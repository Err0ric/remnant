"""AI agents and how they change (ADR-0020 rows 2 and 3).

An agent is something that acts with AI on someone's behalf:

- Claude Code for a person (telemetry, or the hooks plugin of ADR-0026), shown with the
  machine it last ran on;
- an MCP client on a machine, owned by the person whose profile holds it (MCP inventory);
- an Anthropic API key (usage reports).

Each agent has items it uses: tools, MCP servers, models. Over the last 30 days the
first 29 are its baseline. An item first used in the last 24 hours by an agent that was
active before is a change; so is an hour busier than three times its usual busiest hour
(when it usually does at least a few things an hour). A new agent is listed as new, not
as a change. Deterministic SQL over the caller's events view.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.ai.usage import MCP_EXPR, NO_MCP_NAMES, WHO_EXPR
from app.engine.duckdb import QueryEngine, QueryScope
from app.search.entities import CLIENT_NAMES

BASELINE_DAYS = 30
RECENT = timedelta(hours=24)
SPIKE_FACTOR = 3.0
SPIKE_MIN_USUAL = 5
TIMEOUT_S = 20.0

_CLIENT = (
    "coalesce(json_extract_string(unmapped, '$.client'),"
    " json_extract_string(unmapped, '$.attr.client'))"
)

HOOK_MCP = "json_extract_string(unmapped, '$.attr.mcp_server_name')"

# One row per (agent, item) use: kind, agent key, label, owner, machine, item kind, item.
ITEMS_SQL = f"""
WITH u AS (
  SELECT 'Claude Code' AS kind,
         'cc|' || coalesce({WHO_EXPR}, device_hostname, '?') AS agent,
         'Claude Code on ' || coalesce(device_hostname, 'unknown machine') AS label,
         {WHO_EXPR} AS owner, device_hostname AS machine,
         CASE WHEN {MCP_EXPR} IS NOT NULL THEN 'MCP server' ELSE 'Tool' END AS item_kind,
         coalesce({MCP_EXPR}, json_extract_string(unmapped, '$.attr.tool_name')) AS item,
         coalesce(time, time_observed) AS t
  FROM events WHERE template_id = 'claude_code_otel'
  UNION ALL
  SELECT 'Claude Code', 'cc|' || coalesce({WHO_EXPR}, device_hostname, '?'),
         'Claude Code on ' || coalesce(device_hostname, 'unknown machine'),
         {WHO_EXPR}, device_hostname, 'Model',
         json_extract_string(unmapped, '$.attr.model'), coalesce(time, time_observed)
  FROM events WHERE template_id = 'claude_code_otel'
    AND json_extract_string(unmapped, '$.attr.model') IS NOT NULL
  UNION ALL
  SELECT 'Claude Code', 'cc|' || coalesce({WHO_EXPR}, device_hostname, '?'),
         'Claude Code on ' || coalesce(device_hostname, 'unknown machine'),
         {WHO_EXPR}, device_hostname,
         CASE WHEN {HOOK_MCP} IS NOT NULL THEN 'MCP server' ELSE 'Tool' END,
         coalesce({HOOK_MCP}, json_extract_string(unmapped, '$.attr.tool_name')),
         coalesce(time, time_observed)
  FROM events WHERE template_id = 'claude_hooks' AND message = 'claude_hooks.pre_tool_use'
  UNION ALL
  SELECT 'MCP client',
         'mcp|' || coalesce(device_hostname, '?') || '|'
           || coalesce({_CLIENT}, 'MCP client'),
         coalesce({_CLIENT}, 'MCP client') || ' on '
           || coalesce(device_hostname, 'unknown machine'),
         {WHO_EXPR}, device_hostname, 'MCP server', message, coalesce(time, time_observed)
  FROM events WHERE template_id = 'mcp_inventory'
  UNION ALL
  SELECT 'API key', 'key|' || json_extract_string(unmapped, '$.api_key_id'),
         'API key ' || json_extract_string(unmapped, '$.api_key_id'),
         CAST(NULL AS VARCHAR), CAST(NULL AS VARCHAR), 'Model',
         json_extract_string(unmapped, '$.model'), coalesce(time, time_observed)
  FROM events WHERE template_id = 'anthropic_reports' AND message = 'anthropic.usage'
    AND json_extract_string(unmapped, '$.api_key_id') IS NOT NULL
)
SELECT kind, agent, any_value(label) AS label,
       list(DISTINCT owner) FILTER (WHERE owner IS NOT NULL) AS owners,
       max(machine) AS machine, min(t) AS first_seen, max(t) AS last_seen,
       count(*) FILTER (WHERE t >= $recent) AS recent,
       list(DISTINCT [item_kind, item]) FILTER (
         WHERE item IS NOT NULL AND lower(item) NOT IN {NO_MCP_NAMES}
       ) AS all_items,
       list(DISTINCT [item_kind, item]) FILTER (
         WHERE item IS NOT NULL AND t < $recent AND lower(item) NOT IN {NO_MCP_NAMES}
       ) AS old_items
