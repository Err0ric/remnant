"""The Microsoft 365 area (ADR-0038 section 5): Overview numbers and the tabs' lists for one
page window, on the caller's own view.

Every count uses the one-operation key (D122) where Graph and the Management Activity API
report the same operation; every number carries its Search query (ADR-0039). Sign-ins
split three ways (owner edit 2): succeeded, interrupted (Entra asked for something more,
such as MFA, and the sign-in may still complete), and failed. No model is called.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.ai import consents
from app.core.timing import in_context
from app.engine.duckdb import QueryEngine, QueryScope
from app.enrich.networks import Places
from app.search import drill, mail_rules
from app.search.admin_changes import ADMIN_SQL
from app.search.buckets import bucket_sql
from app.search.dashboard import (
    _CHANGE_KEY,
    _CHANGE_KIND,
    _M365_AUDIT,
    FAILED,
    INTERRUPT_CODES,
    INTERRUPTED,
    MAX_IPS,
    History,
    Kpi,
    Row,
    Window,
    _history,
    _Run,
    _utc,
    bounds,
    changes_drill,
    fact_run,
    outside_where,
    trend_points,
    zone,
)

TOP = 5
PARALLEL = 4  # Overview queries running at once
TS = drill.TS
SIGNIN = "template_id = 'm365_signin'"
RISKY = f"{SIGNIN} AND severity_id >= 3"
_OP = "lower(rtrim(trim(message), '.'))"
_ACTIVITY = "template_id = 'm365_management_activity'"

# The counts row: Exchange, DLP, SharePoint, and Copilot operations come only from the
# Management Activity API, so each record is one operation.
COUNTS: list[tuple[str, str, str]] = [
    ("dlp", "DLP matches", f"{_OP} = 'dlprulematch'"),
    ("downloads", "File downloads", f"{_OP} IN ('filedownloaded', 'filesyncdownloadedfull')"),
    (
        "external_shares",
        "External shares",
        f"{_OP} IN ('anonymouslinkcreated', 'sharinginvitationcreated')",
    ),
    ("copilot", "Copilot interactions", f"{_OP} = 'copilotinteraction'"),
]

# Why a sign-in failed: the mapped reason, else Entra's own text in the record (events
# stored before m365_signin 1.1.0 have no status_detail), and the error code beside it
# (owner, 2026-10-31). "No reason given" only when the record has neither.
REASON = (
    "coalesce(nullif(status_detail, ''),"
    " nullif(TRY(json_extract_string(raw, '$.status.failureReason')), ''))"
)
CODE = "TRY_CAST(TRY(json_extract_string(raw, '$.status.errorCode')) AS INTEGER)"
NO_REASON = "No reason given"
APP = "coalesce(nullif(resource_name, ''), nullif(message, ''), 'Unknown app')"


def reason_label(reason: str | None, code: int | None) -> str:
    """ "Invalid username or password. (50126)", "Error 50126", or "No reason given"."""
    text = (reason or "").strip()
    if text and code is not None:
        return f"{text} ({code})"
    if text:
        return text
    return f"Error {code}" if code is not None else NO_REASON


def reason_where(reason: str | None, code: int | None) -> str:
    """The Search condition for one reason row: the same reason and code."""
    r = f"{REASON} = {drill.lit(reason)}" if reason else f"{REASON} IS NULL"
    c = f"{CODE} = {int(code)}" if code is not None else f"{CODE} IS NULL"
    return f"{r} AND {c}"


# --- Facts (ADR-0041) --------------------------------------------------------------------
# The Overview reads small facts, not events: sign-ins per hour, person, app, address,
# outcome, and reason; the counts row's operations per hour; one row per change and per
# consent with its one-operation key (D122); and each source's first event. The same SQL
# builds a closed day's rollup and reads the days the rollup does not have, so both give
# the same numbers. Keys are kept, so changes and consents reported by Graph and the
# Management API are counted once even when they are separate sources.
FACT_COLUMNS = (
    "kind, source_id, t, outcome, risky, who, app, ip, reason, code, op, k, sub, status, n, last_t"
)
_NONE = {
    c: f"CAST(NULL AS {ty}) AS {c}"
    for c, ty in (
        ("outcome", "VARCHAR"), ("risky", "BOOLEAN"), ("who", "VARCHAR"), ("app", "VARCHAR"),
        ("ip", "VARCHAR"), ("reason", "VARCHAR"), ("code", "INTEGER"), ("op", "VARCHAR"),
        ("k", "VARCHAR"), ("sub", "VARCHAR"), ("status", "INTEGER"),
        ("last_t", "TIMESTAMPTZ"),
    )
}  # fmt: skip


def _cols(**given: str) -> str:
    """The fact columns in order: the given expressions, NULL for the rest."""
    out = []
    for c in FACT_COLUMNS.split(", "):
        if c in given:
            out.append(f"{given[c]} AS {c}")
        else:
            out.append(_NONE[c])
    return ", ".join(out)


_CODES = list(INTERRUPT_CODES)
_IS_INTERRUPT = f"list_contains({_CODES}, c)"
_IS_FAILED = f"status_id = 2 AND NOT coalesce({_IS_INTERRUPT}, false)"
_ACTIVITY_OP = "CASE " + " ".join(f"WHEN {cond} THEN '{key}'" for key, _, cond in COUNTS) + " END"

# The same split as INTERRUPTED and FAILED, with the code read once per sign-in.
_SIGNIN_FROM = f"""
FROM (
  SELECT source_id, {TS} AS ts, status_id, severity_id, actor_user_name, src_endpoint_ip,
         {APP} AS app, CASE WHEN status_id = 2 THEN {CODE} END AS c,
         CASE WHEN status_id = 2 THEN {REASON} END AS reason
  FROM events WHERE {SIGNIN}
)
GROUP BY ALL"""  # noqa: S608  # fixed SQL text
_ACTIVITY_FROM = f"""
FROM (SELECT source_id, {TS} AS ts, {_ACTIVITY_OP} AS op FROM events WHERE {_ACTIVITY})
WHERE op IS NOT NULL
GROUP BY ALL"""  # noqa: S608  # fixed SQL text
# CHANGES_SQL's rows before the count: a change per kind, key, and operation.
_CHANGE_FROM = f"""
FROM (
  SELECT source_id, ts, op, {_CHANGE_KEY} AS k, {_CHANGE_KIND} AS kind
  FROM (
    SELECT source_id, {TS} AS ts, {_OP} AS op, raw, event_id, metadata_correlation_uid,
           actor_user_name
    FROM events WHERE {_M365_AUDIT}
  )
)
WHERE kind IS NOT NULL
GROUP BY source_id, k, op, kind"""  # noqa: S608  # fixed SQL text
_CONSENT_FROM = f"""
FROM events WHERE {consents.WHERE}
GROUP BY source_id, {consents.KEY}, {consents.OP}"""  # fixed SQL text

_MAILRULE_FROM = f"""
FROM (WITH {mail_rules.RULES_CTE.strip()}
SELECT * FROM classed)"""  # noqa: S608  # fixed SQL text
_FAIL_ONLY = f"CASE WHEN {_IS_FAILED} THEN {{}} END"
_OUTCOME_EXPR = (
    "CASE WHEN status_id = 1 THEN 'ok'"
    f" WHEN status_id = 2 AND {_IS_INTERRUPT} THEN 'interrupted'"
    " WHEN status_id = 2 THEN 'failed' END"
)
FACTS: dict[str, str] = {
    # Who and from where, for the totals, the outside-countries card, and the spike's
    # person; the app and the reason are a separate kind so neither multiplies the other.
    "signin": "SELECT "
    + _cols(
        kind="'signin'",
        source_id="source_id",
        t="date_trunc('hour', ts)",
        outcome=_OUTCOME_EXPR,
        risky="coalesce(severity_id >= 3, false)",
        who="actor_user_name",
        ip="src_endpoint_ip",
        n="count(*)",
        last_t="max(ts)",
    )
    + _SIGNIN_FROM,
    # Counts only, per hour, outcome, and risk: the totals, outcome chart, and trend, which
    # would otherwise read every person and address.
    "signin_n": "SELECT "
    + _cols(
        kind="'signin_n'",
        source_id="source_id",
        t="date_trunc('hour', ts)",
        outcome=_OUTCOME_EXPR,
        risky="coalesce(severity_id >= 3, false)",
        n="count(*)",
    )
    + _SIGNIN_FROM,
    "signin_app": "SELECT "
    + _cols(
        kind="'signin_app'",
        source_id="source_id",
        t="date_trunc('hour', ts)",
        outcome=_OUTCOME_EXPR,
        app="app",
        reason=_FAIL_ONLY.format("reason"),
        code=_FAIL_ONLY.format("c"),
        n="count(*)",
    )
    + _SIGNIN_FROM,
    "activity": "SELECT "
    + _cols(
        kind="'activity'", source_id="source_id", t="date_trunc('hour', ts)", op="op", n="count(*)"
    )
    + _ACTIVITY_FROM,
    "change": "SELECT "
    + _cols(
        kind="'change'",
        source_id="source_id",
        t="min(ts)",
        op="op",
        k="k",
        sub="kind",
        n="count(*)",
    )
    + _CHANGE_FROM,
    "consent": "SELECT "
    + _cols(
        kind="'consent'",
        source_id="source_id",
        t=f"min({TS})",
        op=consents.OP,
        k=consents.KEY,
        status=consents.STATUS,
        n="count(*)",
    )
    + _CONSENT_FROM,
    # Inbox rules with their class (D132): one row per rule; they are few.
    "mailrule": "SELECT "
    + _cols(
        kind="'mailrule'",
        source_id="source_id",
        t="time",
        outcome="class",
        risky="risky",
        k="event_id",
        n="1",
    )
    + _MAILRULE_FROM,
    "first": "SELECT "
    + _cols(kind="'first'", source_id="source_id", t=f"min({TS})", n="count(*)")
    # Per hour, so a range that starts mid-day keeps exactly the hours in it.
    + f"\nFROM events GROUP BY source_id, date_trunc('hour', {TS})",
}
# A closed day's rollup: every kind at once.
BUILD_SQL = "\nUNION ALL\n".join(f"({sql.strip()})" for sql in FACTS.values())


def facts(kind: str, rollup: bool) -> str:
    """One kind of fact, as a CTE body: from events, and with `rollup` also from the
    rollup's days in `$covered` ("source|YYYY-MM-DD"), which the engine leaves out of
    `events` (`skip_days`)."""
    live = FACTS[kind].strip()
    if not rollup:
        return live
    return (
        f"({live})\nUNION ALL\nSELECT {FACT_COLUMNS} FROM m365_rollup\n"
        f"WHERE kind = '{kind}' AND (source_id || '|' || day) IN (SELECT unnest($covered))"
        " AND t >= $fact_lo AND t <= $fact_hi"
    )


def _with(kind: str, body: str, rollup: bool) -> str:
    """`body` reads `f`, the facts of one kind; one starting with a comma adds CTEs."""
    body = body.strip()
    return f"WITH f AS (\n{facts(kind, rollup)}\n){'' if body.startswith(',') else chr(10)}{body}"


_SIGNIN_TOTALS = """
SELECT coalesce(sum(n) FILTER (WHERE t >= $start), 0),
       coalesce(sum(n) FILTER (WHERE t < $start), 0),
       coalesce(sum(n) FILTER (WHERE t >= $start AND outcome = 'failed'), 0),
       coalesce(sum(n) FILTER (WHERE t < $start AND outcome = 'failed'), 0),
       coalesce(sum(n) FILTER (WHERE t >= $start AND risky), 0),
       coalesce(sum(n) FILTER (WHERE t < $start AND risky), 0)
