"""Source configuration and the allowed-roots rule (CLAUDE.md security rule 6, SPEC T11)."""

import errno
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.core.errors import NotFoundError, SourceRejectedError
from app.core.ids import AUTO_PARSER, RESERVED_SOURCE_PREFIX
from app.ingest.connectors.loki import LokiSettings
from app.ingest.envelope import SyslogEnvelopeConfig
from app.ingest.normalizer import SourceFormat, SourceSpec
from app.meta.db import MetaDB
from app.meta.secrets import SecretBox


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    format: SourceFormat
    # file: a file or folder under allowed_roots. loki: lines pulled from Grafana Loki
    # (ADR-0011), and `path` is empty.
    kind: Literal["file", "loki"] = "file"
    path: str = Field(default="", max_length=4096)
    loki: LokiSettings | None = None
    glob: str = Field(default="*", min_length=1, max_length=200)
    timezone: str = "UTC"
    classification: Literal["local_only", "cloud_allowed"] = "local_only"
    retention_days: int = Field(default=30, ge=1, le=3650)
    enabled: bool = True
    # Parse with this template (SPEC 4); None uses the generic parser for `format`;
    # `auto` picks a template per line (ADR-0012).
    template_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{1,63}$")

    @field_validator("source_id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        SourceSpec(source_id=value, format="syslog")  # reuse the lake-safe id rule
        return value

    @field_validator("glob")
    @classmethod
    def _safe_glob(cls, value: str) -> str:
        if value.startswith("/") or ".." in Path(value).parts:
            raise ValueError("glob must be relative and must not contain '..'")
        return value

    @model_validator(mode="after")
    def _auto_formats(self) -> "SourceConfig":
        if self.template_id == AUTO_PARSER and self.format == "csv":
            raise ValueError("Automatic parsing is for syslog and JSON sources, not CSV")
        return self

    @model_validator(mode="after")
    def _kind_fields(self) -> "SourceConfig":
        if self.kind == "file":
            if not self.path:
                raise ValueError("A file source needs a path")
            if self.loki is not None:
                raise ValueError("Loki settings are only for Loki sources")
        else:
            if self.loki is None:
                raise ValueError("A Loki source needs its Loki settings")
            if self.path:
                raise ValueError("A Loki source has no path")
        return self

    def spec(self, owner_id: str = "local") -> SourceSpec:
        return SourceSpec(
            source_id=self.source_id,
            format=self.format,
            classification=self.classification,
            owner_id=owner_id,
            envelope=SyslogEnvelopeConfig(timezone=self.timezone),
        )


def resolve_source_path(path: Path | str, allowed_roots: list[Path]) -> Path:
    """Resolve symlinks and require the real path to sit under an allowed root."""
    if not allowed_roots:
        raise SourceRejectedError(
            "No folders are allowed yet. Set paths.allowed_roots (or APP__PATHS__ALLOWED_ROOTS) "
            "to the log folders this server may read."
        )
    real = Path(os.path.realpath(path))
    if not real.exists():
        raise SourceRejectedError(f"Path does not exist: {path}")
    for root in allowed_roots:
        root_real = Path(os.path.realpath(root))
        if real == root_real or root_real in real.parents:
            return real
    raise SourceRejectedError(f"Path is outside the allowed roots: {path}")


def path_key(path: Path) -> str:
    """Text form of a path for checkpoints and status.

    A name that is not valid UTF-8 decodes to lone surrogates, which sqlite and JSON refuse;
    one such name once stopped every source. Those paths are keyed by their bytes instead,
    under a prefix no absolute path can start with, so two names never share a checkpoint.
    """
    text = str(path)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return "fsbytes:" + os.fsencode(path).hex()
    return text


def display_name(name: str) -> str:
    """A file or folder name safe to show and serialize: undecodable bytes become U+FFFD."""
    return name.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


def _inside(real: Path, allowed_roots: list[Path]) -> bool:
    for root in allowed_roots:
        root_real = Path(os.path.realpath(root))
        if real == root_real or root_real in real.parents:
            return True
    return False


def open_regular(path: Path, allowed_roots: list[Path]) -> BinaryIO:
    """Open a log file for reading, refusing anything that is not a regular file inside the
    allowed roots at the moment it is opened.

    A FIFO or device swapped in after the directory listing would otherwise block open()
    or read() forever and stall ingest. O_NONBLOCK makes open() return at once, O_NOFOLLOW
    refuses a symlink swapped in for the file itself, and fstat on the open descriptor is
    the check that counts. O_NOFOLLOW only covers the last component, so a parent folder
    swapped for a symlink after the path was resolved is caught by checking where the open
    descriptor really points.
    """
    nonblock = getattr(os, "O_NONBLOCK", 0)  # not on Windows, where FIFOs do not apply
    fd = os.open(path, os.O_RDONLY | nonblock | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise OSError(errno.EINVAL, "not a regular file", str(path))
        if os.path.isdir("/proc/self/fd"):
            real = Path(os.readlink(f"/proc/self/fd/{fd}"))
        else:  # no /proc (macOS development): the resolved path must be this same file
            real = Path(os.path.realpath(path))
            now = os.stat(real)
            if (now.st_dev, now.st_ino) != (info.st_dev, info.st_ino):
                raise OSError(errno.EACCES, "file changed while opening", str(path))
        if not _inside(real, allowed_roots):
            raise OSError(errno.EACCES, "outside the allowed roots when opened", str(path))
        if nonblock:
            os.set_blocking(fd, True)
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise


def files_for(source: SourceConfig, allowed_roots: list[Path]) -> list[Path]:
    """Files a source covers right now. Every file is re-checked against the roots."""
    if source.kind != "file":
        return []
    base = resolve_source_path(source.path, allowed_roots)
    if base.is_file():
        return [base]
    out = []
    for candidate in sorted(base.glob(source.glob)):
        if not candidate.is_file():
            continue
        try:
            out.append(resolve_source_path(candidate, allowed_roots))
        except SourceRejectedError:
            continue  # e.g. a symlink pointing outside the roots
    return out


class SourceStore:
    def __init__(
        self, meta: MetaDB, allowed_roots: list[Path], box: SecretBox | None = None
    ) -> None:
        self._meta = meta
        self.allowed_roots = allowed_roots
        self._box = box

    def add(self, source: SourceConfig, secret: str | None = None) -> SourceConfig:
        # Checked here, not in SourceConfig, so a row stored before the rule still loads.
        if source.source_id.startswith(RESERVED_SOURCE_PREFIX):
            raise SourceRejectedError(
                f"Source ids starting with {RESERVED_SOURCE_PREFIX} are reserved"
            )
        if source.kind == "file":
            resolve_source_path(source.path, self.allowed_roots)
        if secret and self._box is None:
            raise SourceRejectedError("Credentials cannot be stored on this server")
        secret_enc = self._box.encrypt(secret) if secret and self._box else None
        connector = source.loki.model_dump_json() if source.loki else None
        with self._meta.connect() as con:
            if con.execute(
                "SELECT 1 FROM sources WHERE source_id = ?", (source.source_id,)
            ).fetchone():
                raise SourceRejectedError(f"A source named {source.source_id} already exists")
            con.execute(
                "INSERT INTO sources (source_id, format, path, glob, timezone, classification,"
                " retention_days, enabled, template_id, created_at, kind, connector,"
                " connector_secret_enc)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    source.source_id,
                    source.format,
                    source.path,
                    source.glob,
                    source.timezone,
                    source.classification,
                    source.retention_days,
                    int(source.enabled),
                    source.template_id,
                    datetime.now(UTC).isoformat(),
                    source.kind,
                    connector,
                    secret_enc,
                ),
            )
        return source

    def list(self) -> list[SourceConfig]:
        with self._meta.connect() as con:
            rows = con.execute("SELECT * FROM sources ORDER BY source_id").fetchall()
        return [
            SourceConfig(
                source_id=r["source_id"],
                format=r["format"],
                path=r["path"],
                glob=r["glob"],
                timezone=r["timezone"],
                classification=r["classification"],
                retention_days=r["retention_days"],
                enabled=bool(r["enabled"]),
                template_id=r["template_id"],
                kind=r["kind"],
                loki=LokiSettings.model_validate_json(r["connector"])
                if r["kind"] == "loki" and r["connector"]
                else None,
            )
            for r in rows
        ]

    def connector_secret(self, source_id: str) -> str | None:
        """Decrypted connector credential, for the ingest worker and the connection test."""
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT connector_secret_enc FROM sources WHERE source_id = ?", (source_id,)
            ).fetchone()
        if row is None or row["connector_secret_enc"] is None or self._box is None:
            return None
        return self._box.decrypt(row["connector_secret_enc"])

    def set_classification(
        self, source_id: str, classification: Literal["local_only", "cloud_allowed"]
    ) -> tuple[str, SourceConfig]:
        """The previous label and the source after the change. Events already stored keep
        the label they were written with (CLAUDE.md rule 6); only new events take this one.
        Raises NotFoundError for an unknown source."""
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT classification FROM sources WHERE source_id = ?", (source_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("No such source")
            con.execute(
                "UPDATE sources SET classification = ? WHERE source_id = ?",
                (classification, source_id),
            )
        (source,) = [s for s in self.list() if s.source_id == source_id]
        return str(row["classification"]), source

    def set_parser(
        self, source_id: str, template_id: str | None
    ) -> tuple[str | None, SourceConfig]:
        """The previous parser and the source after the change (ADR-0012). Reading continues
        from the saved position, so only lines read from now on use the new parser; stored
        events keep the one they were read with. Raises NotFoundError for an unknown source
        and SourceRejectedError when the parser does not suit the source's format."""
        found = [s for s in self.list() if s.source_id == source_id]
        if not found:
            raise NotFoundError("No such source")
        before = found[0].template_id
        try:
            SourceConfig.model_validate({**found[0].model_dump(), "template_id": template_id})
        except ValidationError as exc:
            msg = str(exc.errors()[0]["msg"]).removeprefix("Value error, ")
            raise SourceRejectedError(msg) from exc
        with self._meta.connect() as con:
            con.execute(
                "UPDATE sources SET template_id = ? WHERE source_id = ?", (template_id, source_id)
            )
        (source,) = [s for s in self.list() if s.source_id == source_id]
        return before, source

    def delete(self, source_id: str) -> bool:
        """Remove the configuration. Data already in the lake stays until retention removes it."""
        with self._meta.connect() as con:
            cur = con.execute("DELETE FROM sources WHERE source_id = ?", (source_id,))
            # A source added again under this id starts its Loki position afresh.
            con.execute("DELETE FROM connector_checkpoints WHERE source_id = ?", (source_id,))
            return cur.rowcount > 0
