"""The hosts, devices, and addresses one person used (owner, 2026-11-03; D197): the
person page's "Hosts and devices" section.

One row per device (`device_hostname` on the person's own records: the machine a sign-in,
login, or agent record came from or landed on) and per source address, with events,
failed sign-ins, and first and last seen. The person is matched under every form of the
name, as on the timeline (`_mine`). Deterministic SQL on the caller's own view.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.engine.duckdb import QueryEngine, QueryScope
from app.search.identity import IdentityMap
from app.search.timeline import _mine

TIMEOUT_S = 20.0
MAX_ROWS = 100

SQL = """
WITH p AS (
  SELECT device_hostname AS h, src_endpoint_ip AS ip, coalesce(time, time_observed) AS t,
         class_uid = 3002 AND status_id = 2 AS fail, source_id
  FROM events WHERE {mine}
)
SELECT 'host' AS kind, h AS value, count(*) AS events, count(*) FILTER (WHERE fail),
       min(t), max(t), list(DISTINCT source_id ORDER BY source_id)
FROM p WHERE nullif(h, '') IS NOT NULL GROUP BY h
UNION ALL
SELECT 'ip', ip, count(*), count(*) FILTER (WHERE fail), min(t), max(t),
       list(DISTINCT source_id ORDER BY source_id)
FROM p WHERE nullif(ip, '') IS NOT NULL GROUP BY ip
ORDER BY 1, 3 DESC, 2
"""  # fixed SQL text; the person condition holds literals only (`_mine`)


@dataclass(slots=True)
class Used:
    kind: str  # host or ip
    value: str
    events: int
    failed: int
    first_seen: str | None
    last_seen: str | None
    sources: list[str]


@dataclass(slots=True)
class PersonHosts:
    person: str
    hosts: list[Used] = field(default_factory=list)
    addresses: list[Used] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


def _iso(v: Any) -> str | None:
    return v.isoformat() if isinstance(v, datetime) else (str(v) if v else None)


def person_hosts(
    engine: QueryEngine, scope: QueryScope, ident: IdentityMap, person: str
) -> PersonHosts:
    keys = ident.keys_for(person)
    res = engine.run(
        SQL.format(mine=_mine(ident, keys)), scope, timeout_s=TIMEOUT_S, page=True
    )  # the condition is literals built by _mine
    out = PersonHosts(person, sources=list(res.sources))
    for kind, value, events, failed, first, last, sources in res.rows:
        u = Used(str(kind), str(value), int(events), int(failed), _iso(first), _iso(last),
                 [str(s) for s in sources or []])  # fmt: skip
        target = out.hosts if kind == "host" else out.addresses
        if len(target) < MAX_ROWS:
            target.append(u)
    return out
