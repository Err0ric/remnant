"""The top of an entity's page (product pass step 2, DESIGN 6.2): what this address, person,
or machine did, in numbers, before any graph.

All of it is SQL over the caller's `events` view through the guard, like the lane graph:
counts, sign-in outcomes, who and what it touched, first and last seen, and the activities
grouped by outcome with a real example line each (not the number-masked pattern).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Literal

from app.core.timing import in_context
from app.engine.duckdb import QueryEngine, QueryScope
from app.engine.signin_classes import ACCESS_OUTCOME, REAL_FAILURE
from app.search.entities import (
    CLASS_NAMES,
    RECORD_LIKE,
    SIGNIN,
    WHERE,
    failed_class,
    quote,
    search_sql,
    user_filter_sql,
    user_where,
)
from app.search.identity import IdentityMap

TIMEOUT_S = 20
Kind = Literal["user", "ip", "host"]

# Sign-ins by outcome for the page's filter (D158): real failures, then each class of a
# Microsoft 365 sign-in that is not counted, then every sign-in.
SLICES: tuple[tuple[str, str, str], ...] = (
    ("failed", "Real failures", f"{SIGNIN} AND {REAL_FAILURE}"),
    ("interrupted", "Interrupted", f"{SIGNIN} AND {failed_class('interrupted')}"),
    ("expired", "Expired", f"{SIGNIN} AND {failed_class('expired')}"),
    ("other", "Other", f"{SIGNIN} AND {failed_class('other')}"),
    ("all", "All", SIGNIN),
)
SLICE_COUNTS = ",\n       ".join(f"count(*) FILTER (WHERE {cond})" for _, _, cond in SLICES)
# Failed sign-ins are real failures only: a Microsoft 365 sign-in interrupted, expired, or
# with an unknown code is "not counted" (D158).
TOTALS_SQL = f"""
SELECT count(*),
       count(*) FILTER (WHERE {SIGNIN}),
       count(*) FILTER (WHERE {SIGNIN} AND status_id = 1),
       count(*) FILTER (WHERE {SIGNIN} AND {REAL_FAILURE}),
       count(DISTINCT nullif(trim(actor_user_name), '')) FILTER (WHERE {SIGNIN}),
       count(DISTINCT coalesce(nullif(dst_endpoint_hostname, ''), nullif(device_hostname, ''))),
       count(DISTINCT {{addr}}) FILTER (WHERE NOT {{service}}),
       min(coalesce(time, time_observed)),
       max(coalesce(time, time_observed)),
       list(DISTINCT source_id),
       count(DISTINCT {{addr}}) FILTER (WHERE {{service}}),
       {SLICE_COUNTS}
FROM {{rows}}
WHERE {{where}}"""  # noqa: S608  # fixed SQL text

ADDR = "coalesce(nullif(src_endpoint_ip, ''), nullif(dst_endpoint_ip, ''))"
# Microsoft 365's own addresses (Exchange Online, SharePoint, the Graph back end) appear on
# server-side records such as mail access by Exchange; they are not where the person was
# (owner, 2026-10-31: "177 seen addresses" in 7 days). Microsoft's AS 8075 when the ASN
# file is installed, else its published Microsoft 365 ranges.
MS_PREFIXES = (
    "2603:10", "2a01:111:", "40.92.", "40.93.", "40.94.", "40.95.", "40.107.", "52.96.",
    "52.97.", "52.98.", "52.99.", "52.100.", "52.101.", "52.102.", "52.103.", "104.47.",
    "13.107.",
)  # fmt: skip
SERVICE = (
    f"(coalesce(ip_asn({ADDR}) = 8075, false) OR "
    + " OR ".join(f"starts_with(lower({ADDR}), '{p}')" for p in MS_PREFIXES)
    + ")"
)

# One row per outcome, kind of activity, user, and target, with a real line as the example.
# Sign-ins and firewall traffic by the access card's own outcome; other events are "other".
OUTCOME = f"CASE WHEN class_uid IN (3002, 4001) THEN {ACCESS_OUTCOME} ELSE 'other' END"
TARGET = "coalesce(nullif(dst_endpoint_hostname, ''), nullif(device_hostname, ''))"
WHO = "nullif(trim(actor_user_name), '')"
ACTIVITIES_SQL = """
SELECT {outcome} AS outcome, coalesce(class_uid, 0) AS class_uid,
       {who} AS who, {target} AS target,
       count(*) AS n, min(coalesce(time, time_observed)) AS first,
       max(coalesce(time, time_observed)) AS last, {example} AS example
