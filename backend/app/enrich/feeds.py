"""Enrichment feeds (ADR-0023): which files exist, where they live, and their state.

Each feed is one file under `data/enrichment/<feed_id>/`. A new file is checked in a
temporary path and swapped in with a rename; the file it replaces is kept as
`previous`. State (edition, hashes, last check, last error) lives in `enrichment_feeds`.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import uuid
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import maxminddb

from app.core.errors import ParamInvalidError, PayloadTooLargeError
from app.enrich import intel
from app.meta.db import MetaDB

MAX_FILE = 100 * 1024 * 1024  # after decompression (ADR-0023 row 5)
Level = Literal["healthy", "attention", "unhealthy", "missing"]
DAY = 86400


@dataclass(frozen=True, slots=True)
class FeedSpec:
    feed_id: str
    label: str
    provider: str
    kind: Literal["geoip_country", "geoip_asn", "intel"]
    host: str  # the only host this feed downloads from (ADR-0023 row 4); "" for uploads only
    terms_url: str
    check_every_s: int
    attention_after_s: int | None  # None: never stale (a list an admin keeps)
    unhealthy_after_s: int | None
    filename: str = "current.mmdb"
    needs_key: bool = False

    @property
    def is_intel(self) -> bool:
        return self.kind == "intel"


FEEDS: dict[str, FeedSpec] = {
    f.feed_id: f
    for f in (
        FeedSpec(
            "geoip_country",
            "GeoIP country",
            "DB-IP Lite",
            "geoip_country",
            "download.db-ip.com",
            "https://db-ip.com/db/lite.php",
            DAY,
            45 * DAY,
            75 * DAY,
        ),
        FeedSpec(
            "geoip_asn",
            "GeoIP ASN",
            "DB-IP Lite",
            "geoip_asn",
            "download.db-ip.com",
            "https://db-ip.com/db/lite.php",
            DAY,
            45 * DAY,
            75 * DAY,
        ),
        FeedSpec(
            "intel_feodo",
            "Botnet C2 addresses",
            "abuse.ch Feodo Tracker",
            "intel",
            "feodotracker.abuse.ch",
            "https://feodotracker.abuse.ch/",
            4 * 3600,
            2 * DAY,
            7 * DAY,
            filename="current.parquet",
        ),
        FeedSpec(
            "intel_threatfox",
            "Indicators of compromise",
            "abuse.ch ThreatFox",
            "intel",
            "threatfox-api.abuse.ch",
            "https://threatfox.abuse.ch/",
            4 * 3600,
            2 * DAY,
            7 * DAY,
            filename="current.parquet",
            needs_key=True,
        ),
        FeedSpec(
            "intel_custom",
            "Your list",
            "Uploaded by an administrator",
            "intel",
            "",
            "",
            0,
            None,
            None,
            filename="current.parquet",
        ),
    )
}
FEODO_URL = "https://feodotracker.abuse.ch/downloads/ipblocklist.csv"
THREATFOX_URL = "https://threatfox-api.abuse.ch/api/v1/"
ATTRIBUTION = ("IP Geolocation by DB-IP", "https://db-ip.com")


def dbip_url(spec: FeedSpec, month: str) -> str:
    """DB-IP names each monthly edition by its month: dbip-country-lite-2026-10.mmdb.gz."""
    name = "country" if spec.kind == "geoip_country" else "asn"
    return f"https://{spec.host}/free/dbip-{name}-lite-{month}.mmdb.gz"


@dataclass(slots=True)
class FeedState:
    feed_id: str
    version: str | None = None
    sha256: str | None = None
    size: int = 0
    entries: int = 0
    source: str | None = None  # download | upload
    installed_at: str | None = None
    checked_at: str | None = None
    error: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    enabled: bool = True
    has_key: bool = False


def _decompress(raw: bytes) -> bytes:
    if raw[:2] != b"\x1f\x8b":
        return raw
    out = bytearray()
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    pos = 0
    while pos < len(raw):
        out += d.decompress(raw[pos : pos + (1 << 20)], MAX_FILE + 1 - len(out))
        if len(out) > MAX_FILE:
            raise PayloadTooLargeError("The file is larger than 100 MB once decompressed")
        if d.unconsumed_tail:
            raise PayloadTooLargeError("The file is larger than 100 MB once decompressed")
        pos += 1 << 20
        if d.eof:
            break
    return bytes(out)


def check_mmdb(spec: FeedSpec, data: bytes) -> tuple[int, str]:
    """Raises ParamInvalidError unless `data` is an MMDB of the feed's kind. Returns the
    node count and the build date."""
    try:
        reader = maxminddb.open_database(io.BytesIO(data), maxminddb.MODE_FD)
        meta = reader.metadata()
        reader.close()
    except Exception as exc:  # any parse failure means not a usable database
        raise ParamInvalidError("Not a MaxMind DB (.mmdb) file") from exc
    kind = meta.database_type.lower()
    wanted = "country" if spec.kind == "geoip_country" else "asn"
    if wanted not in kind or meta.node_count <= 0:
        raise ParamInvalidError(f"This is a {meta.database_type} database, not {spec.label}")
    built = datetime.fromtimestamp(meta.build_epoch, UTC).strftime("%Y-%m-%d")
    return int(meta.node_count), built


class FeedStore:
    def __init__(
        self,
        meta: MetaDB,
        data_dir: Path,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._meta = meta
        self._root = data_dir / "enrichment"
        self._clock = clock

    def path(self, feed_id: str) -> Path:
        return self._root / feed_id / FEEDS[feed_id].filename

    @property
    def intel_file(self) -> Path:
        """The enabled threat intel feeds combined, read by the engine and the matcher."""
        return self._root / "intel" / "indicators.parquet"

    # --- settings -------------------------------------------------------------------------

    def auto_update(self) -> bool:
        with self._meta.connect() as con:
            row = con.execute("SELECT auto_update FROM enrichment_settings WHERE id = 1").fetchone()
        return bool(row[0]) if row else False

    def set_auto_update(self, on: bool, user_id: str | None) -> None:
        with self._meta.connect() as con:
            con.execute(
                "INSERT INTO enrichment_settings (id, auto_update, updated_at, updated_by)"
                " VALUES (1, ?, ?, ?) ON CONFLICT (id) DO UPDATE SET"
                " auto_update = excluded.auto_update, updated_at = excluded.updated_at,"
                " updated_by = excluded.updated_by",
                (int(on), self._clock().isoformat(), user_id),
            )

    # --- state ----------------------------------------------------------------------------

    def state(self, feed_id: str) -> FeedState:
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT version, sha256, size, entries, source, installed_at, checked_at, error,"
                " etag, last_modified, enabled, auth_key IS NOT NULL"
                " FROM enrichment_feeds WHERE feed_id = ?",
                (feed_id,),
            ).fetchone()
        if row is None:
            return FeedState(feed_id)
        if not self.path(feed_id).is_file():  # checked, but no file yet
            return FeedState(
                feed_id,
                checked_at=row[6],
                error=row[7],
                enabled=bool(row[10]),
                has_key=bool(row[11]),
            )
        st = FeedState(feed_id, *row[:10])
        st.enabled, st.has_key = bool(row[10]), bool(row[11])
        return st

    def set_enabled(self, feed_id: str, on: bool) -> None:
        with self._meta.connect() as con:
            con.execute(
                "INSERT INTO enrichment_feeds (feed_id, enabled) VALUES (?, ?)"
                " ON CONFLICT (feed_id) DO UPDATE SET enabled = excluded.enabled",
                (feed_id, int(on)),
            )
        if FEEDS[feed_id].is_intel:
            self.rebuild_intel()

    def set_key(self, feed_id: str, sealed: str | None) -> None:
        """Store a feed's key, already encrypted with the install key (never plain)."""
        with self._meta.connect() as con:
            con.execute(
                "INSERT INTO enrichment_feeds (feed_id, auth_key) VALUES (?, ?)"
                " ON CONFLICT (feed_id) DO UPDATE SET auth_key = excluded.auth_key",
                (feed_id, sealed),
            )

    def sealed_key(self, feed_id: str) -> str | None:
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT auth_key FROM enrichment_feeds WHERE feed_id = ?", (feed_id,)
            ).fetchone()
        return str(row[0]) if row and row[0] else None

    def rebuild_intel(self) -> int:
        """Combine the enabled intel feeds into the one file the engine reads."""
        files = [
            self.path(f)
            for f, spec in FEEDS.items()
            if spec.is_intel and self.path(f).is_file() and self.state(f).enabled
        ]
        return intel.combine(files, self.intel_file)

    def install_intel(
        self,
        feed_id: str,
        rows: list[intel.Indicator],
        source: Literal["download", "upload"],
        version: str | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FeedState:
        """Swap in a threat intel list already parsed and checked."""
        target = self.path(feed_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.copyfile(target, target.with_name("previous.parquet"))
        count = intel.write_parquet(rows, target)
        now = self._clock().isoformat()
        old = self.state(feed_id)
        st = FeedState(
            feed_id,
            version=version or now[:10],
            sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
            size=target.stat().st_size,
            entries=count,
            source=source,
            installed_at=now,
            checked_at=now,
            error=None,
            etag=etag,
            last_modified=last_modified,
            enabled=old.enabled,
            has_key=old.has_key,
        )
        self._save(st)
        self.rebuild_intel()
        return st

    def _save(self, st: FeedState) -> None:
        fields: dict[str, Any] = {
            "version": st.version,
            "sha256": st.sha256,
            "size": st.size,
            "entries": st.entries,
            "source": st.source,
            "installed_at": st.installed_at,
            "checked_at": st.checked_at,
            "error": st.error,
            "etag": st.etag,
            "last_modified": st.last_modified,
        }
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        updates = ", ".join(f"{k} = excluded.{k}" for k in fields)
        with self._meta.connect() as con:
            con.execute(
                f"INSERT INTO enrichment_feeds (feed_id, {cols}) VALUES (?, {marks})"  # noqa: S608  # fixed column names
                f" ON CONFLICT (feed_id) DO UPDATE SET {updates}",
                (st.feed_id, *fields.values()),
            )

    def record_check(self, feed_id: str, error: str | None) -> FeedState:
        st = self.state(feed_id)
        st.checked_at = self._clock().isoformat()
        st.error = error[:300] if error else None
        self._save(st)
        return st

    def install(
        self,
        feed_id: str,
        raw: bytes,
        source: Literal["download", "upload"],
        version: str | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FeedState:
        """Check `raw` (gzip or plain), then swap it in, keeping the old file as previous.
        Nothing changes if the check fails."""
        spec = FEEDS[feed_id]
        data = _decompress(raw)
        if len(data) > MAX_FILE:
            raise PayloadTooLargeError("The file is larger than 100 MB")
        if spec.is_intel:
            rows, bad = intel.parse_for(feed_id, data)
            total = len(rows) + bad
            if total == 0:
                raise ParamInvalidError("The list has no indicators")
            if bad / total > 0.05:  # ADR-0023 row 5: at least 95% valid lines
                raise ParamInvalidError(
                    f"{bad} of {total} lines are not an address, domain, URL, or hash"
                )
            return self.install_intel(feed_id, rows, source, version, etag, last_modified)
        entries, built = check_mmdb(spec, data)
        target = self.path(feed_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.stem}.{uuid.uuid4().hex}.tmp")
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if target.exists():
            os.replace(target, target.with_name("previous.mmdb"))
        os.replace(tmp, target)
        now = self._clock().isoformat()
        st = FeedState(
            feed_id,
            version=version or built,
            sha256=hashlib.sha256(data).hexdigest(),
            size=len(data),
            entries=entries,
            source=source,
            installed_at=now,
            checked_at=now,
            error=None,
            etag=etag,
            last_modified=last_modified,
        )
        self._save(st)
        return st

    def level(self, st: FeedState) -> Level:
        if st.installed_at is None:
            return "missing"
        spec = FEEDS[st.feed_id]
        if spec.attention_after_s is None or spec.unhealthy_after_s is None:
            return "healthy"
        age = (self._clock() - datetime.fromisoformat(st.installed_at)).total_seconds()
        # The edition date matters more than when it was copied here: an old file uploaded
        # today is still old.
        if not spec.is_intel and st.version and len(st.version) >= 7:
            try:
                edition = datetime.fromisoformat(st.version[:7] + "-01").replace(tzinfo=UTC)
                age = max(age, (self._clock() - edition).total_seconds() - 31 * DAY)
            except ValueError:
                pass
        if age >= spec.unhealthy_after_s:
            return "unhealthy"
        if age >= spec.attention_after_s:
            return "attention"
        return "healthy"
