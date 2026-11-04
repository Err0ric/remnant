"""Agent sessions from the hooks plugin (ADR-0026 row 11a): each Claude Code or Cowork
session in order, from start through prompts and tool calls to stop. Deterministic SQL
over the caller's events view, so a person sees only sessions from sources they may read.
What a session touched is metadata (tool, path, host, program, sizes); prompt and tool
content appear only when the source keeps content, and never here."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.ai.internal_tools import counted
from app.core.errors import NotFoundError, ParamInvalidError
from app.engine.duckdb import QueryEngine, QueryScope

TIMEOUT_S = 20.0
MAX_SESSIONS = 100
MAX_STEPS = 2000


def _a(key: str) -> str:
    return f"json_extract_string(unmapped, '$.attr.{key}')"


# A queued batch can be sent twice when an answer is lost; the install id and sequence
# number name a record, so the copy is left out (ADR-0026 offline queue).
_ONE_COPY = f"""hooks AS (
  SELECT * FROM events
  WHERE template_id = 'claude_hooks'
  QUALIFY {_a("seq")} IS NULL OR row_number() OVER (
    PARTITION BY {_a("install_id")}, {_a("seq")} ORDER BY time_observed, event_id) = 1
)"""  # noqa: S608  # fixed SQL text

SESSIONS_SQL = f"""
WITH {_ONE_COPY},
-- Tool calls per session and tool, for the top three (D188).
tc AS (
  SELECT {_a("session_id")} AS sid,
         coalesce({_a("mcp_server_name")}, {_a("tool_name")}) AS tool, count(*) AS n
  FROM hooks
  WHERE message = 'claude_hooks.pre_tool_use' AND {_a("tool_name")} IS NOT NULL
    AND {counted(_a("tool_name"))}
  GROUP BY 1, 2
),
top AS (SELECT sid, list(tool ORDER BY n DESC, tool)[1:3] AS top FROM tc GROUP BY 1),
-- When each MCP server was first used anywhere in the range: a session that used one
-- for the first time has a new MCP server.
mfirst AS (
  SELECT {_a("mcp_server_name")} AS mcp, min(coalesce(time, time_observed)) AS first
  FROM hooks WHERE {_a("mcp_server_name")} IS NOT NULL GROUP BY 1
),
s AS (
SELECT {_a("session_id")} AS session_id,
       any_value(nullif(actor_user_name, '')) AS person,
       any_value(device_hostname) AS machine,
       min(coalesce(time, time_observed)) AS started,
       max(coalesce(time, time_observed)) AS last,
       count(*) FILTER (WHERE message = 'claude_hooks.user_prompt_submit') AS prompts,
       count(*) FILTER (
         WHERE message = 'claude_hooks.pre_tool_use' AND {counted(_a("tool_name"))}
       ) AS tool_calls,
       list(DISTINCT coalesce({_a("mcp_server_name")}, {_a("tool_name")}))
         FILTER (WHERE {_a("tool_name")} IS NOT NULL AND {counted(_a("tool_name"))}) AS tools,
       list(DISTINCT {_a("web_host")}) FILTER (WHERE {_a("web_host")} IS NOT NULL) AS hosts,
       -- Ended: a session end, or for the first plugin (no session end event) a stop.
       bool_or(message = 'claude_hooks.session_end')
         OR (NOT bool_or({_a("plugin_variant")} IS NOT NULL)
             AND bool_or(message = 'claude_hooks.stop')) AS stopped,
       count(*) FILTER (
         WHERE message = 'claude_hooks.post_tool_use_failure' AND {counted(_a("tool_name"))}
       ) AS failed,
       count(*) FILTER (
         WHERE message IN ('claude_hooks.post_tool_use', 'claude_hooks.post_tool_use_failure')
           AND {counted(_a("tool_name"))}
       ) AS results,
       count(DISTINCT {_a("path")}) FILTER (WHERE {_a("path")} IS NOT NULL) AS files,
       list(DISTINCT {_a("mcp_server_name")})
         FILTER (WHERE {_a("mcp_server_name")} IS NOT NULL) AS mcps,
       any_value(lower(nullif({_a("claude_account_email")}, ''))) AS account
FROM hooks
WHERE {_a("session_id")} IS NOT NULL
GROUP BY 1
)
SELECT s.session_id, s.person, s.machine, s.started, s.last, s.prompts, s.tool_calls,
       s.tools, s.hosts, s.stopped, s.failed, coalesce(top.top, []) AS top,
       s.files, greatest(s.tool_calls - s.results, 0) AS unanswered,
       (SELECT list(m.mcp ORDER BY m.mcp) FROM mfirst m
        WHERE list_contains(s.mcps, m.mcp) AND m.first >= s.started) AS new_mcp,
       s.account
