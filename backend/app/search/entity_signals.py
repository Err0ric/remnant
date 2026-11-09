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
from app.core.timing import phase
from app.engine.duckdb import QueryEngine, QueryScope
from app.enrich import networks
from app.meta.db import MetaDB
from app.search.dashboard import FAILURE_WITH_ADDRESS
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

_KIND = "CASE WHEN grouping(u) = 0 THEN 'user' WHEN grouping(ip) = 0 THEN 'ip' ELSE 'host' END"
_PER_ENTITY = f"""SELECT {_KIND} AS kind, coalesce(u, ip, h) AS value,"""


def seen_sql(internal: str = "is_internal(ip)") -> str:
    """One row per entity: events, failed sign-ins, app consents (each consent once, D150),
    attack hits from outside, blocked tool calls, and whether a personal Claude account ran.
    `internal` is the membership test for the column `ip` (`networks.internal_sql`).

    Shaped for speed (owner, 2026-11-07): events are counted per user, address, and host
    in one grouping pass over three columns, and the signals are read only from the rows
    that can carry one (sign-ins, hook events, consents), so DNS and firewall rows are
    never fanned out; "internal" is decided once per distinct address of a failed sign-in,
    in SQL, not once per row. Hook fields are read in a scan of hook rows alone (owner
    item 2, 2026-11-08): a Windows sign-in carries about 1.5 KB of `unmapped`, and reading
    it for every sign-in to find the few hook rows was most of the page's time."""
    return f"""
WITH n AS (
  {_PER_ENTITY} count(*) AS events
  FROM (SELECT actor_user_name AS u, src_endpoint_ip AS ip, device_hostname AS h FROM events)
  GROUP BY GROUPING SETS ((u), (ip), (h))
),
s AS (
  SELECT actor_user_name AS u, src_endpoint_ip AS ip, device_hostname AS h,
         class_uid = 3002 AND status_id = 2 AS fail,
         CASE WHEN message ILIKE 'Consent to application%'
              THEN coalesce(metadata_correlation_uid, CAST(event_id AS VARCHAR)) END AS consent,
         coalesce({FAILURE_WITH_ADDRESS}, false) AS addressed
  FROM events
  WHERE class_uid = 3002 OR message ILIKE 'Consent to application%'
),
a AS (SELECT ip, {internal} AS inside FROM (SELECT DISTINCT ip FROM s WHERE addressed)),
g AS (
  {_PER_ENTITY}
         count(*) FILTER (WHERE fail) AS failed,
         count(*) FILTER (WHERE addressed AND NOT coalesce(a.inside, false)) AS attacks
  FROM s LEFT JOIN a USING (ip) GROUP BY GROUPING SETS ((u), (ip), (h))
),
-- Hook rows only, the one scan that reads `unmapped`: blocked calls and personal accounts
-- count for users and hosts.
k AS (
  SELECT CASE WHEN grouping(u) = 0 THEN 'user' ELSE 'host' END AS kind,
         coalesce(u, h) AS value,
         count(*) FILTER (WHERE message = 'claude_hooks.post_tool_use_failure'
                          AND {counted(_a("tool_name"))}) AS blocked,
         bool_or(len($org) > 0 AND {_EMAIL} IS NOT NULL
                 AND NOT list_contains($org, split_part({_EMAIL}, '@', 2))) AS personal
  FROM (SELECT actor_user_name AS u, device_hostname AS h, message, unmapped FROM events
        WHERE template_id = 'claude_hooks')
  GROUP BY GROUPING SETS ((u), (h))
),
-- Consents count for users only, each once (D150): a few rows, apart from the grouping.
c AS (
  SELECT 'user' AS kind, u AS value, count(DISTINCT consent) AS consents
  FROM s WHERE consent IS NOT NULL GROUP BY 2
)
SELECT kind, value, n.events,
       coalesce(g.failed, 0) AS failed,
       coalesce(c.consents, 0) AS consents,
       CASE WHEN kind = 'user' THEN 0 ELSE coalesce(g.attacks, 0) END AS attacks,
       coalesce(k.blocked, 0) AS blocked,
       coalesce(k.personal, false) AS personal
FROM n LEFT JOIN g USING (kind, value) LEFT JOIN c USING (kind, value)
LEFT JOIN k USING (kind, value)
WHERE nullif(value, '') IS NOT NULL
QUALIFY row_number() OVER (PARTITION BY kind ORDER BY n.events DESC, value) <= {SEEN_PER_KIND}
"""  # noqa: S608  # fixed SQL text; `internal` is built from parsed networks


SEEN_SQL = seen_sql()

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
    """Signals per (kind, value), and the sources read. The queries run one after another:
    each already uses every query thread, and side by side they were no faster on a
    2 vCPU server (owner, 2026-11-07), only harder to read in Server-Timing."""
    internal = networks.internal_sql("ip", networks.load(meta).networks())
    with phase("signals_seen"):
        seen = engine.run(
            seen_sql(internal),
            scope,
            {"org": [d.lower() for d in ident.domains]},
            timeout_s=TIMEOUT_S,
            page=True,
        )
    with phase("signals_mail_rules"):
        risky = engine.run(risky_by_person_sql(), scope, timeout_s=TIMEOUT_S, page=True).rows
    mcp_rows: list[Any] = []
    if scope.start is not None:
        wide = QueryScope(scope.sources, scope.start - NEW_MCP_LOOKBACK, scope.end)
        with phase("signals_new_mcp"):
            mcp_rows = engine.run(
                NEW_MCP_SQL, wide, {"start": scope.start}, timeout_s=TIMEOUT_S
            ).rows
    unreviewed: list[tuple[str | None, str | None]] = []
    if usage is not None:
        with phase("signals_unreviewed_ai"):
            unreviewed = usage.unreviewed_use(scope)
    out: dict[Key, Signals] = {}
    for kind, value, events, failed, consents, attacks, blocked, personal in seen.rows:
        s = out.setdefault((str(kind), str(value)), Signals())
        s.events, s.failed_signins = int(events), int(failed)
        s.consents, s.attacks = int(consents), int(attacks)
        if blocked:
            _flag(out, (str(kind), str(value)), "blocked_calls")
        if personal:
            _flag(out, (str(kind), str(value)), "personal_account")
    for person, n in risky:
        out.setdefault(("user", str(person)), Signals()).mail_rules = int(n)
    for who, host in mcp_rows:
        if who:
            _flag(out, ("user", str(who)), "new_mcp")
        if host:
            _flag(out, ("host", str(host)), "new_mcp")
    for who, machine in unreviewed:
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