FROM {rows}
WHERE {where}
GROUP BY 1, 2, 3, 4
ORDER BY CASE outcome WHEN 'succeeded' THEN 0 WHEN 'failed' THEN 1 ELSE 2 END, n DESC,
         last DESC, who, target
LIMIT 20"""

# The example line: one that names the entity when there is one (a real value, not the
# Windows text "An account failed to log on."), else the newest. Deterministic.
EXAMPLE_NAMED = (
    "arg_max(message, (CASE WHEN contains(coalesce(message, ''), $v) THEN 1 ELSE 0 END)"
    " * 1e13 + epoch_ms(coalesce(time, time_observed)))"
)
EXAMPLE_NEWEST = "arg_max(message, coalesce(time, time_observed))"

# An example line that is a whole delimited record (a vendor CSV payload standing in for a
# message, as Palo Alto USERID lines stored before #425 have) reads instead as a summary of
# its parsed fields: who, the address, and how a mapping was learned. Run only when needed.
RECORD_FIELDS_SQL = """
SELECT message, min(template_id), min(nullif(trim(actor_user_name), '')),
       min(nullif(src_endpoint_ip, '')),
       min(nullif(json_extract_string(unmapped, '$.data_source'), ''))
FROM {rows}
WHERE {where} AND message IN (SELECT unnest($records)) AND {record_like}
GROUP BY 1"""


def either_rows(kind: str) -> str:
    """The events of the address or host `$v` (`WHERE[kind]`), as two arms, each row once:
    as one OR the test is not pushed into the scan, so the record was read for every row in
    range (owner, 2026-11-17: 1.5 s for 56 rows of an address on the 30-day bench lake)."""
    a, b = {"ip": ("src_endpoint_ip", "dst_endpoint_ip"),
            "host": ("device_hostname", "src_endpoint_hostname")}[kind]  # fmt: skip
    return (
        f"(SELECT * FROM events WHERE {a} = $v UNION ALL"  # noqa: S608  # fixed columns; $v is bound
        f" SELECT * FROM events WHERE {b} = $v AND {a} IS DISTINCT FROM $v) AS e"
    )


def is_record(message: str) -> bool:
    """The Python side of `RECORD_LIKE` for a non-empty message."""
    return len(message) - len(message.replace(",", "").replace("|", "")) >= 8


def record_summary(name: str, who: Any, address: Any, learned: Any) -> str:
    """'Palo Alto Networks User-ID: alice at 192.0.2.20, learned from globalprotect'."""
    text = " at ".join(str(v) for v in (who, address) if v)
    if learned:
        text = f"{text}, learned from {learned}" if text else f"learned from {learned}"
    if name:
        text = f"{name}: {text}" if text else name
    return text


# Users are counted by their sign-ins (SIGNIN), so "Users tried" and its numbers agree
# with the Sign-ins number; hosts by every event that names them.
TARGETS_SQL = """
SELECT 'host' AS kind, {target} AS value, count(*) AS n FROM {rows}
WHERE {where} AND {target} IS NOT NULL GROUP BY 2
UNION ALL
SELECT 'user', nullif(trim(actor_user_name), ''), count(*) FROM {rows}
WHERE {where} AND {signin} AND nullif(trim(actor_user_name), '') IS NOT NULL GROUP BY 2
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
class SignInSlice:
    key: str  # failed, interrupted, expired, other, all
    label: str
    count: int
    search_sql: str


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
    addresses: int  # where the person or host was: client addresses
    first_seen: str | None
    last_seen: str | None
    sources: list[str]
    activities: list[Activity] = field(default_factory=list)
    targets: list[Target] = field(default_factory=list)
    search_sql: str = ""
    read: list[str] = field(default_factory=list)
    service_addresses: int = 0  # Microsoft 365's own, on server-side records
    # This entity's sign-ins by outcome, each opening its rows in Search (D158).
    sign_in_slices: list[SignInSlice] = field(default_factory=list)


