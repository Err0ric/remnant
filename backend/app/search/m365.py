"""The Microsoft 365 area (ADR-0038 section 5): Overview numbers and the tabs' lists for one
page window, on the caller's own view.

Every count uses the one-operation key (D122) where Graph and the Management Activity API
report the same operation; every number carries its Search query (ADR-0039). Sign-ins
split three ways (owner edit 2): succeeded, interrupted (Entra asked for something more,
such as MFA, and the sign-in may still complete), and failed. No model is called.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.ai import consents
from app.engine.duckdb import QueryEngine, QueryScope
from app.enrich.networks import Places
from app.search import drill
from app.search.dashboard import (
    CHANGES_SQL,
    FAILED,
    FIRST_EVENT_SQL,
    INTERRUPTED,
    History,
    Kpi,
    Row,
    Window,
    _history,
    _Run,
    _utc,
    bounds,
    changes_drill,
    outside_where,
    trend_points,
)

TOP = 5
TS = drill.TS
SIGNIN = "template_id = 'm365_signin'"
RISKY = f"{SIGNIN} AND severity_id >= 3"
_OP = "lower(rtrim(trim(message), '.'))"
_ACTIVITY = "template_id = 'm365_management_activity'"

# The counts row: Exchange, DLP, SharePoint, and Copilot operations come only from the
# Management Activity API, so each record is one operation.
COUNTS: list[tuple[str, str, str]] = [
    (
        "mail_rules",
        "Mail rules",
        f"{_OP} IN ('new-inboxrule', 'set-inboxrule', 'updateinboxrules')",
    ),
    ("forwarding", "Forwarding", f"{_OP} = 'set-mailbox' AND raw ILIKE '%Forwarding%'"),
    ("dlp", "DLP matches", f"{_OP} = 'dlprulematch'"),
    ("downloads", "File downloads", f"{_OP} IN ('filedownloaded', 'filesyncdownloadedfull')"),
    (
        "external_shares",
        "External shares",
        f"{_OP} IN ('anonymouslinkcreated', 'sharinginvitationcreated')",
    ),
    ("copilot", "Copilot interactions", f"{_OP} = 'copilotinteraction'"),
]

SIGNIN_SQL = f"""
SELECT count(*) FILTER (WHERE {TS} >= $start),
       count(*) FILTER (WHERE {TS} < $start),
       count(*) FILTER (WHERE {TS} >= $start AND {FAILED}),
       count(*) FILTER (WHERE {TS} < $start AND {FAILED}),
       count(*) FILTER (WHERE {TS} >= $start AND severity_id >= 3),
       count(*) FILTER (WHERE {TS} < $start AND severity_id >= 3)
FROM events WHERE {SIGNIN}"""  # noqa: S608  # fixed SQL text

OUTCOME_SQL = f"""
SELECT date_trunc($unit, timezone('UTC', {TS})) AS b,
       count(*) FILTER (WHERE status_id = 1),
       count(*) FILTER (WHERE {INTERRUPTED}),
       count(*) FILTER (WHERE {FAILED})
FROM events WHERE {SIGNIN} AND {TS} >= $start
GROUP BY 1"""  # noqa: S608  # fixed SQL text

REASONS_SQL = f"""
SELECT coalesce(nullif(status_detail, ''), 'No reason given') AS reason, count(*) AS n
FROM events WHERE {SIGNIN} AND {FAILED} AND {TS} >= $start
GROUP BY 1 ORDER BY n DESC, reason LIMIT {TOP}"""  # noqa: S608  # fixed SQL text

APPS_SQL = f"""
SELECT coalesce(nullif(resource_name, ''), nullif(message, ''), 'Unknown app') AS app,
       count(*) AS n
FROM events WHERE {SIGNIN} AND {TS} >= $start
GROUP BY 1 ORDER BY n DESC, app LIMIT {TOP}"""  # noqa: S608  # fixed SQL text

OUTSIDE_SQL = f"""
SELECT ip_country(src_endpoint_ip) AS country, count(*) AS n,
       count(DISTINCT actor_user_name) AS people
FROM events
WHERE {SIGNIN} AND status_id = 1 AND {TS} >= $start
  AND NOT list_contains($approved, ip_country(src_endpoint_ip))
