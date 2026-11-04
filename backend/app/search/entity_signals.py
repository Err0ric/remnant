"""The signals behind the People and devices ranking besides rule matches (owner,
2026-11-03; D195): every user, source IP, and host seen in the range with its event count,
failed sign-ins, risky inbox rules and app consents (Microsoft 365), AI watch flags, attack
hits from outside, and (in `alert_names`) the alerts about it.

Every count is SQL over the caller's own `events` view, or alert items on sources the
caller may read, so nobody learns of activity on a source they cannot read. Nothing here
is a verdict: each part is shown in its own column and the score is their weighted sum.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from app.ai.internal_tools import counted
from app.engine.duckdb import QueryEngine, QueryScope
from app.meta.db import MetaDB
from app.search.dashboard import EXTERNAL_FAILURE
from app.search.identity import IdentityMap
from app.search.mail_rules import risky_by_person_sql

TIMEOUT_S = 20.0
SEEN_PER_KIND = 1000  # the busiest entities per kind; rule-matched ones are added anyway
NEW_MCP_LOOKBACK = timedelta(days=30)
MAX_ALERTS = 2000

AI_FLAGS = ("personal_account", "unreviewed_service", "new_mcp", "blocked_calls")
AI_FLAG_LABEL = {
    "personal_account": "personal Claude account",
    "unreviewed_service": "unreviewed AI service",
    "new_mcp": "new MCP server",
    "blocked_calls": "blocked or failed tool calls",
}


def _a(key: str) -> str:
    return f"json_extract_string(unmapped, '$.attr.{key}')"


_EMAIL = f"lower(nullif(trim({_a('claude_account_email')}), ''))"

# One row per entity: events, failed sign-ins, app consents (each consent once, D150),
# attack hits from outside, blocked tool calls, and whether a personal Claude account ran.
SEEN_SQL = f"""
WITH e AS (
  SELECT actor_user_name AS u, src_endpoint_ip AS ip, device_hostname AS h,
         class_uid = 3002 AND status_id = 2 AS fail,
         CASE WHEN message ILIKE 'Consent to application%'
              THEN coalesce(metadata_correlation_uid, CAST(event_id AS VARCHAR)) END AS consent,
         coalesce({EXTERNAL_FAILURE}, false) AS attack,
         template_id = 'claude_hooks' AND message = 'claude_hooks.post_tool_use_failure'
           AND {counted(_a("tool_name"))} AS blocked,
         template_id = 'claude_hooks' AND len($org) > 0 AND {_EMAIL} IS NOT NULL
           AND NOT list_contains($org, split_part({_EMAIL}, '@', 2)) AS personal
  FROM events
),
x AS (
  SELECT 'user' AS kind, u AS value, fail, consent, false AS attack, blocked, personal
  FROM e WHERE nullif(u, '') IS NOT NULL
  UNION ALL
  SELECT 'ip', ip, fail, NULL, attack, false, false FROM e WHERE nullif(ip, '') IS NOT NULL
  UNION ALL
  SELECT 'host', h, fail, NULL, attack, blocked, personal FROM e WHERE nullif(h, '') IS NOT NULL
)
SELECT kind, value, count(*) AS events,
       count(*) FILTER (WHERE fail) AS failed,
       count(DISTINCT consent) AS consents,
       count(*) FILTER (WHERE attack) AS attacks,
       count(*) FILTER (WHERE blocked) AS blocked,
       bool_or(personal) AS personal
