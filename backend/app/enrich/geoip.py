"""GeoIP/ASN lookups against the local DB-IP (or uploaded MaxMind) files (ADR-0023 row 6).

Lookups never leave the server. Files are reopened when they change on disk, so an
update or upload takes effect on the next query without a restart.
"""

from __future__ import annotations

import ipaddress
import re
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import maxminddb
import structlog

from app.enrich.feeds import FeedStore

log = structlog.get_logger(__name__)

MAX_LOOKUPS = 1000  # distinct addresses per response
CACHE_MAX = 200_000  # addresses kept between pages; emptied past this or on a new file
_LOOKS_LIKE_IP = re.compile(r"^[0-9a-fA-F:.]{3,45}$")


def is_public(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return addr.is_global and not addr.is_multicast


@dataclass(frozen=True, slots=True)
class GeoInfo:
    country: str | None
    country_name: str | None
    asn: int | None
    org: str | None


class _Reader:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._stamp: tuple[float, int] | None = None
        self._reader: Any = None
        self._lock = threading.Lock()

    def get(self, ip: str) -> Any:
        reader = self.current()
        try:
            return reader.get(ip) if reader is not None else None
        except ValueError:
            return None

    def current(self) -> Any:
        """The open reader, reopened when the file changed; one stat per call, so a page
        that looks up thousands of addresses stats the file once, not per address."""
        with self._lock:
            try:
                st = self._path.stat()
            except OSError:
                self._close()
                return None
            stamp = (st.st_mtime, st.st_size)
            if stamp != self._stamp:
                self._close()
                try:
                    self._reader = maxminddb.open_database(str(self._path))
                    self._stamp = stamp
                except Exception as exc:  # a broken file means no answers, not an error
                    log.warning("geoip.open_failed", error=type(exc).__name__)
                    return None
            return self._reader

    @property
    def stamp(self) -> tuple[float, int] | None:
        return self._stamp

    def available(self) -> bool:
        return self._path.is_file()

    def _close(self) -> None:
        if self._reader is not None:
            self._reader.close()
        self._reader, self._stamp = None, None


class GeoIP:
    def __init__(
        self,
        feeds: FeedStore,
        public: Callable[[ipaddress.IPv4Address | ipaddress.IPv6Address], bool] = is_public,
    ) -> None:
        self._country = _Reader(feeds.path("geoip_country"))
        self._asn = _Reader(feeds.path("geoip_asn"))
        self._public = public
        self._cache: dict[str, GeoInfo | None] = {}
        self._cache_stamps: tuple[Any, Any] = (None, None)
        self._cache_lock = threading.Lock()

    def available(self) -> bool:
        return self._country.available() or self._asn.available()

    def lookup(self, value: str) -> GeoInfo | None:
        return self._lookup(value, self._country.current(), self._asn.current())

    def _lookup(self, value: str, country_db: Any, asn_db: Any) -> GeoInfo | None:
        try:
            addr = ipaddress.ip_address(value)
        except ValueError:
            return None
        if not self._public(addr):
            return None
        text = str(addr)
        c = _get(country_db, text) or {}
        a = _get(asn_db, text) or {}
        country = c.get("country") or c.get("registered_country") or {}
        info = GeoInfo(
            country=_text(country.get("iso_code"), 2),
            country_name=_text((country.get("names") or {}).get("en"), 80),
            asn=a.get("autonomous_system_number")
            if isinstance(a.get("autonomous_system_number"), int)
            else None,
            org=_text(a.get("autonomous_system_organization"), 120),
        )
        return info if (info.country or info.asn) else None

    def enrich(self, values: Iterable[Any], limit: int = MAX_LOOKUPS) -> dict[str, GeoInfo]:
        """Distinct IP-shaped strings among `values`, up to `limit`, that resolve."""
        if not self.available():
            return {}
        # The files once per call, and answers kept until either file changes (owner,
        # 2026-11-01: per-address file checks and lookups were most of a page's Python).
        cdb, adb = self._country.current(), self._asn.current()
        stamps = (self._country.stamp, self._asn.stamp)
        with self._cache_lock:
            if stamps != self._cache_stamps or len(self._cache) > CACHE_MAX:
                self._cache, self._cache_stamps = {}, stamps
            cache = self._cache
        out: dict[str, GeoInfo] = {}
        seen: set[str] = set()
        for v in values:
            if not isinstance(v, str) or v in seen or not _LOOKS_LIKE_IP.match(v):
                continue
            seen.add(v)
            if len(seen) > limit:
                break
            if v in cache:
                info = cache[v]
            else:
                info = cache[v] = self._lookup(v, cdb, adb)
            if info is not None:
                out[v] = info
        return out


def _get(reader: Any, ip: str) -> Any:
    try:
        return reader.get(ip) if reader is not None else None
    except ValueError:
        return None


def _text(value: Any, cap: int) -> str | None:
    """Feed text is untrusted like log content: strings only, capped."""
    return value[:cap] if isinstance(value, str) and value else None