def drill_sql(where: str) -> str:
    """A sign-in list for Search: who, the app, the outcome and its code, interactive or not,
    the reason, and the address, newest first."""
    from app.search.m365 import SIGNIN_COLUMNS

    return (
        f"SELECT {SIGNIN_COLUMNS}, source_id\nFROM events\nWHERE {where}\n"
        "ORDER BY coalesce(time, time_observed) DESC"
    )


def _iso(v: Any) -> str | None:
    return v.isoformat() if hasattr(v, "isoformat") else (str(v) if v is not None else None)


def entity_summary(
    engine: QueryEngine,
    scope: QueryScope,
    kind: Kind,
    value: str,
    ident: IdentityMap | None = None,
    template_names: dict[str, str] | None = None,
) -> Summary:
    """`template_names` (id to name) names a summary that stands in for a record line."""
    ident = ident or IdentityMap()
    params: dict[str, object]
    if kind == "user":
        keys = ident.keys_for(value)
        where = user_where(keys)
        params = {"keys": keys, **ident.params()}
        literal = user_filter_sql(ident, keys)
        rows = "events"
    else:
        rows, where = either_rows(kind), "true"
        params = {"v": value}
        literal = WHERE[kind].replace("$v", quote(value))
    totals_sql = TOTALS_SQL.format(rows=rows, where=where, addr=ADDR, service=SERVICE)
    acts_sql = ACTIVITIES_SQL.format(
        rows=rows,
        where=where,
        outcome=OUTCOME,
        who=WHO,
        target=TARGET,
        example=EXAMPLE_NEWEST if kind == "user" else EXAMPLE_NAMED,
    )
    # The three run together (owner re-time, 2026-11-01: they ran one after another).
    with ThreadPoolExecutor(max_workers=3) as pool:
        runs = [
            pool.submit(
                in_context(engine.run),
                sql,
                scope,
                params,
                timeout_s=TIMEOUT_S,
                name=name,
                page=True,
            )
            for name, sql in (
                ("summary.totals", totals_sql),
                ("summary.activities", acts_sql),
                (
                    "summary.targets",
                    TARGETS_SQL.format(rows=rows, where=where, target=TARGET, signin=SIGNIN),
                ),
            )
        ]
        totals, acts, tgts = (r.result() for r in runs)
    t: list[Any] = list(totals.rows[0]) if totals.rows else [0] * 9 + [[], 0] + [0] * len(SLICES)
    activities = []
    for outcome, class_uid, who, target, n, first, last, example in acts.rows:
        # Exactly the row's events: its class and the same outcome rule that grouped it.
        cond = [literal, f"coalesce(class_uid, 0) = {int(class_uid or 0)}"]
        cond.append(f"{OUTCOME} = {quote(str(outcome))}")
        # No user or no target is a group of its own: the link opens only those rows.
        cond.append(f"trim(actor_user_name) = {quote(str(who))}" if who else f"{WHO} IS NULL")
        cond.append(f"{TARGET} = {quote(str(target))}" if target else f"{TARGET} IS NULL")
        activities.append(
            Activity(
                outcome=str(outcome).replace(" ", "_"),  # the API's spelling: not_counted
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
    records = sorted({a.example for a in activities if a.example and is_record(a.example)})
    if records:
        found = engine.run(
            RECORD_FIELDS_SQL.format(rows=rows, where=where, record_like=RECORD_LIKE),
            scope,
            {**params, "records": records},
            timeout_s=TIMEOUT_S,
            name="summary.records",
            page=True,
        )
        plain = {
            str(msg): record_summary((template_names or {}).get(str(tpl or ""), ""), w, a, ls)
            for msg, tpl, w, a, ls in found.rows
        }
        for act in activities:
            act.example = plain.get(act.example, act.example)
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
        service_addresses=int(t[10] or 0),
        activities=activities,
        targets=targets,
        search_sql=search_sql(literal),
        sign_in_slices=[
            SignInSlice(
                key,
                label,
                int(t[11 + i] or 0),
                drill_sql(f"{literal} AND {cond}"),
            )
            for i, (key, label, cond) in enumerate(SLICES)
        ],
        read=sorted(set(totals.sources) | set(acts.sources) | set(tgts.sources)),
    )
