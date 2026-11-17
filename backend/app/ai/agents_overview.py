"""Agents > Overview and Tools (ADR-0038 section 6), on the caller's own view. The numbers
count every agent source (the hooks plugin, Claude Code telemetry, the MCP inventory;
owner, 2026-11-08); the Tools table and late or silent devices are the plugin's. Sessions,
people, tool calls, failed calls, MCP servers not approved that were used, devices whose
records arrive late or stopped, and one row per tool with its status, people, devices,
calls, failures, and first and last use. Deterministic SQL; no model is called. Every
number carries its Search query (ADR-0039)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.ai.catalog import Catalog
from app.ai.internal_tools import counted
from app.ai.sessions import _ONE_COPY, _a
from app.ai.test_records import HOOKS as HOOKS_USE
from app.ai.usage import McpUse
from app.engine.duckdb import QueryEngine, QueryScope
from app.search import drill
from app.search.dashboard import FIRST_EVENT_SQL, History, Kpi, _history, _utc, settle

TIMEOUT_S = 20.0
LATE_S = 3600  # delivered an hour or more after it happened (the plugin's offline queue)
MAX_TOOLS = 200

_TS = "coalesce(time, time_observed)"
_TOOL = f"coalesce({_a('mcp_server_name')}, {_a('tool_name')})"
# Claude Code's own bookkeeping is not a tool call (D186).
_REAL = counted(_a("tool_name"))
_CALL = f"message = 'claude_hooks.pre_tool_use' AND {_REAL}"
_FAIL = f"message = 'claude_hooks.post_tool_use_failure' AND {_REAL}"

# Every agent source the page is about (owner, 2026-11-08): the hooks plugin, Claude Code
# telemetry, and the MCP inventory (people only). As on AI usage, a session telemetry saw
# takes its calls from telemetry, so a session both report is counted once.
TELEMETRY = "template_id = 'claude_code_otel'"
INVENTORY = "template_id = 'mcp_inventory'"
_TEL_CALL = "message = 'claude_code.tool_result'"
_TEL_FAIL = f"{_TEL_CALL} AND {_a('success')} = 'false'"
OVERVIEW_SQL = f"""
WITH {_ONE_COPY},
tel AS (SELECT * FROM events WHERE {TELEMETRY}),
seen AS (SELECT DISTINCT {_a("session_id")} AS sid FROM tel WHERE {_a("session_id")} IS NOT NULL),
a AS (
  SELECT {_a("session_id")} AS sid, nullif(actor_user_name, '') AS who, {_TS} AS ts,
         {_TEL_CALL} AS call, coalesce({_TEL_FAIL}, false) AS fail, false AS hook,
         false AS step
  FROM tel
  UNION ALL
  SELECT {_a("session_id")}, nullif(actor_user_name, ''), {_TS},
         {_CALL} AND coalesce({_a("session_id")} NOT IN (SELECT sid FROM seen), true),
         {_FAIL} AND coalesce({_a("session_id")} NOT IN (SELECT sid FROM seen), true),
         true,
         -- A step the Sessions list counts: a prompt or a real tool call (D186).
         coalesce(message = 'claude_hooks.user_prompt_submit' OR {_CALL}, false)
  FROM hooks
  UNION ALL
  SELECT NULL, nullif(actor_user_name, ''), {_TS}, false, false, false, false
  FROM events WHERE {INVENTORY}
)
SELECT count(DISTINCT sid) FILTER (WHERE ts >= $start),
       count(DISTINCT sid) FILTER (WHERE ts < $start),
       count(DISTINCT who) FILTER (WHERE ts >= $start),
       count(DISTINCT who) FILTER (WHERE ts < $start),
       count(*) FILTER (WHERE ts >= $start AND call),
       count(*) FILTER (WHERE ts < $start AND call),
       count(*) FILTER (WHERE ts >= $start AND fail),
       count(*) FILTER (WHERE ts < $start AND fail),
       (SELECT count(DISTINCT device_hostname) FROM hooks
        WHERE {_TS} >= $start AND epoch(time_observed) - epoch({_TS}) >= {LATE_S}),
       -- The window's sessions the hooks plugin recorded, and those with a step: the
       -- Sessions list's rows and its hidden empty ones (fix list, PR 639 item 3).
       count(DISTINCT sid) FILTER (WHERE ts >= $start AND hook),
       count(DISTINCT sid) FILTER (WHERE ts >= $start AND hook AND step)
FROM a"""  # noqa: S608  # fixed SQL text

# An MCP server's name in a telemetry or hook record, for the not-approved drill.
_MCP_NAME = f"coalesce({_a('mcp_server_name')}, json_extract_string(unmapped, '$.mcp_server_name'))"

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
WHERE {_TS} >= $start AND {_a("tool_name")} IS NOT NULL AND {_REAL}
GROUP BY 1, 2
ORDER BY calls DESC, tool
LIMIT {MAX_TOOLS}"""  # noqa: S608  # fixed SQL text