GROUP BY 1 ORDER BY n DESC, country LIMIT {TOP}"""  # noqa: S608  # fixed SQL text

COUNTS_SQL = (
    "SELECT "  # fixed SQL text
    + ",\n       ".join(
        f"count(*) FILTER (WHERE {TS} >= $start AND {cond}),"
        f" count(*) FILTER (WHERE {TS} < $start AND {cond})"
        for _, _, cond in COUNTS
    )
    + f"\nFROM events WHERE {_ACTIVITY}"
)

SIGNIN_COLUMNS = (
    "time, actor_user_name, coalesce(nullif(resource_name, ''), message) AS app,\n"
    f"       CASE WHEN status_id = 1 THEN 'succeeded' WHEN {INTERRUPTED} THEN 'interrupted'"
    " WHEN status_id = 2 THEN 'failed' END AS outcome,\n"
    "       status_detail AS reason, severity_id, src_endpoint_ip,"
    " ip_country(src_endpoint_ip) AS country, device_hostname, event_id"
)
ACTIVITY_COLUMNS = (
    "time, actor_user_name, message AS operation, status_id, src_endpoint_ip, event_id"
)
_MAIL = " OR ".join(f"({c})" for k, _, c in COUNTS if k in ("mail_rules", "forwarding", "dlp"))

# Admin: directory changes, one row per operation (D122), sign-ins and consents left out.
ADMIN_LIST = (
    "WITH r AS (\n"  # noqa: S608  # fixed SQL text
    f"  SELECT {TS} AS ts, {_OP} AS op, actor_user_name AS who, resource_name AS target,"
    " status_id, event_id,\n"
    "         coalesce(metadata_correlation_uid,\n"
    "                  coalesce(lower(actor_user_name), '') || '|'\n"
    f"                    || strftime({TS}, '%Y-%m-%d %H:%M')) AS k\n"
    "  FROM events\n"
    "  WHERE template_id = 'm365_directory_audit'\n"
    "     OR (template_id = 'm365_management_activity'\n"
    "         AND json_extract_string(raw, '$.Workload') = 'AzureActiveDirectory')\n"
    ")\n"
    "SELECT min(ts) AS time, any_value(who) AS person, op AS operation,"
    " any_value(target) AS target, max(status_id) AS status_id,"
    " list(event_id) AS event_ids\n"
    "FROM r\n"
    "WHERE op NOT IN ('userloggedin', 'userloginfailed')\n"
    "  AND op NOT LIKE 'consent to application%'\n"
    "GROUP BY k, op\n"
    "HAVING min(ts) >= TIMESTAMPTZ '{from}' AND min(ts) < TIMESTAMPTZ '{to}'\n"
    "ORDER BY time DESC"
)
REGISTRATIONS = (
    "template_id IN ('m365_directory_audit', 'm365_management_activity')\n"
    f"  AND ({_OP} IN ('add application', 'update application', 'add service principal')"
    f" OR {_OP} LIKE 'update application%certificates and secrets management')"
)


@dataclass(slots=True)
class Count:
    key: str
    label: str
    kpi: Kpi


@dataclass(slots=True)
class Outcome:
    points: list[datetime]
    succeeded: list[int]
    interrupted: list[int]
    failed: list[int]
    drill_succeeded: str
    drill_interrupted: str
    drill_failed: str


@dataclass(slots=True)
class M365:
    window: str
    start: datetime
    end: datetime
    before: datetime
    has_source: bool
    approved_set: bool
    history: History = field(default_factory=lambda: History(True))
    sign_ins: Kpi | None = None
    failed: Kpi | None = None
    outside: Kpi | None = None  # None: approved countries not set
    risky: Kpi | None = None
    consents: Kpi | None = None  # extra: blocked attempts
    admin_changes: Kpi | None = None
    counts: list[Count] = field(default_factory=list)
    outcome: Outcome | None = None
    reasons: list[Row] = field(default_factory=list)
    outside_top: list[Row] = field(default_factory=list)
    apps: list[Row] = field(default_factory=list)
    lists: dict[str, str] = field(default_factory=dict)
    read: list[str] = field(default_factory=list)


def lists(approved: tuple[str, ...]) -> dict[str, str]:
    """The tabs' event lists, as Search query templates."""
    return {
        "sign_ins": drill.events(SIGNIN, SIGNIN_COLUMNS),
        "mail": drill.events(f"{_ACTIVITY} AND ({_MAIL})", ACTIVITY_COLUMNS),
        "consents": consents_list(),
        "registrations": drill.events(REGISTRATIONS, ACTIVITY_COLUMNS),
        "admin": ADMIN_LIST,
    }


def consents_list() -> str:
    """Consents granted and blocked, one row per consent (D122)."""
    return (
        f"WITH {consents.CONSENTS_CTE.strip()}\n"  # fixed SQL text
        "SELECT ts AS time, who AS person, app, app_id,"
        " CASE WHEN status_id = 2 THEN 'blocked' ELSE 'granted' END AS result,"
        " privileges AS permissions, reason, event_id, event_ids\n"
        "FROM consents\n"
        "WHERE ts >= TIMESTAMPTZ '{from}' AND ts < TIMESTAMPTZ '{to}'\n"
        "ORDER BY ts DESC"
    )


