"""Entity lookup for the top bar search (ADR-0038 edit 10): type an address, a user, a host,
or an AI service and go to its page.

Addresses, users, and hosts come from SQL over the caller's own `events` view through the
guard, so a value from a source the viewer cannot read is never offered. The typed text is a
bound parameter, never formatted into SQL. AI services come from the catalog (names, not
events), which every role can read on AI usage.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.ai.catalog import Service
from app.engine.duckdb import QueryEngine, QueryScope
from app.search.identity import IdentityMap

TIMEOUT_S = 5
PER_KIND = 5

# One branch per kind and column. Addresses match from the start ("203.0.113" finds
# 203.0.113.77); names match anywhere, ignoring case. Exact matches rank first, then
# names that start with the text, then the busiest.
_BRANCH = """
SELECT '{kind}' AS kind, {col} AS value, coalesce(time, time_observed) AS t
FROM events WHERE {col} IS NOT NULL AND {match}"""

_PREFIX = "starts_with({col}, $q)"
_CONTAINS = "contains(lower({col}), $lq)"

_COLUMNS: list[tuple[str, str, str]] = [
    ("ip", "src_endpoint_ip", _PREFIX),
    ("ip", "dst_endpoint_ip", _PREFIX),
    ("user", "actor_user_name", _CONTAINS),
    ("host", "device_hostname", _CONTAINS),
    ("host", "src_endpoint_hostname", _CONTAINS),
    ("host", "dst_endpoint_hostname", _CONTAINS),
]

_TEMPLATE = """WITH hits AS ({branches}
), grouped AS (
  SELECT kind, value, count(*) AS n, max(t) AS last
  FROM hits WHERE trim(value) <> '' GROUP BY kind, value
)
SELECT kind, value, n, last FROM grouped
QUALIFY row_number() OVER (
  PARTITION BY kind
  ORDER BY (lower(value) = $lq) DESC, starts_with(lower(value), $lq) DESC, n DESC, value
) <= {per}
ORDER BY kind, (lower(value) = $lq) DESC, starts_with(lower(value), $lq) DESC, n DESC, value"""


def _build() -> str:
    """Built once from the constant column list above; the typed text is only ever the
    bound $q and $lq."""
    branches = " UNION ALL ".join(
        _BRANCH.format(kind=k, col=c, match=m.format(col=c)) for k, c, m in _COLUMNS
    )
    return _TEMPLATE.format(branches=branches, per=PER_KIND)


LOOKUP_SQL = _build()


@dataclass(slots=True)
class Hit:
    kind: str  # ip | user | host | service
    value: str  # what the entity page opens with (the service id for a service)
    label: str  # what the list shows
    events: int | None
    last_seen: str | None
    aliases: list[str] = field(default_factory=list)  # other forms of the same person


@dataclass(slots=True)
class Lookup:
    hits: list[Hit] = field(default_factory=list)
    read: list[str] = field(default_factory=list)


def _iso(value: object) -> str | None:
    if value is None:
        return None
    iso = getattr(value, "isoformat", None)
    return str(iso()) if callable(iso) else str(value)


def _services(services: list[Service], q: str) -> list[Hit]:
    lq = q.lower()
    found = [
        s
        for s in services
        if lq in s.name.lower() or lq in s.id or lq in s.vendor.lower() or lq in s.domains
    ]
    found.sort(key=lambda s: (s.name.lower() != lq, not s.name.lower().startswith(lq), s.name))
    return [Hit("service", s.id, s.name, None, None) for s in found[:PER_KIND]]


def lookup(
    engine: QueryEngine,
    scope: QueryScope,
    q: str,
    services: list[Service],
    ident: IdentityMap | None = None,
) -> Lookup:
    """Up to five of each kind matching `q`, from the events the caller can read. With
    `ident`, the forms of one person (short name, DOMAIN\\user, organization email, and
    the aliases an administrator set: ADR-0018) are one row, its other forms listed."""
    text = q.strip()
    res = engine.run(
        LOOKUP_SQL,
        scope,
        {"q": text, "lq": text.lower()},
        timeout_s=TIMEOUT_S,
        name="lookup",
    )
    hits = [
        Hit(
            kind=str(kind),
            value=str(value),
            label=str(value),
            events=int(n),
            last_seen=_iso(last),
        )
        for kind, value, n, last in res.rows
    ]
    if ident is not None:
        hits = merge_people(hits, ident)
    return Lookup(hits=hits + _services(services, text), read=res.sources)


def merge_people(hits: list[Hit], ident: IdentityMap) -> list[Hit]:
    """User hits with the same person key as one: the busiest form leads (its value opens
    the person page, which resolves every form), the others are its aliases."""
    out: list[Hit] = []
    by_key: dict[str, Hit] = {}
    for h in hits:
        if h.kind != "user":
            out.append(h)
            continue
        k = ident.key(h.value)
        seen = by_key.get(k)
        if seen is None:
            by_key[k] = h
            out.append(h)
            continue
        seen.aliases.append(h.value)
        seen.events = (seen.events or 0) + (h.events or 0)
        if h.last_seen and (seen.last_seen is None or h.last_seen > seen.last_seen):
            seen.last_seen = h.last_seen
    for h in by_key.values():
        h.aliases = sorted(set(h.aliases) - {h.value}, key=str.lower)
    return out
