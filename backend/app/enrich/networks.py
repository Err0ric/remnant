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

import functools
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


@functools.lru_cache(maxsize=262_144)
def parse_address(address: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """The address, or None for text that is not one. Cached: pages ask about the same
    addresses on every load, and parsing was most of their Python time (owner, 2026-11-01)."""
    try:
        return ipaddress.ip_address(address.strip())
    except ValueError:
        return None


def is_internal(address: str, nets: Iterable[Network]) -> bool:
    """True when the address is in one of the networks; text that is not an address is
    never internal (the caller decides what to do with it)."""
    ip = parse_address(address)
    if ip is None:
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


# Text that is plainly one address, in the forms `ipaddress` reads the same way: dotted
# IPv4 with no leading zeros, and IPv6 of hex groups with at most one "::". Anything else
# (spaces, a zone, an embedded IPv4 tail) goes to the `is_internal` function, so the answer
# is always the one Python gives (owner, 2026-11-07: per-row Python made People and
# devices slow).
_V4_OCTET = "(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])"
_V4_RE = rf"({_V4_OCTET}\.){{3}}{_V4_OCTET}"
_V6_GROUPS = "([0-9a-f]{1,4}:)*[0-9a-f]{1,4}"
_V6_FULL_RE = "([0-9a-f]{1,4}:){7}[0-9a-f]{1,4}"
_V6_SKIP_RE = f"({_V6_GROUPS})?::({_V6_GROUPS})?"


def _v4_int(col: str) -> str:
    parts = [f"CAST(split_part({col}, '.', {i}) AS BIGINT)" for i in (1, 2, 3, 4)]
    return f"({parts[0]} * 16777216 + {parts[1]} * 65536 + {parts[2]} * 256 + {parts[3]})"


def _hex_groups(part: str) -> str:
    """Colon-separated groups as one hex string, each group padded to 4 digits."""
    padded = f"regexp_replace({part}, '([0-9a-f]+)', '000\\1', 'g')"
    return f"replace(regexp_replace({padded}, '0*([0-9a-f]{{4}})(:|$)', '\\1\\2', 'g'), ':', '')"


def _groups(part: str) -> str:
    colons = f"length({part}) - length(replace({part}, ':', ''))"
    return f"CASE WHEN {part} = '' THEN 0 ELSE {colons} + 1 END"


def internal_sql(col: str, nets: Iterable[Network]) -> str:
    """A SQL expression with the answer `is_internal(col)` gives for these networks,
    worked out in SQL for plain IPv4 and IPv6 text (integer and fixed-width hex range
    checks) and by the `is_internal` function only for anything else. `col` is a fixed
    column expression; the networks become numeric and hex literals."""
    v4 = [n for n in nets if n.version == 4]
    v6 = [n for n in nets if n.version == 6]
    num = _v4_int(col)
    in_v4 = " OR ".join(
        f"{num} BETWEEN {int(n.network_address)} AND {int(n.broadcast_address)}" for n in v4
    )
    low = f"lower({col})"
    left, right = f"split_part({low}, '::', 1)", f"split_part({low}, '::', 2)"
    full = f"{_hex_groups(low)}"
    skip = (
        f"{_hex_groups(left)} || repeat('0000', 8 - {_groups(left)} - {_groups(right)})"
        f" || {_hex_groups(right)}"
    )
    ranges = [
        (format(int(n.network_address), "032x"), format(int(n.broadcast_address), "032x"))
        for n in v6
    ]

    def in_v6(h: str) -> str:
        return " OR ".join(f"({h}) BETWEEN '{lo}' AND '{hi}'" for lo, hi in ranges) or "false"

    return (
        f"CASE WHEN regexp_full_match({col}, '{_V4_RE}') THEN ({in_v4 or 'false'})"
        f" WHEN regexp_full_match({low}, '{_V6_FULL_RE}') THEN ({in_v6(full)})"
        f" WHEN regexp_full_match({low}, '{_V6_SKIP_RE}')"
        f" AND {_groups(left)} + {_groups(right)} <= 7 THEN ({in_v6(skip)})"
        f" ELSE is_internal({col}) END"
    )