def overview(
    engine: QueryEngine,
    allowed: list[str] | None,
    sources: list[tuple[str, str, str | None]],
    places: Places,
    window: Window,
    now: datetime,
) -> M365:
    start, before, _ = bounds(window, now)
    mine = [s for s in sources if allowed is None or s[0] in set(allowed)]
    m365 = [sid for sid, kind, tpl in mine if kind == "m365" or (tpl or "").startswith("m365_")]
    approved = tuple(sorted(c.upper() for c in places.approved_countries))
    out = M365(
        window=window,
        start=start,
        end=now,
        before=before,
        has_source=bool(m365),
        approved_set=bool(approved),
        lists=lists(approved),
    )
    if not m365:
        return out
    unit, points = trend_points(window, now)
    run = _Run(
        engine,
        QueryScope(sources=None, start=before, end=now),
        {"start": start, "unit": unit, "approved": list(approved)},
    )
    first = {str(s): t for s, at in run(FIRST_EVENT_SQL, m365) if (t := _utc(at)) is not None}
    out.history = _history(first, m365, start, before)

    total, total_b, failed, failed_b, risky, risky_b = (run(SIGNIN_SQL, m365) or [[0] * 6])[0]
    out.sign_ins = Kpi(int(total), int(total_b), drill=drill.events(SIGNIN, SIGNIN_COLUMNS))
    out.failed = Kpi(
        int(failed), int(failed_b), drill=drill.events(f"{SIGNIN} AND {FAILED}", SIGNIN_COLUMNS)
    )
    out.risky = Kpi(int(risky), int(risky_b), drill=drill.events(RISKY, SIGNIN_COLUMNS))
    if approved:
        where = outside_where(["m365_signin"], approved)
        rows = run(OUTSIDE_SQL, m365)
        now_n = sum(int(r[1]) for r in rows)
        out.outside = Kpi(now_n, None, drill=drill.events(where, SIGNIN_COLUMNS))
        out.outside_top = [
            Row(
                str(c),
                int(n),
                kind="country",
                detail=str(p),
                drill=drill.events(
                    f"{where}\n  AND ip_country(src_endpoint_ip) = {drill.lit(str(c))}",
                    SIGNIN_COLUMNS,
                ),
            )
            for c, n, p in rows
        ]
    granted, granted_b, blocked = (run(consents.COUNTS_SQL, m365) or [[0, 0, 0]])[0][:3]
    out.consents = Kpi(
        int(granted),
        int(granted_b),
        int(blocked),
        drill=consents.drill_sql(blocked=False),
        extra_drill=consents.drill_sql(blocked=True),
    )
    changes = {str(k): (int(a), int(b)) for k, a, b in run(CHANGES_SQL, m365)}
    role, ca = changes.get("role", (0, 0)), changes.get("ca", (0, 0))
    out.admin_changes = Kpi(role[0] + ca[0], role[1] + ca[1], drill=_admin_drill())
    c = (run(COUNTS_SQL, m365) or [[0] * (2 * len(COUNTS))])[0]
    out.counts = [
        Count(
            key,
            label,
            Kpi(
                int(c[2 * i]),
                int(c[2 * i + 1]),
                drill=drill.events(f"{_ACTIVITY} AND {cond}", ACTIVITY_COLUMNS),
            ),
        )
        for i, (key, label, cond) in enumerate(COUNTS)
    ]
    at = {p: i for i, p in enumerate(points)}
    ok, inter, fail = ([0] * len(points) for _ in range(3))
    for b, s, i_, f in run(OUTCOME_SQL, m365):
        t = _utc(b)
        if t is not None and t in at:
            ok[at[t]], inter[at[t]], fail[at[t]] = int(s), int(i_), int(f)
    out.outcome = Outcome(
        points,
        ok,
        inter,
        fail,
        drill.events(f"{SIGNIN} AND status_id = 1", SIGNIN_COLUMNS),
        drill.events(f"{SIGNIN} AND {INTERRUPTED}", SIGNIN_COLUMNS),
        drill.events(f"{SIGNIN} AND {FAILED}", SIGNIN_COLUMNS),
    )
    out.reasons = [
        Row(
            str(r),
            int(n),
            kind="reason",
            drill=drill.events(
                f"{SIGNIN} AND {FAILED}\n"
                "  AND coalesce(nullif(status_detail, ''), 'No reason given')"
                f" = {drill.lit(str(r))}",
                SIGNIN_COLUMNS,
            ),
        )
        for r, n in run(REASONS_SQL, m365)
    ]
    out.apps = [
        Row(
            str(a),
            int(n),
            kind="app",
            drill=drill.events(
                f"{SIGNIN}\n  AND coalesce(nullif(resource_name, ''), nullif(message, ''),"
                f" 'Unknown app') = {drill.lit(str(a))}",
                SIGNIN_COLUMNS,
            ),
        )
        for a, n in run(APPS_SQL, m365)
    ]
    out.read = sorted(run.read)
    return out


def _admin_drill() -> str:
    """Role grants and Conditional Access edits, one row per change (D122)."""
    return changes_drill("role").replace("WHERE kind = 'role'", "WHERE kind IN ('role', 'ca')")


def to_dict(m: Any) -> dict[str, Any]:
    from app.search.entities import to_json

    data: dict[str, Any] = to_json(m)
    data.pop("read", None)
    return data
