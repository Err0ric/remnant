"""Approved countries and internal networks (ADR-0038 edit 1 and edit 10, calls 6 and 8).

Both are install settings an admin keeps in Settings > Enrichment; none ship in the repo.

- Approved countries: ISO 3166 two-letter codes. Empty means not set: the Dashboard then
  asks for them instead of counting "outside approved countries".
- Internal networks: addresses and ranges, private or public (an office's egress is
  public). "External" means not in this list. Until an admin saves one, it is the private,
  loopback, and link-local ranges below, and Settings asks for the company's egress.

Countries come from local GeoIP at query time (ADR-0023); nothing here leaves the server.
"""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.meta.db import MetaDB

Network = ipaddress.IPv4Network | ipaddress.IPv6Network

DEFAULT_INTERNAL: tuple[str, ...] = (
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "fc00::/7",
    "fe80::/10",
    "::1/128",
)
MAX_COUNTRIES = 250
MAX_NETWORKS = 500


def parse_network(text: str) -> Network:
    """A range ("198.51.100.0/24") or one address ("198.51.100.7"); host bits are dropped."""
    return ipaddress.ip_network(text.strip(), strict=False)


def is_private(net: Network) -> bool:
    """Inside the default ranges: a list with only these has no company egress yet."""
    defaults = [parse_network(d) for d in DEFAULT_INTERNAL]
    return any(net.version == d.version and net.subnet_of(d) for d in defaults)  # type: ignore[arg-type]  # same version checked first


@dataclass(frozen=True, slots=True)
class Places:
    approved_countries: tuple[str, ...]
    internal_networks: tuple[str, ...]
    internal_set: bool  # False: the defaults, never saved by an admin
    updated_at: str | None

    @property
    def has_public(self) -> bool:
        """Some entry is public (a company egress); else Settings asks for one."""
        return any(not is_private(parse_network(n)) for n in self.internal_networks)

    def networks(self) -> list[Network]:
        return [parse_network(n) for n in self.internal_networks]


def is_internal(address: str, nets: Iterable[Network]) -> bool:
    """True when the address is in one of the networks; text that is not an address is
    never internal (the caller decides what to do with it)."""
    try:
        ip = ipaddress.ip_address(address.strip())
    except ValueError:
        return False
    return any(ip.version == n.version and ip in n for n in nets)


def load(meta: MetaDB) -> Places:
    with meta.connect() as con:
        row = con.execute(
            "SELECT approved_countries, internal_networks, places_updated_at"
            " FROM install_settings WHERE id = 1"
        ).fetchone()
    countries: list[str] = json.loads(row[0]) if row and row[0] else []
    saved: list[str] | None = json.loads(row[1]) if row and row[1] is not None else None
    return Places(
        approved_countries=tuple(countries),
        internal_networks=tuple(saved if saved is not None else DEFAULT_INTERNAL),
        internal_set=saved is not None,
        updated_at=str(row[2]) if row and row[2] else None,
    )


def save(meta: MetaDB, countries: list[str], networks: list[str], user_id: str) -> Places:
    """Store both lists as given (already validated); returns what is now in force."""
    now = datetime.now(UTC).isoformat()
    with meta.connect() as con:
        con.execute(
            "INSERT INTO install_settings (id, approved_countries, internal_networks,"
            " places_updated_at, updated_by) VALUES (1, ?, ?, ?, ?)"
            " ON CONFLICT (id) DO UPDATE SET approved_countries = excluded.approved_countries,"
            " internal_networks = excluded.internal_networks,"
            " places_updated_at = excluded.places_updated_at, updated_by = excluded.updated_by",
            (json.dumps(countries), json.dumps(networks), now, user_id),
        )
    return load(meta)
