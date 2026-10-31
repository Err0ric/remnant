"""A person's timeline (ADR-0038 section 9, rows 27 to 29): one row per action across
sources, newest first: Microsoft 365 sign-ins (per app, outcome, and hour), Claude sessions
(one row each), AI services first used in the window, app consents, and every other event
grouped by source, message, and hour. Microsoft 365 audit records count once (D122).

The person is resolved across forms: every name whose key (ADR-0018: lower case, no
`DOMAIN\\`, an organization address reduced to its local part) is the person's key or an
alias of it. Each row carries Search SQL for its own events. Deterministic SQL on the
caller's `events` view; no model is called."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.ai.consents import CONSENTS_CTE
from app.ai.sessions import _a
from app.ai.usage import _use_ctes
from app.core.errors import ParamInvalidError
from app.engine.duckdb import QueryEngine, QueryScope
from app.search import drill
from app.search.dashboard import FAILED, INTERRUPTED
from app.search.identity import IdentityMap, key_sql

TIMEOUT_S = 30.0
MAX_ROWS = 500
_TS = drill.TS
M365_AUDIT = "('m365_directory_audit', 'm365_management_activity')"
_OP = "lower(rtrim(trim(message), '.'))"
_K = (
    "coalesce(metadata_correlation_uid, coalesce(lower(actor_user_name), '') || '|' "
    f"|| strftime({_TS}, '%Y-%m-%d %H:%M'))"
)
_HOUR = f"date_trunc('hour', timezone('UTC', {_TS}))"


@dataclass(slots=True)
class Row:
    kind: str  # signin | session | ai_first | consent | audit | events
    start: str
    end: str
    title: str
    detail: str
    count: int
    source: str
    tone: str  # neutral | warn (a failure); never a severity color
    sql: str  # Search SQL with {from} and {to}; the row's own window
    item_id: str | None = None  # an alert row opens its alert, not Search


@dataclass(slots=True)
class Timeline:
    person: str
    forms: list[str]
    devices: list[str]
    start: str
    end: str
    rows: list[Row] = field(default_factory=list)
    more: bool = False
    sql: str = ""
    signins_sql: str = ""  # the person's Microsoft 365 sign-ins, for the Sign-ins tab
    sources: list[str] = field(default_factory=list)


def _iso(v: Any) -> str:
    t = v if isinstance(v, datetime) else datetime.fromisoformat(str(v))
    return (t if t.tzinfo else t.replace(tzinfo=UTC)).astimezone(UTC).isoformat()


def _mine(ident: IdentityMap, keys: list[str]) -> str:
    """The person condition with literals only, for Search (it has no parameters)."""
    org = "[" + ", ".join(drill.lit(d) for d in (ident.domains or [""])) + "]"
    cond = f"list_contains({drill.lits(keys)}, {key_sql('actor_user_name')})"
    return cond.replace("$id_org", org)


def timeline(
    engine: QueryEngine,
    allowed: list[str] | None,
    ident: IdentityMap,
    catalog_pairs: list[tuple[str, str]],
    person: str,
    start: datetime,
    end: datetime,
) -> Timeline:
    if not person.strip():
        raise ParamInvalidError("Name a person")
    keys = ident.keys_for(person)
    mine = _mine(ident, keys)
    org = "[" + ", ".join(drill.lit(d) for d in (ident.domains or [""])) + "]"
    scope = QueryScope(allowed, start, end)
    out = Timeline(
        person=ident.key(person), forms=[], devices=[], start=start.isoformat(),
        end=end.isoformat(), sql=drill.events(mine),
    )  # fmt: skip
    sources: set[str] = set()
    outcome = (
        f"CASE WHEN status_id = 1 THEN 'Signed in' WHEN {INTERRUPTED} THEN 'Interrupted'"
        f" WHEN {FAILED} THEN 'Failed' ELSE 'Sign-in' END"
    )
    out.signins_sql = drill.events(
        f"template_id = 'm365_signin' AND {mine}",
        f"time, actor_user_name, coalesce(resource_name, message) AS app, {outcome} AS outcome,"
        " src_endpoint_ip, device_hostname, event_id",
    )

    def run(sql: str, name: str) -> list[list[Any]]:
        res = engine.run(sql, scope, timeout_s=TIMEOUT_S, intel=False, name=f"timeline.{name}")
        sources.update(res.sources)
        return res.rows

    def add(kind: str, s: Any, e: Any, title: str, detail: str, n: Any, src: str,
            where: str, tone: str = "neutral") -> None:  # fmt: skip
        # `end` is exclusive, as Search's window is: one second past the last event.
        stop = datetime.fromisoformat(_iso(e)) + timedelta(seconds=1)
        out.rows.append(
            Row(kind, _iso(s), stop.isoformat(), title, detail, int(n or 0), src, tone,
                drill.events(f"{mine} AND {where}"))
        )  # fmt: skip

    for name, devs in run(
        f"SELECT DISTINCT actor_user_name, device_hostname FROM events WHERE {mine} LIMIT 200",  # noqa: S608  # escaped literals only
        "forms",
    ):
        if name and str(name) not in out.forms:
            out.forms.append(str(name))
        if devs and str(devs) not in out.devices:
            out.devices.append(str(devs))
    out.forms.sort()
    out.devices.sort()

    for _hour, app, how, n, s, e in run(
        f"SELECT {_HOUR}, coalesce(resource_name, message), {outcome}, count(*), min({_TS}),"  # noqa: S608  # escaped literals only
        f" max({_TS}) FROM events WHERE template_id = 'm365_signin' AND {mine}"
        " GROUP BY 1, 2, 3 ORDER BY 1 DESC LIMIT 300",
        "signins",
    ):
        app_s = str(app or "an app")
        cond = (
            f"template_id = 'm365_signin' AND coalesce(resource_name, message) = {drill.lit(app_s)}"
        )
        add("signin", s, e, f"{how} to {app_s}", "Microsoft 365", n, "m365_signin", cond,
            "warn" if how == "Failed" else "neutral")  # fmt: skip

    for sid, s, e, dev, calls, failed in run(
        f"SELECT {_a('session_id')}, min({_TS}), max({_TS}), any_value(device_hostname),"  # noqa: S608  # escaped literals only
        " count(*) FILTER (WHERE message = 'claude_hooks.pre_tool_use'),"
        " count(*) FILTER (WHERE message = 'claude_hooks.post_tool_use_failure')"
        f" FROM events WHERE template_id = 'claude_hooks' AND {mine}"
        f" AND {_a('session_id')} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 200",
        "sessions",
    ):
        detail = f"{int(calls or 0)} tool calls" + (f", {int(failed)} failed" if failed else "")
        cond = f"template_id = 'claude_hooks' AND {_a('session_id')} = {drill.lit(str(sid))}"
        add("session", s, e, f"Claude session on {dev or 'a device'}", detail, calls,
            "claude_hooks", cond, "warn" if failed else "neutral")  # fmt: skip

    key_who = key_sql("who").replace("$id_org", org)
    for svc, s in run(
        f"WITH {_use_ctes(catalog_pairs, False)}\n"  # catalog values checked in _values
        f"SELECT service_id, min(first_t) FROM r WHERE list_contains({drill.lits(keys)}, {key_who})"
        " GROUP BY 1 LIMIT 100",
        "ai",
    ):
        add("ai_first", s, s, f"First used {svc} in this window", "AI service", 1, "network",
            "true")  # fmt: skip
        out.rows[-1].sql = ""  # the use rows need the AI usage query; opened from AI usage

    consent_mine = f"list_contains({drill.lits(keys)}, {key_sql('who')})".replace("$id_org", org)
    for ts, app, status in run(
        f"WITH {CONSENTS_CTE}\nSELECT ts, app, status_id FROM consents WHERE {consent_mine}"
        " ORDER BY ts DESC LIMIT 100",
        "consents",
    ):
        blocked = status == 2
        what = "Consent blocked" if blocked else "Granted consent"
        cond = f"template_id IN {M365_AUDIT} AND message ILIKE 'Consent to application%'"
        add("consent", ts, ts, f"{what}: {app or 'an app with no name'}", "Microsoft 365", 1,
            "m365", cond, "warn" if blocked else "neutral")  # fmt: skip

    for _hour, op, n, s, e in run(
        f"SELECT {_HOUR}, {_OP}, count(DISTINCT {_K}), min({_TS}), max({_TS}) FROM events"  # noqa: S608  # escaped literals only
        f" WHERE template_id IN {M365_AUDIT} AND {mine}"
        " AND message NOT ILIKE 'Consent to application%' GROUP BY 1, 2 ORDER BY 1 DESC LIMIT 300",
        "audit",
    ):
        add("audit", s, e, str(op), "Microsoft 365 audit", n, "m365",
            f"template_id IN {M365_AUDIT} AND {_OP} = {drill.lit(str(op))}")  # fmt: skip

    for _hour, src, msg, n, s, e, bad in run(
        f"SELECT {_HOUR}, source_id, message, count(*), min({_TS}), max({_TS}),"  # noqa: S608  # escaped literals only
        " count(*) FILTER (WHERE status_id = 2) FROM events"
        " WHERE template_id NOT LIKE 'm365_%' AND template_id <> 'claude_hooks'"
        f" AND {mine} GROUP BY 1, 2, 3 ORDER BY 1 DESC LIMIT 300",
        "events",
    ):
        add("events", s, e, str(msg or "Event"), str(src), n, str(src),
            f"source_id = {drill.lit(str(src))} AND message = {drill.lit(str(msg or ''))}",
            "warn" if bad else "neutral")  # fmt: skip

    out.rows.sort(key=lambda r: r.start, reverse=True)
    out.more = len(out.rows) > MAX_ROWS
    out.rows = out.rows[:MAX_ROWS]
    out.sources = sorted(sources)
    return out


def window(days: int, now: datetime) -> tuple[datetime, datetime]:
    now = now.astimezone(UTC)
    return now - timedelta(days=days), now
