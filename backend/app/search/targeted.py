"""Who counts as a person on People and devices (owner review, 2026-11-06; D212).

An account is a person, listed under Users, when any of its names has a successful
sign-in (a logon that succeeded, not a disconnect or a log off), a known Microsoft 365
identity (an event from a Microsoft 365 source that is not a failed sign-in), or an
Identities link (an administrator's alias to or from it). An account with failed sign-ins
and none of these is a targeted username: password spraying tries names like root, ubuntu,
and oracle that are nobody's, and they are listed apart with the attempts against them.
An account with no sign-in attempts at all stays under Users, as before.

Every count is SQL over the caller's own `events` view; test records are left out.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.ai.test_records import NOT_TEST
from app.core.timing import phase
from app.engine.duckdb import QueryEngine, QueryScope
from app.search.identity import IdentityMap, key_of

TIMEOUT_S = 20.0
MAX_NAMES = 20_000  # distinct names with sign-in or Microsoft 365 events read per load
RANKED = 100
IPS_PER_NAME = 20
TOP_PLACES = 3

_FAIL = "class_uid = 3002 AND status_id = 2"
_OK = "class_uid = 3002 AND status_id = 1 AND activity_id = 1"
_M365 = "template_id LIKE 'm365_%' AND status_id IS DISTINCT FROM 2"
_HOST = "coalesce(nullif(device_hostname, ''), nullif(dst_endpoint_hostname, ''))"

EVIDENCE_SQL = f"""
SELECT actor_user_name AS u,
       count(*) FILTER (WHERE {_FAIL}) AS failed,
       count(*) FILTER (WHERE {_OK}) AS ok,
       count(*) FILTER (WHERE {_M365}) AS m365,
       list(DISTINCT source_id) FILTER (WHERE {_FAIL}) AS sources,
       list(DISTINCT {_HOST}) FILTER (WHERE {_FAIL} AND {_HOST} IS NOT NULL) AS hosts
FROM events
WHERE nullif(trim(actor_user_name), '') IS NOT NULL
  AND (class_uid = 3002 OR template_id LIKE 'm365_%') AND {NOT_TEST}
GROUP BY 1
ORDER BY failed DESC, u
LIMIT {MAX_NAMES}"""  # noqa: S608  # fixed SQL text

ATTACKERS_SQL = f"""
SELECT actor_user_name AS u, src_endpoint_ip AS ip, count(*) AS n
FROM events
WHERE {_FAIL} AND list_contains($names, actor_user_name)
  AND nullif(src_endpoint_ip, '') IS NOT NULL AND {NOT_TEST}
GROUP BY 1, 2
QUALIFY row_number() OVER (PARTITION BY u ORDER BY count(*) DESC, ip) <= {IPS_PER_NAME}"""  # noqa: S608  # fixed SQL text


@dataclass(slots=True)
class Place:
    label: str
    attempts: int


@dataclass(slots=True)
class Targeted:
    value: str
    attempts: int = 0
    sources: list[str] = field(default_factory=list)
    hosts: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    countries: list[Place] = field(default_factory=list)
    asns: list[Place] = field(default_factory=list)
    ips: dict[str, int] = field(default_factory=dict)  # top attacking addresses, not sent


@dataclass(slots=True)
class Split:
    people: set[str]  # person keys with evidence
    targeted: set[str]  # keys with failed sign-ins and no evidence
    rows: list[Targeted]  # the most attempted, RANKED at most
    total: int
    sources: list[str]


class GeoLookup(Protocol):
    def enrich(self, values: list[str]) -> dict[str, Any]: ...


def linked(ident: IdentityMap, name: str) -> bool:
    """An administrator linked this name, or linked another name to it."""
    raw = key_of(name, ident.domains)
    return raw in ident.aliases or ident.key(name) in set(ident.aliases.values())


def split(engine: QueryEngine, scope: QueryScope, ident: IdentityMap) -> Split:
    """People and targeted usernames by key (names merged per ADR-0018)."""
    res = engine.run(EVIDENCE_SQL, scope, timeout_s=TIMEOUT_S, name="people.evidence", page=True)
    groups: dict[str, Targeted] = {}
    people: set[str] = set()
    failed_keys: set[str] = set()
    for u, failed, ok, m365, sources, hosts in res.rows:
        name = str(u)
        key = ident.key(name)
        if int(ok) or int(m365) or linked(ident, name):
            people.add(key)
        if not int(failed):
            continue
        failed_keys.add(key)
        email = ident.org_email(name)
        t = groups.setdefault(key, Targeted(value=ident.display(key, email)))
        t.attempts += int(failed)
        t.sources = sorted(set(t.sources) | {str(s) for s in sources or []})
        t.hosts = sorted(set(t.hosts) | {str(h) for h in hosts or []})
        t.names = sorted(set(t.names) | {name})
    targeted = failed_keys - people
    rows = sorted((groups[k] for k in targeted), key=lambda t: (-t.attempts, t.value))
    top = rows[:RANKED]
    read = set(res.sources)
    names = [n for t in top for n in t.names]
    if names:
        with phase("people_attackers"):
            found = engine.run(
                ATTACKERS_SQL,
                scope,
                {"names": names},
                timeout_s=TIMEOUT_S,
                name="people.attackers",
                page=True,
            )
        read |= set(found.sources)
        by_name = {n: t for t in top for n in t.names}
        for u, ip, n in found.rows:
            hit = by_name.get(str(u))
            if hit is not None:
                hit.ips[str(ip)] = hit.ips.get(str(ip), 0) + int(n)
    return Split(people, targeted, top, len(rows), sorted(read))


def place(rows: list[Targeted], geo: GeoLookup | None) -> None:
    """Top attacking countries and networks per row, weighted by attempts, from the
    query-time GeoIP and ASN lookups (ADR-0023). Nothing when enrichment is off."""
    if geo is None:
        return
    found = geo.enrich(sorted({ip for t in rows for ip in t.ips}))
    if not found:
        return
    for t in rows:
        countries: Counter[str] = Counter()
        asns: Counter[str] = Counter()
        for ip, n in t.ips.items():
            info = found.get(ip)
            if info is None:
                continue
            if info.country:
                countries[str(info.country_name or info.country)] += n
            if info.asn is not None:
                label = f"AS{info.asn}" + (f" {info.org}" if info.org else "")
                asns[label] += n
        t.countries = [Place(k, v) for k, v in _top(countries)]
        t.asns = [Place(k, v) for k, v in _top(asns)]


def _top(c: Counter[str]) -> list[tuple[str, int]]:
    return sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_PLACES]