FROM s LEFT JOIN top ON top.sid = s.session_id
ORDER BY s.last DESC
LIMIT {MAX_SESSIONS}"""  # noqa: S608  # fixed SQL text

STEPS_SQL = f"""
WITH {_ONE_COPY}
SELECT coalesce(time, time_observed) AS t, message, {_a("role")}, {_a("tool_name")},
       {_a("mcp_server_name")}, {_a("mcp_tool_name")}, {_a("path")}, {_a("web_host")},
       {_a("program")}, TRY_CAST({_a("prompt_chars")} AS BIGINT),
       TRY_CAST({_a("tool_input_chars")} AS BIGINT),
       TRY_CAST({_a("tool_response_chars")} AS BIGINT), event_id,
       nullif(actor_user_name, ''), device_hostname,
       epoch(time_observed) - epoch(coalesce(time, time_observed)) AS late_s
FROM hooks
WHERE {_a("session_id")} = $session
ORDER BY t, event_id
LIMIT {MAX_STEPS}"""  # noqa: S608  # fixed SQL text; the session id is a parameter


@dataclass(slots=True)
class Session:
    session_id: str
    person: str | None
    machine: str | None
    started: str
    last: str
    prompts: int
    tool_calls: int
    tools: list[str] = field(default_factory=list)
    hosts: list[str] = field(default_factory=list)
    stopped: bool = False  # ended
    failed: int = 0  # tool calls that failed
    # ended (a stop record), idle (no record for the idle time and no stop: "Ended (no end
    # event)"), or open
    state: str = "open"
    # For the list (owner, 2026-11-03; D188): the three most used tools, files touched,
    # tool calls with no result, MCP servers first used in this session, and the Claude
    # account the plugin reported.
    top_tools: list[str] = field(default_factory=list)
    files: int = 0
    unanswered: int = 0
    new_mcp: list[str] = field(default_factory=list)
    account: str | None = None


@dataclass(slots=True)
class Step:
    time: str
    event: str
    role: str | None
    tool: str | None
    mcp_server: str | None
    mcp_tool: str | None
    path: str | None
    web_host: str | None
    program: str | None
    prompt_chars: int | None
    input_chars: int | None
    output_chars: int | None
    event_id: str
    late_s: int | None = None  # delivered this long after it happened, when over 5 minutes


@dataclass(slots=True)
class Timeline:
    session_id: str
    person: str | None
    machine: str | None
    steps: list[Step]


def _iso(v: Any) -> str:
    return v.astimezone(UTC).isoformat() if isinstance(v, datetime) else str(v)


def _state(stopped: bool, last: Any, now: datetime, idle_minutes: int) -> str:
    if stopped:
        return "ended"
    seen = last if isinstance(last, datetime) else None
    if seen is None and last is not None:
        try:
            seen = datetime.fromisoformat(str(last))
        except ValueError:
            seen = None
    if seen is not None and seen.tzinfo is None:
        seen = seen.replace(tzinfo=UTC)
    if seen is not None and now - seen >= timedelta(minutes=idle_minutes):
        return "idle"
    return "open"


def sessions(
    engine: QueryEngine,
    allowed: list[str] | None,
    now: datetime,
    days: int,
    idle_minutes: int = 120,
) -> list[Session]:
    scope = QueryScope(allowed, now - timedelta(days=days), now)
    rows = engine.run(SESSIONS_SQL, scope, timeout_s=TIMEOUT_S, page=True).rows
    return [
        Session(
            str(sid),
            person,
            machine,
            _iso(started),
            _iso(last),
            int(prompts or 0),
            int(calls or 0),
            sorted(str(t) for t in (tools or [])),
            sorted(str(h) for h in (hosts or [])),
            bool(stopped),
            int(failed or 0),
            _state(bool(stopped), last, now, idle_minutes),
            [str(t) for t in (top or [])],
            int(files or 0),
            int(unanswered or 0),
            [str(m) for m in (new_mcp or [])],
            str(account) if account else None,
        )
        for (
            sid, person, machine, started, last, prompts, calls, tools, hosts, stopped, failed,
            top, files, unanswered, new_mcp, account,
        ) in rows
    ]  # fmt: skip


def timeline(
    engine: QueryEngine, allowed: list[str] | None, session_id: str, now: datetime, days: int
) -> Timeline:
    if not session_id or len(session_id) > 200:
        raise ParamInvalidError("Give a session id")
    scope = QueryScope(allowed, now - timedelta(days=days), now)
    rows = engine.run(
        STEPS_SQL, scope, {"session": session_id}, timeout_s=TIMEOUT_S, page=True
    ).rows
    if not rows:
        raise NotFoundError("No such session in the sources you can read")
    steps = [
        Step(
            _iso(t),
            str(msg).removeprefix("claude_hooks."),
            role,
            tool,
            srv,
            mtool,
            path,
            host,
            prog,
            pc,
            ic,
            oc,
            str(eid),
            int(late) if late is not None and late > 300 else None,
        )
        for t, msg, role, tool, srv, mtool, path, host, prog, pc, ic, oc, eid, _, _, late in rows
    ]
    person = next((r[13] for r in rows if r[13]), None)
    machine = next((r[14] for r in rows if r[14]), None)
    return Timeline(session_id, person, machine, steps)
