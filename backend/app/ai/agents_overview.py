"""Agents > Overview and Tools (ADR-0038 section 6), from the hooks plugin's records on the
caller's own view: sessions, people, tool calls, failed calls, MCP servers not approved
that were used, devices whose records arrive late or stopped, and one row per tool with
its status, people, devices, calls, failures, and first and last use. Deterministic SQL;
no model is called. Every number carries its Search query (ADR-0039)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.ai.catalog import Catalog
from app.ai.sessions import _ONE_COPY, _a
from app.engine.duckdb import QueryEngine, QueryScope
from app.search import drill
from app.search.dashboard import FIRST_EVENT_SQL, History, Kpi, _history, _utc

TIMEOUT_S = 20.0
LATE_S = 3600  # delivered an hour or more after it happened (the plugin's offline queue)
MAX_TOOLS = 200

_TS = "coalesce(time, time_observed)"
_TOOL = f"coalesce({_a('mcp_server_name')}, {_a('tool_name')})"
_CALL = "message = 'claude_hooks.pre_tool_use'"
_FAIL = "message = 'claude_hooks.post_tool_use_failure'"

OVERVIEW_SQL = f"""
WITH {_ONE_COPY}
SELECT count(DISTINCT {_a("session_id")}) FILTER (WHERE {_TS} >= $start),
       count(DISTINCT {_a("session_id")}) FILTER (WHERE {_TS} < $start),
       count(DISTINCT nullif(actor_user_name, '')) FILTER (WHERE {_TS} >= $start),
       count(DISTINCT nullif(actor_user_name, '')) FILTER (WHERE {_TS} < $start),
       count(*) FILTER (WHERE {_TS} >= $start AND {_CALL}),
       count(*) FILTER (WHERE {_TS} < $start AND {_CALL}),
       count(*) FILTER (WHERE {_TS} >= $start AND {_FAIL}),
       count(*) FILTER (WHERE {_TS} < $start AND {_FAIL}),
       count(DISTINCT device_hostname) FILTER (
         WHERE {_TS} >= $start AND epoch(time_observed) - epoch({_TS}) >= {LATE_S})
FROM hooks"""  # noqa: S608  # fixed SQL text

# Devices that sent before the window and nothing in it: stopped, or the plugin removed.
MISSING_SQL = f"""
WITH {_ONE_COPY}
SELECT device_hostname FROM hooks
WHERE device_hostname IS NOT NULL
GROUP BY 1
HAVING max({_TS}) < $start"""  # noqa: S608  # fixed SQL text

TOOLS_SQL = f"""
WITH {_ONE_COPY}
SELECT {_TOOL} AS tool, {_a("mcp_server_name")} IS NOT NULL AS mcp,
       count(DISTINCT nullif(actor_user_name, '')) AS people,
       count(DISTINCT device_hostname) AS devices,
       count(*) FILTER (WHERE {_CALL}) AS calls,
       count(*) FILTER (WHERE {_FAIL}) AS failed,
       min({_TS}) AS first_seen, max({_TS}) AS last_seen
FROM hooks
WHERE {_TS} >= $start AND {_a("tool_name")} IS NOT NULL
GROUP BY 1, 2
ORDER BY calls DESC, tool
LIMIT {MAX_TOOLS}"""  # noqa: S608  # fixed SQL text

HOOKS = "template_id = 'claude_hooks'"
COLUMNS = (
    "time, actor_user_name, device_hostname, message,"
    f" {_a('session_id')} AS session_id, {_TOOL} AS tool, event_id"
)


@dataclass(slots=True)
class ToolRow:
    tool: str
    mcp: bool
    status: str  # approved, not_approved, unreviewed; built-in tools are "built_in"
    people: int
    devices: int
    calls: int
    failed: int
    first_seen: str | None
    last_seen: str | None
    drill: str


@dataclass(slots=True)
class AgentsOverview:
    days: int
    start: str
    end: str
    before: str
    has_source: bool
    history: History = field(default_factory=lambda: History(True))
    sessions: Kpi | None = None
    people: Kpi | None = None
    calls: Kpi | None = None
    failed: Kpi | None = None
    mcp_not_approved: Kpi | None = None
    late_devices: Kpi | None = None
    missing_devices: list[str] = field(default_factory=list)
    tools: list[ToolRow] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    return v.isoformat() if isinstance(v, datetime) else str(v)


def overview(
    engine: QueryEngine, catalog: Catalog, telemetry: list[str], now: datetime, days: int
) -> AgentsOverview:
    now = now.astimezone(UTC)
    start = now - timedelta(days=days)
    before = start - timedelta(days=days)
    out = AgentsOverview(
        days=days,
        start=start.isoformat(),
        end=now.isoformat(),
        before=before.isoformat(),
        has_source=bool(telemetry),
    )
    if not telemetry:
        return out
    scope = QueryScope(telemetry, before, now)
    params = {"start": start}
    firsts = engine.run(FIRST_EVENT_SQL, scope, timeout_s=TIMEOUT_S, name="agents.first")
    first = {str(s): t for s, at in firsts.rows if (t := _utc(at)) is not None}
    out.history = _history(first, telemetry, start, before)
    head = engine.run(OVERVIEW_SQL, scope, params, timeout_s=TIMEOUT_S, name="agents.overview")
    s, s_b, p, p_b, c, c_b, f, f_b, late = (head.rows or [[0] * 9])[0]
    out.sessions = Kpi(int(s), int(s_b), drill=drill.grouped(HOOKS, _a("session_id"), "session_id"))
    out.people = Kpi(
        int(p),
        int(p_b),
        drill=drill.grouped(f"{HOOKS} AND actor_user_name <> ''", "actor_user_name", "person"),
    )
    out.calls = Kpi(int(c), int(c_b), drill=drill.events(f"{HOOKS} AND {_CALL}", COLUMNS))
    out.failed = Kpi(int(f), int(f_b), drill=drill.events(f"{HOOKS} AND {_FAIL}", COLUMNS))
    out.late_devices = Kpi(
        int(late),
        None,
        drill=drill.grouped(
            f"{HOOKS} AND epoch(time_observed) - epoch({_TS}) >= {LATE_S}",
            "device_hostname",
            "device",
        ),
    )
    tools = engine.run(TOOLS_SQL, scope, params, timeout_s=TIMEOUT_S, name="agents.tools")
    rules = catalog.mcp_rules()
    for tool, mcp, people, devices, calls, failed, first, last in tools.rows:
        name = str(tool)
        status = str(catalog.mcp_status(name, rules)) if mcp else "built_in"
        out.tools.append(
            ToolRow(
                name, bool(mcp), status, int(people), int(devices), int(calls), int(failed),
                _iso(first), _iso(last),
                drill.events(f"{HOOKS} AND {_TOOL} = {drill.lit(name)}", COLUMNS),
            )
        )  # fmt: skip
    bad = [t for t in out.tools if t.mcp and t.status == "not_approved"]
    names = drill.lits(sorted(t.tool for t in bad)) if bad else "['']"
    out.mcp_not_approved = Kpi(
        len(bad),
        None,
        drill=drill.grouped(
            f"{HOOKS} AND list_contains({names}, {_a('mcp_server_name')})",
            _a("mcp_server_name"),
            "mcp_server",
        ),
    )
    missing = engine.run(MISSING_SQL, scope, params, timeout_s=TIMEOUT_S, name="agents.missing")
    out.missing_devices = sorted(str(r[0]) for r in missing.rows)[:50]
    out.sources = sorted(set(head.sources) | set(tools.sources))
    return out