HOOKS = HOOKS_USE
ANY_AGENT = f"({HOOKS} OR {TELEMETRY} OR {INVENTORY})"
_NOT_SEEN = (
    f"coalesce({_a('session_id')} NOT IN (SELECT {_a('session_id')} FROM events"  # noqa: S608  # fixed SQL text
    f" WHERE {TELEMETRY} AND {_a('session_id')} IS NOT NULL), true)"
)
# The rows behind calls and failures: telemetry's, and the plugin's for sessions telemetry
# did not see, as OVERVIEW_SQL counts them.
CALL_ROWS = f"(({TELEMETRY} AND {_TEL_CALL}) OR ({HOOKS} AND {_CALL} AND {_NOT_SEEN}))"
FAIL_ROWS = f"(({TELEMETRY} AND {_TEL_FAIL}) OR ({HOOKS} AND {_FAIL} AND {_NOT_SEEN}))"
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
class SessionParts:
    """The Sessions tile in parts that add up to it, for the Sessions card's line."""

    listed: int = 0  # hook-plugin sessions with a prompt or a tool call: the list's rows
    empty: int = 0  # hook-plugin sessions with neither: hidden by default
    telemetry_only: int = 0  # sessions only Claude Code telemetry reported


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
    # MCP servers seen in the window that nobody has reviewed, by the names and rules the
    # not-approved count uses: what Agents' Needs attention says (fix list item 15).
    mcp_unreviewed: int = 0
    session_parts: SessionParts = field(default_factory=SessionParts)
    missing_devices: list[str] = field(default_factory=list)
    tools: list[ToolRow] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    return v.isoformat() if isinstance(v, datetime) else str(v)


def overview(
    engine: QueryEngine,
    catalog: Catalog,
    telemetry: list[str],
    now: datetime,
    days: int,
    mcp_rows: list[McpUse] | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> AgentsOverview:
    """`days` back from now, or with `start` exactly the window the page chose (`end`
    or now), compared with the window of the same length before it. `mcp_rows` is the MCP
    servers table's own rows for that window (`Usage.mcp`): the not-approved and
    unreviewed counts are its rows by review state, never a second list of names."""
    now = (end or now).astimezone(UTC)
    if start is not None:
        start = start.astimezone(UTC)
        days = max(1, math.ceil((now - start) / timedelta(days=1)))
    else:
        start = now - timedelta(days=days)
    before = start - (now - start)
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
    firsts = engine.run(FIRST_EVENT_SQL, scope, timeout_s=TIMEOUT_S, name="agents.first", page=True)
    first = {str(s): t for s, at in firsts.rows if (t := _utc(at)) is not None}
    out.history = _history(first, telemetry, start, before)
    head = engine.run(
        OVERVIEW_SQL, scope, params, timeout_s=TIMEOUT_S, name="agents.overview", page=True
    )
    s, s_b, p, p_b, c, c_b, f, f_b, late, hooked, stepped = (head.rows or [[0] * 11])[0]
    # Parts of the Sessions tile that add up to it: listed (a step), empty (hidden by
    # default), and seen only in telemetry (no hook records in the window).
    out.session_parts = SessionParts(
        listed=int(stepped), empty=int(hooked) - int(stepped), telemetry_only=int(s) - int(hooked)
    )
    sessions = f"({HOOKS} OR {TELEMETRY}) AND {_a('session_id')} IS NOT NULL"
    out.sessions = Kpi(
        int(s), int(s_b), drill=drill.grouped(sessions, _a("session_id"), "session_id")
    )
    out.people = Kpi(
        int(p),
        int(p_b),
        drill=drill.grouped(f"{ANY_AGENT} AND actor_user_name <> ''", "actor_user_name", "person"),
    )
    out.calls = Kpi(int(c), int(c_b), drill=drill.events(CALL_ROWS, COLUMNS))
    out.failed = Kpi(int(f), int(f_b), drill=drill.events(FAIL_ROWS, COLUMNS))
    out.late_devices = Kpi(
        int(late),
        None,
        drill=drill.grouped(
            f"{HOOKS} AND epoch(time_observed) - epoch({_TS}) >= {LATE_S}",
            "device_hostname",
            "device",
        ),
    )
    tools = engine.run(
        TOOLS_SQL, scope, params, timeout_s=TIMEOUT_S, name="agents.tools", page=True
    )
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
    bad = sorted(m.name for m in mcp_rows or [] if m.status == "not_approved")
    out.mcp_unreviewed = sum(1 for m in mcp_rows or [] if m.status == "unreviewed")
    names = drill.lits(bad) if bad else "['']"
    server = f"coalesce({_MCP_NAME}, CASE WHEN {INVENTORY} THEN message END)"
    out.mcp_not_approved = Kpi(
        len(bad),
        None,
        drill=drill.grouped(
            f"{ANY_AGENT} AND list_contains({names}, {server})", server, "mcp_server"
        ),
    )
    missing = engine.run(
        MISSING_SQL, scope, params, timeout_s=TIMEOUT_S, name="agents.missing", page=True
    )
    out.missing_devices = sorted(str(r[0]) for r in missing.rows)[:50]
    out.sources = sorted(set(head.sources) | set(tools.sources))
    # #638's one rule, for the window actually read (the clamped start and the read end).
    settle(out, start, before, now)
    return out
