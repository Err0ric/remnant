"""Agent sessions from the hooks plugin (ADR-0026 row 11a): each Claude Code or Cowork
session in order, from start through prompts and tool calls to stop. Deterministic SQL
over the caller's events view, so a person sees only sessions from sources they may read.
What a session touched is metadata (tool, path, host, program, sizes); prompt and tool
content appear only when the source keeps content, and never here."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

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
WITH {_ONE_COPY}
SELECT {_a("session_id")} AS session_id,
       any_value(nullif(actor_user_name, '')) AS person,
       any_value(device_hostname) AS machine,
       min(coalesce(time, time_observed)) AS started,
       max(coalesce(time, time_observed)) AS last,
       count(*) FILTER (WHERE message = 'claude_hooks.user_prompt_submit') AS prompts,
       count(*) FILTER (WHERE message = 'claude_hooks.pre_tool_use') AS tool_calls,
       list(DISTINCT coalesce({_a("mcp_server_name")}, {_a("tool_name")}))
         FILTER (WHERE {_a("tool_name")} IS NOT NULL) AS tools,
       list(DISTINCT {_a("web_host")}) FILTER (WHERE {_a("web_host")} IS NOT NULL) AS hosts,
       -- Ended: a session end, or for the first plugin (no session end event) a stop.
       bool_or(message = 'claude_hooks.session_end')
         OR (NOT bool_or({_a("plugin_variant")} IS NOT NULL)
             AND bool_or(message = 'claude_hooks.stop')) AS stopped,
       count(*) FILTER (WHERE message = 'claude_hooks.post_tool_use_failure') AS failed
FROM hooks
WHERE {_a("session_id")} IS NOT NULL
GROUP BY 1
ORDER BY last DESC
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


def sessions(
    engine: QueryEngine, allowed: list[str] | None, now: datetime, days: int
) -> list[Session]:
    scope = QueryScope(allowed, now - timedelta(days=days), now)
    rows = engine.run(SESSIONS_SQL, scope, timeout_s=TIMEOUT_S).rows
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
        )
        for sid, person, machine, started, last, prompts, calls, tools, hosts, stopped, failed in (
            rows
        )
    ]


def timeline(
    engine: QueryEngine, allowed: list[str] | None, session_id: str, now: datetime, days: int
) -> Timeline:
    if not session_id or len(session_id) > 200:
        raise ParamInvalidError("Give a session id")
    scope = QueryScope(allowed, now - timedelta(days=days), now)
    rows = engine.run(STEPS_SQL, scope, {"session": session_id}, timeout_s=TIMEOUT_S).rows
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