FROM x GROUP BY 1, 2
QUALIFY row_number() OVER (PARTITION BY kind ORDER BY count(*) DESC, value) <= {SEEN_PER_KIND}
"""  # noqa: S608  # fixed SQL text; the org domains are a parameter

# MCP servers first used (over the lookback) inside the range, with who used them there.
NEW_MCP_SQL = f"""
WITH m AS (
  SELECT {_a("mcp_server_name")} AS mcp, actor_user_name AS u, device_hostname AS h,
         coalesce(time, time_observed) AS t
  FROM events
  WHERE template_id = 'claude_hooks' AND {_a("mcp_server_name")} IS NOT NULL
),
f AS (SELECT mcp, min(t) AS first FROM m GROUP BY 1)
SELECT DISTINCT m.u, m.h FROM m JOIN f USING (mcp) WHERE f.first >= $start AND m.t >= $start
"""  # noqa: S608  # fixed SQL text


@dataclass(slots=True)
class Signals:
    events: int = 0
    failed_signins: int = 0
    mail_rules: int = 0
    consents: int = 0
    attacks: int = 0
    ai_flags: list[str] = field(default_factory=list)

    def add(self, other: Signals) -> None:
        self.events += other.events
        self.failed_signins += other.failed_signins
        self.mail_rules += other.mail_rules
        self.consents += other.consents
        self.attacks += other.attacks
        self.ai_flags = [f for f in AI_FLAGS if f in self.ai_flags or f in other.ai_flags]


Key = tuple[str, str]


def _flag(out: dict[Key, Signals], key: Key, flag: str) -> None:
    s = out.setdefault(key, Signals())
    if flag not in s.ai_flags:
        s.ai_flags = [f for f in AI_FLAGS if f in s.ai_flags or f == flag]


def collect(
    engine: QueryEngine,
    meta: MetaDB,
    allowed: list[str] | None,
    scope: QueryScope,
    ident: IdentityMap,
    usage: Any = None,
) -> tuple[dict[Key, Signals], list[str]]:
    """Signals per (kind, value), and the sources read."""
    out: dict[Key, Signals] = {}
    seen = engine.run(
        SEEN_SQL, scope, {"org": [d.lower() for d in ident.domains]}, timeout_s=TIMEOUT_S, page=True
    )
    for kind, value, events, failed, consents, attacks, blocked, personal in seen.rows:
        s = out.setdefault((str(kind), str(value)), Signals())
        s.events, s.failed_signins = int(events), int(failed)
        s.consents, s.attacks = int(consents), int(attacks)
        if blocked:
            _flag(out, (str(kind), str(value)), "blocked_calls")
        if personal:
            _flag(out, (str(kind), str(value)), "personal_account")
    for person, n in engine.run(risky_by_person_sql(), scope, timeout_s=TIMEOUT_S, page=True).rows:
        out.setdefault(("user", str(person)), Signals()).mail_rules = int(n)
    if scope.start is not None:
        wide = QueryScope(scope.sources, scope.start - NEW_MCP_LOOKBACK, scope.end)
        rows = engine.run(NEW_MCP_SQL, wide, {"start": scope.start}, timeout_s=TIMEOUT_S).rows
        for who, host in rows:
            if who:
                _flag(out, ("user", str(who)), "new_mcp")
            if host:
                _flag(out, ("host", str(host)), "new_mcp")
    if usage is not None:
        for who, machine in usage.unreviewed_use(scope):
            if who:
                _flag(out, ("user", who), "unreviewed_service")
            if machine:
                _flag(out, ("host", machine), "unreviewed_service")
    return out, list(seen.sources)


def alert_names(meta: MetaDB, allowed: list[str] | None, scope: QueryScope) -> list[set[str]]:
    """Per alert item in the range, the names it is about (its people and devices, from
    the rows that fired, and its subject), lower case. Only items whose sources the caller
    may read count."""
    with meta.connect() as con:
        rows = con.execute(
            "SELECT subject, people, devices, sources, created_at FROM alert_items"
            " ORDER BY created_at DESC LIMIT ?",
            (MAX_ALERTS,),
        ).fetchall()
    permitted = None if allowed is None else set(allowed)
    out: list[set[str]] = []
    for r in rows:
        at = str(r["created_at"])
        if scope.start and at < scope.start.isoformat():
            continue
        if scope.end and at >= scope.end.isoformat():
            continue
        try:
            sources = set(json.loads(r["sources"] or "[]"))
            names = [*json.loads(r["people"] or "[]"), *json.loads(r["devices"] or "[]")]
        except ValueError:
            continue
        if permitted is not None and not sources <= permitted:
            continue
        out.append({str(n).lower() for n in [*names, r["subject"]] if n})
    return out


def count_alerts(items: list[set[str]], names: list[str]) -> int:
    """Alerts about any of these names (a person's names count each alert once)."""
    wanted = {n.lower() for n in names}
    return sum(1 for item in items if item & wanted)