FROM f"""
# The person, and the app, with the most failed or interrupted sign-ins in each bucket (a
# tie goes to the first by name, so the tooltip does not change between loads).
_SPIKE = """
SELECT b, first(x ORDER BY n DESC, x) AS top, max(n) AS n
FROM (
  SELECT {BUCKET} AS b, {x} AS x, sum(n) AS n
  FROM f WHERE outcome IN ('failed', 'interrupted') AND t >= $start
  GROUP BY 1, 2
)
GROUP BY 1""".replace("{BUCKET}", bucket_sql())
_OUTCOME = """
SELECT {BUCKET} AS b,
       coalesce(sum(n) FILTER (WHERE outcome = 'ok'), 0),
       coalesce(sum(n) FILTER (WHERE outcome = 'interrupted'), 0),
       coalesce(sum(n) FILTER (WHERE outcome = 'failed'), 0)
FROM f WHERE t >= $start
GROUP BY 1""".replace("{BUCKET}", bucket_sql())
_REASONS = f"""
SELECT reason, code, sum(n) AS n
FROM f WHERE outcome = 'failed' AND t >= $start
GROUP BY 1, 2 ORDER BY n DESC, reason NULLS LAST, code LIMIT {TOP}"""  # noqa: S608  # fixed SQL text
_APPS = f"""
SELECT app, sum(n) AS n FROM f WHERE t >= $start
GROUP BY 1 ORDER BY n DESC, app LIMIT {TOP}"""  # noqa: S608  # fixed SQL text
_OUTSIDE = f"""
SELECT ip_country(ip) AS country, sum(n) AS n, count(DISTINCT who) AS people
FROM f
WHERE outcome = 'ok' AND t >= $start AND NOT list_contains($approved, ip_country(ip))
GROUP BY 1 ORDER BY n DESC, country LIMIT {TOP}"""  # noqa: S608  # fixed SQL text
_COUNTS = (
    "SELECT "
    + ",\n       ".join(
        f"coalesce(sum(n) FILTER (WHERE t >= $start AND op = '{key}'), 0),"
        f" coalesce(sum(n) FILTER (WHERE t < $start AND op = '{key}'), 0)"
        for key, _, _ in COUNTS
    )
    + "\nFROM f"
)
# CHANGES_SQL on the facts: one change per kind, key, and operation (D122).
_CHANGES = """,
one AS (SELECT sub AS kind, min(t) AS ts FROM f GROUP BY sub, k, op)
SELECT kind, count(*) FILTER (WHERE ts >= $start), count(*) FILTER (WHERE ts < $start)
FROM one GROUP BY kind"""
# consents.COUNTS_SQL's first three numbers on the facts: granted now and before, blocked
# now, one per consent (D122).
_CONSENTS = f""",
one AS (SELECT min(t) AS ts, {consents.STATUS.replace("status_id", "status")} AS status
        FROM f GROUP BY k, op)
