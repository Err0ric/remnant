"""One agent session in numbers (BACKLOG P1, the session detail's KPI row): requests,
tool calls with how many failed or got no result, tokens when Claude Code telemetry
reported them, files touched and how many were written outside the session's folder, the
inputs of the session's flags, and a count per step type. Counted on the server over the
whole session, never over the steps list (which stops at MAX_STEPS). Metadata only.

Two guarded queries on the caller's view: the hook records of the session over the asked
days, then the token metrics of the session over its own window. Each read of `events`
pins `template_id` at the top level of its WHERE, so the engine reads only the sources
that can hold those templates (see `app.ai.agents`)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.ai.internal_tools import counted
from app.ai.person_ai import WRITE_TOOLS, outside
from app.ai.sessions import (
    MAX_STEPS,
    STEP_TYPES,
    TIMEOUT_S,
    _a,
    _iso,
    _state,
    has,
    one_copy,
    step_type,
)
from app.ai.test_records import NOT_TEST
from app.core.errors import NotFoundError, ParamInvalidError
from app.engine.duckdb import QueryEngine, QueryScope
from app.search import drill

# Token metrics are sent on an interval, so the last ones can arrive after the last hook
# record: the token query reads this long past the session's last record.
TOKEN_SLACK = timedelta(minutes=15)

_WRITES = "(" + ", ".join(f"'{t}'" for t in sorted(WRITE_TOOLS)) + ")"
_CALL = "message = 'claude_hooks.pre_tool_use'"
_FAIL = "message = 'claude_hooks.post_tool_use_failure'"

SUMMARY_SQL = f"""
WITH {one_copy("one", f"{_a('session_id')} = $session")},
s AS (
  SELECT coalesce(time, time_observed) AS t, message, event_id,
         {_a("tool_name")} AS tool, {_a("mcp_server_name")} AS mcp, {_a("path")} AS path,
         {_a("web_host")} AS host, {_a("cwd")} AS cwd, {_a("plugin_variant")} AS variant,
         nullif(actor_user_name, '') AS person, device_hostname AS machine,
         lower(nullif({_a("claude_account_email")}, '')) AS account
  FROM one
),
-- When each MCP server was first used anywhere in the range, for "New MCP server".
mf AS (
  SELECT {_a("mcp_server_name")} AS mcp, min(coalesce(time, time_observed)) AS first
  FROM events
  WHERE template_id = 'claude_hooks' AND {NOT_TEST} AND {_a("mcp_server_name")} IS NOT NULL
  GROUP BY 1
),
-- The session's folder as known at each record: the first one reported up to it, as the
-- person page's "Writes outside the session's working folder" reads it.
w AS (
  SELECT message, tool, path,
         first_value(cwd IGNORE NULLS) OVER (
           ORDER BY t, event_id ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cwd
  FROM s
),
k AS (
  SELECT coalesce(message, '') || '|' || ({has("mcp")})::VARCHAR || '|'
           || ({has("host")})::VARCHAR || '|' || ({has("path")})::VARCHAR || '|'
           || ({counted("tool")})::VARCHAR AS kind,
         count(*) AS n
  FROM s GROUP BY 1
),
h AS (
  SELECT min(t) AS started, max(t) AS last, count(*) AS steps,
         any_value(person) AS person, any_value(machine) AS machine,
         any_value(account) AS account,
         count(*) FILTER (WHERE message = 'claude_hooks.user_prompt_submit') AS prompts,
         count(*) FILTER (WHERE {_CALL} AND {counted("tool")}) AS calls,
         count(*) FILTER (WHERE {_FAIL} AND {counted("tool")}) AS failed,
         count(*) FILTER (
           WHERE message IN ('claude_hooks.post_tool_use', 'claude_hooks.post_tool_use_failure')
             AND {counted("tool")}
         ) AS results,
         count(DISTINCT path) FILTER (WHERE path IS NOT NULL) AS files,
         bool_or(message = 'claude_hooks.session_end')
           OR (NOT bool_or(variant IS NOT NULL) AND bool_or(message = 'claude_hooks.stop'))
           AS stopped,
         list(DISTINCT mcp) FILTER (WHERE mcp IS NOT NULL) AS mcps
  FROM s
)
SELECT h.started, h.last, h.steps, h.person, h.machine, h.account, h.prompts, h.calls,
       h.failed, greatest(h.calls - h.results, 0), h.files, h.stopped,
       (SELECT list(mf.mcp ORDER BY mf.mcp) FROM mf
        WHERE list_contains(h.mcps, mf.mcp) AND mf.first >= h.started),
       (SELECT list(kind ORDER BY kind) FROM k), (SELECT list(n ORDER BY kind) FROM k),
       (SELECT list(DISTINCT [path, cwd]) FROM w
        WHERE {_CALL} AND path IS NOT NULL AND lower(tool) IN {_WRITES})
FROM h
WHERE h.steps > 0"""  # noqa: S608  # fixed SQL text; the session id is a parameter

# Claude Code telemetry's token metric for the session: output, and everything else (input
# and cache tokens), so the two add up to what AI usage counts as tokens.
TOKENS_SQL = f"""
SELECT count(*), sum(v) FILTER (WHERE kind = 'output'),
       sum(v) FILTER (WHERE kind IS DISTINCT FROM 'output')
FROM (
  SELECT TRY_CAST(json_extract_string(unmapped, '$.value') AS DOUBLE) AS v, {_a("type")} AS kind
  FROM events
  WHERE template_id = 'claude_code_otel' AND message = 'claude_code.token.usage'
    AND {_a("session_id")} = $session
)
WHERE isfinite(v) AND v >= 0 AND v < 1e15"""  # noqa: S608  # fixed SQL text


@dataclass(slots=True)
class SessionSummary:
    session_id: str
    person: str | None
    machine: str | None
    account: str | None
    started: str
    last: str
    length_s: int
    state: str  # ended | idle | open, as on the list
    prompts: int  # requests
    tool_calls: int  # Claude Code bookkeeping left out (D186)
    failed: int
    unanswered: int  # tool calls with no result: blocked, interrupted, or still running
    tokens_in: int | None  # None: no token metrics arrived for this session
    tokens_out: int | None
    files: int  # distinct paths touched
    files_outside: int  # distinct paths written outside the session's folder
    new_mcp: list[str] = field(default_factory=list)
    types: dict[str, int] = field(default_factory=dict)  # steps per step_type()
    steps: int = 0  # every step, also those past the steps list's limit
    steps_cut: bool = False  # the steps list stops at MAX_STEPS
    # The session's hook records for Logs (Show events in Logs), with the window's bounds
    # as placeholders, as the person timeline's session rows (app SQL is server-built).
    sql: str = ""


def _when(v: Any) -> datetime:
    t = v if isinstance(v, datetime) else datetime.fromisoformat(str(v))
    return t.replace(tzinfo=UTC) if t.tzinfo is None else t.astimezone(UTC)


def _types(kinds: list[Any], counts: list[Any]) -> dict[str, int]:
    out: Counter[str] = Counter({t: 0 for t in STEP_TYPES})
    for kind, n in zip(kinds or [], counts or [], strict=True):
        # The query says only whether each field is there, which is all step_type reads.
        message, *has, real = str(kind).split("|")
        mcp, host, path = ("set" if h == "true" else None for h in has)
        out[step_type(message, mcp, host, path, real == "true")] += int(n)
    return dict(out)


def summary(
    engine: QueryEngine,
    allowed: list[str] | None,
    session_id: str,
    now: datetime,
    days: int,
    idle_minutes: int = 120,
) -> SessionSummary:
    if not session_id or len(session_id) > 200:
        raise ParamInvalidError("Give a session id")
    now = now.astimezone(UTC)
    params = {"session": session_id}
    res = engine.run(
        SUMMARY_SQL, QueryScope(allowed, now - timedelta(days=days), now), params,
        timeout_s=TIMEOUT_S, name="ai.session_summary", page=True,
    )  # fmt: skip
    if not res.rows:
        raise NotFoundError("No such session in the sources you can read")
    (
        started, last, steps, person, machine, account, prompts, calls, failed, unanswered,
        files, stopped, new_mcp, kinds, counts, writes,
    ) = res.rows[0]  # fmt: skip
    first, end = _when(started), _when(last)
    tokens = engine.run(
        TOKENS_SQL, QueryScope(allowed, first, min(now, end + TOKEN_SLACK)), params,
        timeout_s=TIMEOUT_S, name="ai.session_tokens", page=True,
    )  # fmt: skip
    metered, out_t, in_t = tokens.rows[0] if tokens.rows else (0, None, None)
    away = {str(p) for p, cwd in (writes or []) if outside(str(p), cwd)}
    return SessionSummary(
        session_id=session_id,
        person=person,
        machine=machine,
        account=str(account) if account else None,
        started=_iso(started),
        last=_iso(last),
        length_s=max(0, int((end - first).total_seconds())),
        state=_state(bool(stopped), last, now, idle_minutes),
        prompts=int(prompts or 0),
        tool_calls=int(calls or 0),
        failed=int(failed or 0),
        unanswered=int(unanswered or 0),
        tokens_in=int(in_t or 0) if metered else None,
        tokens_out=int(out_t or 0) if metered else None,
        files=int(files or 0),
        files_outside=len(away),
        new_mcp=[str(m) for m in (new_mcp or [])],
        types=_types(kinds, counts),
        steps=int(steps or 0),
        steps_cut=int(steps or 0) > MAX_STEPS,
        sql=drill.events(
            f"template_id = 'claude_hooks' AND {_a('session_id')} = {drill.lit(session_id)}"
        ),
    )
