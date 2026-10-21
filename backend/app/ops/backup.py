"""Back up and restore the data folder (events, settings, users, audit log, the key).

A backup is one gzip tar with `manifest.json` first: what it holds, the database
schema version, and a SHA-256 per file. It can be taken while the server runs:

- `meta.sqlite` is copied with SQLite's online backup, so it is consistent.
- Lake files are copied under the lake lock, so compaction and retention cannot
  rewrite a partition mid-copy. New events written during the copy may or may not
  be included.
- `.key` is included by default (without it, stored passwords and tokens for AI
  providers, alert targets, and Loki cannot be decrypted). `include_key=False` leaves
  it out for copies kept somewhere less trusted.

Restore checks every hash before writing anything, refuses unsafe paths, refuses a
backup from a newer schema than this code knows, and never writes over a data folder
that is not empty unless asked; then the old one is moved aside, not deleted.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import IO, Any

from app.core.branding import PRODUCT_NAME
from app.ingest.lakelock import lake_lock
from app.meta.db import MIGRATIONS
from app.meta.secrets import KEY_NAME

FORMAT = 1
MANIFEST = "manifest.json"
# What a data folder holds. Anything else in it (stray files, backups) is not copied.
TREES = ("lake", "templates", "tls", "enrichment")
SKIP_SUFFIXES = (".tmp", ".lock")
KEPT_PREFIX = ".before-restore-"


class BackupError(Exception):
    """The backup cannot be made, read, or restored; the message says why."""


@dataclass(frozen=True, slots=True)
class BackupInfo:
    created_at: str
    schema_version: int
    files: int
    bytes: int
    has_key: bool


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _schema_version(db: Path) -> int:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT max(version) FROM schema_migrations").fetchone()
    finally:
        con.close()
    return int(row[0] or 0)


def _tree_files(root: Path) -> Iterator[Path]:
    if not root.is_dir() or root.is_symlink():
        return
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file() or path.name.endswith(SKIP_SUFFIXES):
            continue
        yield path


def create(data_dir: Path, out: IO[bytes], include_key: bool = True) -> BackupInfo:
    """Write a backup of `data_dir` to the binary stream `out`."""
    db = data_dir / "meta.sqlite"
    if not db.is_file():
        raise BackupError(f"No database at {db}: is this the right data folder?")
    with tempfile.TemporaryDirectory(prefix="backup-") as tmp:
        stage = Path(tmp)
        src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        dst = sqlite3.connect(stage / "meta.sqlite")
        try:
            src.backup(dst)  # consistent copy while the server keeps writing
        finally:
            dst.close()
            src.close()
        entries: list[tuple[str, Path]] = [("meta.sqlite", stage / "meta.sqlite")]
        key = data_dir / KEY_NAME
        if include_key and key.is_file():
            entries.append((KEY_NAME, key))
        with lake_lock(data_dir / "lake"):
            # Hold the lock until the lake files are in the archive, not just listed.
            for tree in TREES:
                for path in _tree_files(data_dir / tree):
                    entries.append((path.relative_to(data_dir).as_posix(), path))
            files: list[dict[str, Any]] = [
                {"path": name, "sha256": _sha256(path), "bytes": path.stat().st_size}
                for name, path in entries
            ]
            manifest: dict[str, Any] = {
                "format": FORMAT,
                "product": PRODUCT_NAME,
                "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "schema_version": _schema_version(stage / "meta.sqlite"),
                "has_key": any(name == KEY_NAME for name, _ in entries),
                "files": files,
            }
            with tarfile.open(fileobj=out, mode="w|gz") as tar:
                body = json.dumps(manifest, indent=1).encode()
                info = tarfile.TarInfo(MANIFEST)
                info.size, info.mode = len(body), 0o600
                tar.addfile(info, io.BytesIO(body))
                for (name, path), meta in zip(entries, files, strict=True):
                    info = tarfile.TarInfo(name)
                    info.size, info.mode = int(meta["bytes"]), 0o600
                    info.mtime = int(path.stat().st_mtime)
                    with path.open("rb") as fh:
                        tar.addfile(info, fh)
    return BackupInfo(
        str(manifest["created_at"]),
        int(manifest["schema_version"]),
        len(files),
        sum(int(f["bytes"]) for f in files),
        bool(manifest["has_key"]),
    )


def _safe_name(name: str) -> bool:
    p = PurePosixPath(name)
    return (
        bool(name)
        and not p.is_absolute()
        and ".." not in p.parts
        and "\\" not in name
        and (p.parts[0] in (*TREES, "meta.sqlite", KEY_NAME))
    )


def verify(archive: Path, into: Path | None = None) -> tuple[BackupInfo, dict[str, Any]]:
    """Check the archive against its manifest; with `into`, also extract the files there."""
    try:
        tar = tarfile.open(archive, mode="r:gz")
    except (tarfile.TarError, OSError) as exc:
        raise BackupError(f"Not a readable backup: {exc}") from exc
    with tar:
        members = tar.getmembers()
        if not members or members[0].name != MANIFEST:
            raise BackupError("Not a backup made by app-admin backup (no manifest)")
        fh = tar.extractfile(members[0])
        if fh is None:
            raise BackupError("The manifest is unreadable")
        manifest: dict[str, Any] = json.loads(fh.read())
        if manifest.get("format") != FORMAT:
            raise BackupError(f"Unknown backup format {manifest.get('format')!r}")
        expected = {f["path"]: f for f in manifest["files"]}
        seen: set[str] = set()
        for m in members[1:]:
            if not m.isfile() or not _safe_name(m.name) or m.name not in expected:
                raise BackupError(f"Unexpected or unsafe entry in the backup: {m.name!r}")
            if m.name in seen:
                raise BackupError(f"Entry appears twice: {m.name!r}")
            seen.add(m.name)
            src = tar.extractfile(m)
            if src is None:
                raise BackupError(f"Unreadable entry: {m.name!r}")
            h = hashlib.sha256()
            target = (into / m.name) if into else None
            out: IO[bytes] | None = None
            if target is not None:
                target.parent.mkdir(parents=True, exist_ok=True)
                out = target.open("wb")
            try:
                while block := src.read(1 << 20):
                    h.update(block)
                    if out is not None:
                        out.write(block)
            finally:
                if out is not None:
                    out.close()
            if h.hexdigest() != expected[m.name]["sha256"]:
                raise BackupError(f"Checksum mismatch for {m.name}: the backup is damaged")
        missing = set(expected) - seen
        if missing:
            raise BackupError(f"The backup is missing {len(missing)} file(s), e.g. {min(missing)}")
    info = BackupInfo(
        str(manifest["created_at"]),
        int(manifest["schema_version"]),
        len(expected),
        sum(int(f["bytes"]) for f in expected.values()),
        bool(manifest.get("has_key")),
    )
    return info, manifest


def restore(archive: Path, data_dir: Path, replace: bool = False) -> tuple[BackupInfo, Path | None]:
    """Restore into `data_dir`. Returns the info and where the previous contents were moved.

    Works on a mount point too (a Docker volume): entries are moved inside the folder,
    never the folder itself, and the previous contents go to `.before-restore-<time>/`.
    """
    info, _ = verify(archive)  # every hash checked before anything is written
    if info.schema_version > len(MIGRATIONS):
        raise BackupError(
            f"This backup is from a newer version (database schema {info.schema_version},"
            f" this code knows {len(MIGRATIONS)}). Update the code first."
        )
    data_dir.mkdir(parents=True, exist_ok=True)
    current = [p for p in data_dir.iterdir() if not p.name.startswith(KEPT_PREFIX)]
    if current and not replace:
        raise BackupError(
            f"{data_dir} is not empty. Stop the server, then run again with --replace;"
            " the current contents are kept beside the restored ones, not deleted."
        )
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    stage = data_dir / f".restore-{stamp}"
    stage.mkdir(mode=0o700)
    try:
        verify(archive, into=stage)
        for path in stage.rglob("*"):
            os.chmod(path, 0o700 if path.is_dir() else 0o600)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    kept: Path | None = None
    if current:
        kept = data_dir / f"{KEPT_PREFIX}{stamp}"
        kept.mkdir(mode=0o700)
        for path in current:
            os.replace(path, kept / path.name)
    for path in stage.iterdir():
        os.replace(path, data_dir / path.name)
    stage.rmdir()
    return info, kept