SELECT count(*) FILTER (WHERE coalesce(status, 1) <> 2 AND ts >= $start),
       count(*) FILTER (WHERE coalesce(status, 1) <> 2 AND ts < $start),
       count(*) FILTER (WHERE status = 2 AND ts >= $start)
FROM one"""  # noqa: S608  # fixed SQL text
_FIRST = "SELECT source_id, min(t) FROM f GROUP BY 1"
_MAIL = """
SELECT count(*) FILTER (WHERE risky AND t >= $start),
       count(*) FILTER (WHERE risky AND t < $start),
       count(*) FILTER (WHERE outcome = 'organizing' AND t >= $start)
FROM f"""
# The Dashboard's Identity card (both windows) and its top failing people.
_FAILED_TREND = """
SELECT {BUCKET} AS b, sum(n)
FROM f WHERE outcome = 'failed'
GROUP BY 1""".replace("{BUCKET}", bucket_sql())
# Successful sign-ins per address, now and before: the Dashboard's outside-countries count.
_OK_BY_IP = f"""
SELECT ip, coalesce(sum(n) FILTER (WHERE t >= $start), 0),
       coalesce(sum(n) FILTER (WHERE t < $start), 0)
FROM f WHERE outcome = 'ok' AND nullif(ip, '') IS NOT NULL
GROUP BY 1 ORDER BY 2 + 3 DESC LIMIT {MAX_IPS}"""  # noqa: S608  # fixed SQL text
_TOP_FAILING = f"""
SELECT nullif(trim(who), '') AS who, sum(n) AS n, max(last_t) AS last FROM f
WHERE outcome = 'failed' AND t >= $start AND nullif(trim(who), '') IS NOT NULL
GROUP BY 1 ORDER BY n DESC, who LIMIT {TOP}"""  # noqa: S608  # fixed SQL text

# Overview query -> (fact kind, body).
QUERIES: dict[str, tuple[str, str]] = {
    "first": ("first", _FIRST),
    "signins": ("signin_n", _SIGNIN_TOTALS),
    "spike_user": ("signin", _SPIKE.format(x="coalesce(nullif(lower(who), ''), '(no user)')")),
    "spike_app": ("signin_app", _SPIKE.format(x="app")),
    "outcome": ("signin_n", _OUTCOME),
    "reasons": ("signin_app", _REASONS),
    "apps": ("signin_app", _APPS),
    "outside": ("signin", _OUTSIDE),
    "counts": ("activity", _COUNTS),
    "changes": ("change", _CHANGES),
    "consents": ("consent", _CONSENTS),
    "mail": ("mailrule", _MAIL),
    "failed_trend": ("signin_n", _FAILED_TREND),
    "top_failing": ("signin", _TOP_FAILING),
    "ok_by_ip": ("signin", _OK_BY_IP),
}


OVERVIEW = [n for n in QUERIES if n not in ("failed_trend", "top_failing", "ok_by_ip")]


def query(name: str, rollup: bool) -> str:
    kind, body = QUERIES[name]
    return _with(kind, body, rollup)


def run_facts(
    run: _Run, sources: list[str], names: list[str], rollup: bool, **extra: Any
) -> dict[str, list[list[Any]]]:
    """Several fact queries at once (each reads today's events, so they overlap instead of
    queueing; the engine's slots still bound how many run together)."""
    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        rows = pool.map(in_context(lambda n: run(query(n, rollup), sources, **extra)), names)
        return dict(zip(names, rows, strict=True))


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
    # Per point, who and which app had the most failed or interrupted sign-ins, with the
    # count ("erin@example.com (12)"), so a repeating spike reads from the tooltip.
    top_user: list[str] = field(default_factory=list)
    top_app: list[str] = field(default_factory=list)


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
        # Inbox rules with their settings and class, grouped by burst on the page (D132).
        "mail": mail_rules.list_sql(),
        "dlp": drill.events(f"{_ACTIVITY} AND {_OP} = 'dlprulematch'", ACTIVITY_COLUMNS),
        "consents": consents_list(),
        "registrations": drill.events(REGISTRATIONS, ACTIVITY_COLUMNS),
        "admin": ADMIN_SQL,
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


class Covers(Protocol):
    def covered(self, scope: QueryScope) -> list[str]: ...

    def today(self, scope: QueryScope) -> tuple[list[str], list[str], datetime] | None: ...


def source_ids(sources: list[tuple[str, str, str | None]]) -> list[str]:
    """Microsoft 365 sources: a connector, or a source whose template is one of its."""
    return [sid for sid, kind, tpl in sources if kind == "m365" or (tpl or "").startswith("m365_")]


def overview(
    engine: QueryEngine,
    allowed: list[str] | None,
    sources: list[tuple[str, str, str | None]],
    places: Places,
    window: Window,
    now: datetime,
    rollup: Covers | None = None,
    tz: str = "UTC",
) -> M365:
    """With `rollup`, closed days come from the Microsoft 365 rollup where it has them and
    the rest from events (ADR-0041)."""
    start, before, _ = bounds(window, now, tz)
    m365 = source_ids([s for s in sources if allowed is None or s[0] in set(allowed)])
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
    unit, points = trend_points(window, now, tz)
    base = _Run(
        engine,
        QueryScope(sources=None, start=before, end=now),
        {"start": start, "unit": unit, "tz": zone(tz).key, "approved": list(approved)},
    )
    run, r = fact_run(base, m365, rollup)
    got = run_facts(run, m365, [n for n in OVERVIEW if n != "outside" or approved], r)
    first = {str(s): t for s, at in got["first"] if (t := _utc(at)) is not None}
    out.history = _history(first, m365, start, before)

    total, total_b, failed, failed_b, risky, risky_b = (got["signins"] or [[0] * 6])[0]
    out.sign_ins = Kpi(int(total), int(total_b), drill=drill.events(SIGNIN, SIGNIN_COLUMNS))
    out.failed = Kpi(
        int(failed), int(failed_b), drill=drill.events(f"{SIGNIN} AND {FAILED}", SIGNIN_COLUMNS)
    )
    out.risky = Kpi(int(risky), int(risky_b), drill=drill.events(RISKY, SIGNIN_COLUMNS))
    if approved:
        where = outside_where(["m365_signin"], approved)
        rows = got["outside"]
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
    granted, granted_b, blocked = (got["consents"] or [[0, 0, 0]])[0][:3]
    out.consents = Kpi(
        int(granted),
        int(granted_b),
        int(blocked),
        drill=consents.drill_sql(blocked=False),
        extra_drill=consents.drill_sql(blocked=True),
    )
    changes = {str(k): (int(a), int(b)) for k, a, b in got["changes"]}
    role, ca = changes.get("role", (0, 0)), changes.get("ca", (0, 0))
    out.admin_changes = Kpi(role[0] + ca[0], role[1] + ca[1], drill=_admin_drill())
    c = (got["counts"] or [[0] * (2 * len(COUNTS))])[0]
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
    # Risky inbox rules first, organizing ones beside them: the Dashboard's card (D132).
    risky, risky_b, organizing = (got["mail"] or [[0, 0, 0]])[0]
    out.counts.insert(
        0,
        Count(
            "mail_rules",
            "Risky mail rules",
            Kpi(
                int(risky),
                int(risky_b),
                int(organizing),
                drill=mail_rules.list_sql("risky"),
                extra_drill=mail_rules.list_sql("class = 'organizing'"),
            ),
        ),
    )
    at = {p: i for i, p in enumerate(points)}
    ok, inter, fail = ([0] * len(points) for _ in range(3))
    for b, s, i_, f in got["outcome"]:
        t = _utc(b)
        if t is not None and t in at:
            ok[at[t]], inter[at[t]], fail[at[t]] = int(s), int(i_), int(f)
    top_user, top_app = [""] * len(points), [""] * len(points)
    for name, tops in (("spike_user", top_user), ("spike_app", top_app)):
        for b, top, n in got[name]:
            t = _utc(b)
            if t is not None and t in at:
                tops[at[t]] = f"{top} ({int(n)})"
    out.outcome = Outcome(
        points,
        ok,
        inter,
        fail,
        drill.events(f"{SIGNIN} AND status_id = 1", SIGNIN_COLUMNS),
        drill.events(f"{SIGNIN} AND {INTERRUPTED}", SIGNIN_COLUMNS),
        drill.events(f"{SIGNIN} AND {FAILED}", SIGNIN_COLUMNS),
        top_user,
        top_app,
    )
    out.reasons = [
        Row(
            reason_label(r, code),
            int(n),
            kind="reason",
            detail="" if code is None else str(code),
            drill=drill.events(
                f"{SIGNIN} AND {FAILED}\n  AND {reason_where(r, code)}", SIGNIN_COLUMNS
            ),
        )
        for r, code, n in got["reasons"]
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
        for a, n in got["apps"]
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
