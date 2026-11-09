"""Who used a device an AI Watch alert names (owner item 5, 2026-11-08; ADR-0048 C1, C2).

An alert from DNS, firewall, or proxy rows often names a machine and no person. The Claude
hooks plugin sends records that carry both the machine (`device_hostname`) and the person
(`actor_user_name`): its own host-to-user evidence. This reads those records for the alert's
hosts over the alert's range, on the caller's own view, so a viewer who cannot read the hooks
source gets no name from it (T70, D219). Names are joined into people by the Identities key
in the caller's scope (C2). One person is "attributed"; two or more are "possible" with the
count, and nothing picks one of them (C1). Hosts match exactly, ignoring case.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from app.ai.test_records import HOOKS
from app.engine.duckdb import QueryEngine, QueryScope
from app.search.identity import IdentityMap, is_person

TIMEOUT_S = 10.0
MAX_HOSTS = 200
MAX_NAMES = 3  # "Possible" lists up to 3 names and a count (ADR-0048 C1)

SQL = f"""
SELECT lower(trim(device_hostname)) AS h, actor_user_name AS u,
       min(coalesce(time, time_observed)) AS first_t, max(coalesce(time, time_observed)) AS last_t
FROM events
WHERE {HOOKS}
  AND lower(trim(device_hostname)) IN (SELECT unnest($hp_hosts))
  AND nullif(trim(actor_user_name), '') IS NOT NULL
  AND coalesce(time, time_observed) >= $hp_from AND coalesce(time, time_observed) < $hp_to
GROUP BY 1, 2, date_trunc('hour', coalesce(time, time_observed))
LIMIT 20000"""  # noqa: S608  # fixed text; hosts and times are bound parameters


@dataclass(slots=True)
class Seen:
    """One name on one host in one hour, so each alert's own range is applied exactly."""

    host: str
    name: str
    first: datetime
    last: datetime


@dataclass(slots=True)
class DevicePerson:
    device: str
    level: Literal["attributed", "possible"]
    people: list[str]
    count: int
    # hooks_identities: two names on the host were joined into one person by Identities
    how: Literal["hooks", "hooks_identities"]


@dataclass(slots=True)
class _Person:
    names: set[str] = field(default_factory=set)


def hooks_seen(
    engine: QueryEngine, scope: QueryScope, hosts: Iterable[str], start: datetime, end: datetime
) -> list[Seen]:
    """Every hooks name seen on these hosts in [start, end), from the caller's view."""
    wanted = sorted({h.strip().lower() for h in hosts if h.strip()})[:MAX_HOSTS]
    if not wanted or scope.sources == []:
        return []
    res = engine.run(
        SQL,
        QueryScope(scope.sources, start, end),
        {"hp_hosts": wanted, "hp_from": start, "hp_to": end},
        timeout_s=TIMEOUT_S,
        page=True,
        name="alerts.host_people",
    )
    return [Seen(str(h), str(u), _at(f), _at(t)) for h, u, f, t in res.rows if f is not None]


def _at(v: object) -> datetime:
    return v if isinstance(v, datetime) else datetime.fromisoformat(str(v))


def _shown(names: set[str]) -> str:
    """One name for a person: an email form when there is one, else the first in order."""
    mail = sorted(n for n in names if "@" in n)
    return (mail or sorted(names))[0]


def resolve(
    seen: list[Seen], ident: IdentityMap, device: str, start: datetime, end: datetime
) -> DevicePerson | None:
    """The person (or the possible people) on `device` between `start` and `end`."""
    host = device.strip().lower()
    people: dict[str, _Person] = {}
    for s in seen:
        if s.host != host or s.last < start or s.first >= end:
            continue
        key = ident.key(s.name)
        if not is_person(key):
            continue
        people.setdefault(key, _Person()).names.add(s.name.strip())
    if not people:
        return None
    joined = any(len({n.lower() for n in p.names}) > 1 for p in people.values())
    shown = sorted(_shown(p.names) for p in people.values())
    return DevicePerson(
        device=device,
        level="attributed" if len(shown) == 1 else "possible",
        people=shown[:MAX_NAMES],
        count=len(shown),
        how="hooks_identities" if joined else "hooks",
    )


@dataclass(slots=True)
class Asked:
    """One alert's hosts and range."""

    key: str
    hosts: list[str]
    start: datetime
    end: datetime


def for_alerts(
    engine: QueryEngine,
    sources: list[str] | None,
    ident: IdentityMap,
    whole_map: bool,
    asked: list[Asked],
) -> dict[str, list[DevicePerson]]:
    """The people on each alert's hosts, in one query over all of them. `sources` is the
    caller's readable hooks sources (None: every source, an administrator's view);
    `whole_map` is True only for an administrator (D223). Anyone else gets only the part of
    Identities the hooks names they read show (`seen_in`, T70, D219)."""
    asked = [a for a in asked if a.hosts]
    if not asked or sources == []:
        return {}
    start = min(a.start for a in asked)
    end = max(a.end for a in asked)
    seen = hooks_seen(engine, QueryScope(sources), (h for a in asked for h in a.hosts), start, end)
    if not seen:
        return {}
    scoped = ident if whole_map else ident.seen_in(s.name for s in seen)
    out: dict[str, list[DevicePerson]] = {}
    for a in asked:
        found = [resolve(seen, scoped, h, a.start, a.end) for h in a.hosts]
        kept = [f for f in found if f is not None]
        if kept:
            out[a.key] = kept
    return out
