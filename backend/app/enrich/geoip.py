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
            reader = self._reader
        try:
            return reader.get(ip) if reader is not None else None
        except ValueError:
            return None

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

    def available(self) -> bool:
        return self._country.available() or self._asn.available()

    def lookup(self, value: str) -> GeoInfo | None:
        try:
            addr = ipaddress.ip_address(value)
        except ValueError:
            return None
        if not self._public(addr):
            return None
        text = str(addr)
        c = self._country.get(text) or {}
        a = self._asn.get(text) or {}
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
        out: dict[str, GeoInfo] = {}
        seen: set[str] = set()
        for v in values:
            if not isinstance(v, str) or v in seen or not _LOOKS_LIKE_IP.match(v):
                continue
            seen.add(v)
            if len(seen) > limit:
                break
            info = self.lookup(v)
            if info is not None:
                out[v] = info
        return out


def _text(value: Any, cap: int) -> str | None:
    """Feed text is untrusted like log content: strings only, capped."""
    return value[:cap] if isinstance(value, str) and value else None