FROM u GROUP BY 1, 2
ORDER BY last_seen DESC
LIMIT 2000"""  # noqa: S608  # fixed SQL text

HOURLY_SQL = """
WITH u AS (
  SELECT CASE template_id
           WHEN 'claude_code_otel' THEN 'cc|'
             || coalesce(nullif(actor_user_name, ''), device_hostname, '?')
           WHEN 'claude_hooks' THEN 'cc|'
             || coalesce(nullif(actor_user_name, ''), device_hostname, '?')
           WHEN 'anthropic_reports' THEN 'key|' || json_extract_string(unmapped, '$.api_key_id')
         END AS agent, date_trunc('hour', coalesce(time, time_observed)) AS h
  FROM events
  WHERE template_id IN ('claude_code_otel', 'claude_hooks')
     OR (template_id = 'anthropic_reports' AND message = 'anthropic.usage')
)
SELECT agent,
       max(n) FILTER (WHERE h < $recent) AS usual,
       max(n) FILTER (WHERE h >= $recent) AS peak
FROM (SELECT agent, h, count(*) AS n FROM u WHERE agent IS NOT NULL GROUP BY 1, 2)
GROUP BY 1
LIMIT 2000"""


@dataclass(slots=True)
class AgentStatus:
    kind: str
    agent: str
    label: str
    owners: list[str]
    machine: str | None
    first_seen: str
    last_seen: str
    events_24h: int
    state: str  # new | changed | usual
    new_items: list[dict[str, str]] = field(default_factory=list)
    usual_peak: int | None = None
    recent_peak: int | None = None


def _iso(v: Any) -> str:
    return v.isoformat() if isinstance(v, datetime) else str(v)


def agents(engine: QueryEngine, allowed: list[str] | None, now: datetime) -> list[AgentStatus]:
    now = now.astimezone(UTC)
    recent = now - RECENT
    scope = QueryScope(allowed, now - timedelta(days=BASELINE_DAYS), now)
    params = {"recent": recent}
    rows = engine.run(ITEMS_SQL, scope, params, timeout_s=TIMEOUT_S).rows
    hourly = {
        str(a): (int(u) if u is not None else None, int(p) if p is not None else None)
        for a, u, p in engine.run(HOURLY_SQL, scope, params, timeout_s=TIMEOUT_S).rows
    }
    out = []
    for kind, agent, label, owners, machine, first, last, n24, all_items, old_items in rows:
        if kind == "Claude Code":  # one per person; machines come and go
            label = f"Claude Code on {machine or 'unknown machine'}"
        elif kind == "MCP client":
            client = str(agent).split("|", 2)[-1]
            name = CLIENT_NAMES.get(client, client)
            label = f"{name} MCP setup on {machine or 'unknown machine'}"
        first_t = first if isinstance(first, datetime) else datetime.fromisoformat(str(first))
        is_new = first_t.astimezone(UTC) >= recent
        old = {(str(k), str(v)) for k, v in (old_items or [])}
        fresh = [] if is_new else sorted({(str(k), str(v)) for k, v in (all_items or [])} - old)
        usual, peak = hourly.get(str(agent), (None, None))
        spike = (
            not is_new
            and usual is not None
            and peak is not None
            and usual >= SPIKE_MIN_USUAL
            and peak > SPIKE_FACTOR * usual
        )
        state = "new" if is_new else "changed" if fresh or spike else "usual"
        out.append(
            AgentStatus(
                kind=str(kind),
                agent=str(agent),
                label=str(label),
                owners=sorted(str(o) for o in (owners or [])),
                machine=str(machine) if machine else None,
                first_seen=_iso(first),
                last_seen=_iso(last),
                events_24h=int(n24 or 0),
                state=state,
                new_items=[{"kind": k, "name": v} for k, v in fresh],
                usual_peak=usual,
                recent_peak=peak if spike else None,
            )
        )
    order = {"changed": 0, "new": 1, "usual": 2}
    return sorted(out, key=lambda a: (order[a.state], a.label))
