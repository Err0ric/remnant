"""The top of an entity's page (product pass step 2, DESIGN 6.2): what this address, person,
or machine did, in numbers, before any graph.

All of it is SQL over the caller's `events` view through the guard, like the lane graph:
counts, sign-in outcomes, who and what it touched, first and last seen, and the activities
grouped by outcome with a real example line each (not the number-masked pattern).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.engine.duckdb import QueryEngine, QueryScope
from app.search.entities import CLASS_NAMES, WHERE, quote, search_sql, user_filter_sql
from app.search.identity import IdentityMap, key_sql

TIMEOUT_S = 20
Kind = Literal["user", "ip", "host"]

TOTALS_SQL = """
SELECT count(*),
       count(*) FILTER (WHERE class_uid = 3002),
       count(*) FILTER (WHERE class_uid = 3002 AND status_id = 1),
       count(*) FILTER (WHERE class_uid = 3002 AND status_id = 2),
       count(DISTINCT nullif(trim(actor_user_name), '')),
       count(DISTINCT coalesce(nullif(dst_endpoint_hostname, ''), nullif(device_hostname, ''))),
       count(DISTINCT coalesce(nullif(src_endpoint_ip, ''), nullif(dst_endpoint_ip, ''))),
       min(coalesce(time, time_observed)),
       max(coalesce(time, time_observed)),
       list(DISTINCT source_id)
FROM events
WHERE {where}"""

# One row per outcome, kind of activity, user, and target, with a real line as the example.
OUTCOME = (
    "CASE WHEN class_uid = 3002 AND status_id = 1 THEN 'succeeded'"
    " WHEN class_uid = 3002 AND status_id = 2 THEN 'failed' ELSE 'other' END"
)
TARGET = "coalesce(nullif(dst_endpoint_hostname, ''), nullif(device_hostname, ''))"
ACTIVITIES_SQL = """
SELECT {outcome} AS outcome, coalesce(class_uid, 0) AS class_uid,
       nullif(trim(actor_user_name), '') AS who, {target} AS target,
       count(*) AS n, min(coalesce(time, time_observed)) AS first,
       max(coalesce(time, time_observed)) AS last, {example} AS example
FROM events
WHERE {where}
GROUP BY 1, 2, 3, 4
ORDER BY CASE outcome WHEN 'succeeded' THEN 0 WHEN 'failed' THEN 1 ELSE 2 END, n DESC
LIMIT 20"""

# The example line: one that names the entity when there is one (a real value, not the
# Windows text "An account failed to log on."), else the newest. Deterministic.
EXAMPLE_NAMED = (
    "arg_max(message, (CASE WHEN contains(coalesce(message, ''), $v) THEN 1 ELSE 0 END)"
    " * 1e13 + epoch_ms(coalesce(time, time_observed)))"
)
EXAMPLE_NEWEST = "arg_max(message, coalesce(time, time_observed))"

TARGETS_SQL = """
SELECT 'host' AS kind, {target} AS value, count(*) AS n FROM events
WHERE {where} AND {target} IS NOT NULL GROUP BY 2
UNION ALL
SELECT 'user', nullif(trim(actor_user_name), ''), count(*) FROM events
WHERE {where} AND nullif(trim(actor_user_name), '') IS NOT NULL GROUP BY 2
ORDER BY n DESC
LIMIT 40"""


@dataclass(slots=True)
class Activity:
    outcome: str  # succeeded | failed | other
    kind: str  # class name, "Authentication"
    user: str | None
    target: str | None
    events: int
    first: str | None
    last: str | None
    example: str  # one real line, values intact
    search_sql: str


@dataclass(slots=True)
class Target:
    kind: Literal["host", "user"]
    value: str
    events: int


@dataclass(slots=True)
class Summary:
    kind: Kind
    value: str
    events: int
    sign_ins: int
    succeeded: int
    failed: int
    users: int
    hosts: int
    addresses: int
    first_seen: str | None
    last_seen: str | None
    sources: list[str]
    activities: list[Activity] = field(default_factory=list)
    targets: list[Target] = field(default_factory=list)
    search_sql: str = ""
    read: list[str] = field(default_factory=list)


def _iso(v: Any) -> str | None:
    return v.isoformat() if hasattr(v, "isoformat") else (str(v) if v is not None else None)


def entity_summary(
    engine: QueryEngine,
    scope: QueryScope,
    kind: Kind,
    value: str,
    ident: IdentityMap | None = None,
) -> Summary:
    ident = ident or IdentityMap()
    params: dict[str, object]
    if kind == "user":
        keys = ident.keys_for(value)
        where = f"list_contains($keys, {key_sql('actor_user_name')})"
        params = {"keys": keys, **ident.params()}
        literal = user_filter_sql(ident, keys)
    else:
        where = WHERE[kind]
        params = {"v": value}
        literal = WHERE[kind].replace("$v", quote(value))
    totals = engine.run(TOTALS_SQL.format(where=where), scope, params, timeout_s=TIMEOUT_S)
    t: list[Any] = list(totals.rows[0]) if totals.rows else [0] * 9 + [[]]
    acts = engine.run(
        ACTIVITIES_SQL.format(
            where=where,
            outcome=OUTCOME,
            target=TARGET,
            example=EXAMPLE_NEWEST if kind == "user" else EXAMPLE_NAMED,
        ),
        scope,
        params,
        timeout_s=TIMEOUT_S,
    )
    tgts = engine.run(
        TARGETS_SQL.format(where=where, target=TARGET), scope, params, timeout_s=TIMEOUT_S
    )
    activities = []
    for outcome, class_uid, who, target, n, first, last, example in acts.rows:
        cond = [literal]
        if outcome == "succeeded":
            cond.append("class_uid = 3002 AND status_id = 1")
        elif outcome == "failed":
            cond.append("class_uid = 3002 AND status_id = 2")
        else:
            cond.append(f"coalesce(class_uid, 0) = {int(class_uid or 0)}")
        if who:
            cond.append(f"trim(actor_user_name) = {quote(str(who))}")
        if target:
            cond.append(f"{TARGET} = {quote(str(target))}")
        activities.append(
            Activity(
                outcome=str(outcome),
                kind=CLASS_NAMES.get(int(class_uid or 0), f"Class {class_uid}"),
                user=str(who) if who else None,
                target=str(target) if target else None,
                events=int(n),
                first=_iso(first),
                last=_iso(last),
                example=str(example or ""),
                search_sql=search_sql(" AND ".join(cond)),
            )
        )
    # The entity itself is not its own target (a host's own name, a user's own name).
    own = {value.lower()}
    targets = [
        Target(kind=str(k), value=str(v), events=int(n))  # type: ignore[arg-type]  # 'host' or 'user' from the SQL
        for k, v, n in tgts.rows
        if v and str(v).lower() not in own
    ][:20]
    return Summary(
        kind=kind,
        value=value,
        events=int(t[0] or 0),
        sign_ins=int(t[1] or 0),
        succeeded=int(t[2] or 0),
        failed=int(t[3] or 0),
        users=int(t[4] or 0),
        hosts=int(t[5] or 0),
        addresses=int(t[6] or 0),
        first_seen=_iso(t[7]),
        last_seen=_iso(t[8]),
        sources=sorted(str(s) for s in (t[9] or [])),
        activities=activities,
        targets=targets,
        search_sql=search_sql(literal),
        read=sorted(set(totals.sources) | set(acts.sources) | set(tgts.sources)),
    )
