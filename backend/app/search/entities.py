"""Entity risk and the investigator graph (ADR-0016 rows 4, 5, 7).

Every number comes from the caller's `events` view through the engine and its guard, with
values bound as parameters. Rule matches live in the metadata database; only matches on
sources the caller may read are used, and only events still in the caller's view and time
range are counted.
"""

from __future__ import annotations

import ipaddress
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from app.ai.catalog import NON_USAGE, Catalog
from app.ai.usage import (
    HOST_EXPR,
    HOST_MATCH_SQL,
    MACHINE_EXPR,
    MCP_EXPR,
    NO_MCP_NAMES,
    WHO_EXPR,
    _use_ctes,
    catalog_values,
    fact_range,
)
from app.core.errors import ParamInvalidError
from app.core.timing import in_context
from app.engine.duckdb import QueryEngine, QueryScope
from app.meta.db import MetaDB
from app.search.addresses import OBS_SQL, address_ctes, join_addr, lookup
from app.search.identity import IdentityMap, key_sql

if TYPE_CHECKING:
    from app.ai.rollup import AiRollup

EntityKind = Literal["user", "ip", "host"]
GraphKind = Literal["user", "ip", "host", "mcp", "service"]
TIMEOUT_S = 20.0
MAX_MATCHES = 20_000
MAX_CARDS = 60
PER_LANE = 15
WEIGHTS = {"critical": 10, "high": 5, "medium": 2}  # anything else: 1
FLAG_POINTS = 3

COLUMN: dict[EntityKind, str] = {
    "user": "actor_user_name",
    "ip": "src_endpoint_ip",
    "host": "device_hostname",
}
# Graph filters: an IP or host matches on either side of the event.
WHERE: dict[str, str] = {
    "user": "actor_user_name = $v",
    "ip": "(src_endpoint_ip = $v OR dst_endpoint_ip = $v)",
    "host": "(device_hostname = $v OR src_endpoint_hostname = $v)",
}


def quote(value: str) -> str:
    """A SQL string literal for the Search handoff. The SQL still goes through the guard
    on a read-only connection; doubling quotes keeps the value one literal."""
    return "'" + value.replace("'", "''") + "'"


def lit_list(values: list[str]) -> str:
    """A SQL list literal of quoted strings, for Search handoff SQL."""
    return "[" + ", ".join(quote(v) for v in values) + "]"


def user_filter_sql(m: IdentityMap, keys: list[str]) -> str:
    """Literal SQL selecting every name that counts as one of these person keys."""
    return (
        key_sql("actor_user_name")
        .replace("$id_org", lit_list(m.domains or [""]))
        .join(["list_contains(" + lit_list(keys) + ", ", ")"])
    )


def search_sql(where: str) -> str:
    return (
        "SELECT time, severity_id, source_id, device_hostname, actor_user_name, message,"
        " event_id\nFROM events\nWHERE " + where + "\nORDER BY coalesce(time, time_observed) DESC"
    )


# --- rule matches -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Match:
    event_id: str
    level: str
    rule: str


def visible_matches(meta: MetaDB, allowed: list[str] | None) -> list[Match]:
    """Newest rule matches on sources the caller may read, one per rule and event."""
    with meta.connect() as con:
        rows = con.execute(
            "SELECT m.event_id, m.source_id, v.level, v.title, v.rule_id FROM rule_matches m"
            " JOIN rule_runs r ON r.run_id = m.run_id"
            " JOIN rule_versions v ON v.sha256 = r.sha256"
            " ORDER BY m.rowid DESC LIMIT ?",
            (MAX_MATCHES * 2,),
        ).fetchall()
    permitted = None if allowed is None else set(allowed)
    seen: set[tuple[str, str]] = set()
    out: list[Match] = []
    for r in rows:
        if permitted is not None and r["source_id"] not in permitted:
            continue
        key = (str(r["rule_id"]), str(r["event_id"]))
        if key in seen:
            continue
        seen.add(key)
        out.append(Match(str(r["event_id"]), str(r["level"]).lower(), str(r["title"])))
        if len(out) >= MAX_MATCHES:
            break
    return out


# --- entity risk ------------------------------------------------------------------------


@dataclass(slots=True)
class Risk:
    kind: EntityKind
    value: str
    score: int = 0
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    flagged_runs: int = 0
    events: int = 0
    rules: list[str] = field(default_factory=list)
    search_sql: str = ""
    names: list[str] = field(default_factory=list)  # users: the logged names merged here


RISK_SQL = """
WITH m AS (SELECT unnest($ids) AS id, unnest($levels) AS lv, unnest($rules) AS rule),
e AS (
  SELECT e.event_id, e.actor_user_name AS u, e.src_endpoint_ip AS ip, e.device_hostname AS h,
         m.lv, m.rule
  FROM events e JOIN m ON e.event_id = m.id
),
x AS (
  SELECT 'user' AS kind, u AS value, lv, rule, event_id FROM e WHERE nullif(u, '') IS NOT NULL
  UNION ALL
  SELECT 'ip', ip, lv, rule, event_id FROM e WHERE nullif(ip, '') IS NOT NULL
  UNION ALL
  SELECT 'host', h, lv, rule, event_id FROM e WHERE nullif(h, '') IS NOT NULL
)
SELECT kind, value,
       count(*) FILTER (WHERE lv = 'critical') AS critical,
       count(*) FILTER (WHERE lv = 'high') AS high,
       count(*) FILTER (WHERE lv = 'medium') AS medium,
       count(*) FILTER (WHERE lv NOT IN ('critical', 'high', 'medium')) AS low,
       count(DISTINCT event_id) AS events,
       list_slice(list(DISTINCT rule ORDER BY rule), 1, 5) AS rules
FROM x GROUP BY 1, 2
LIMIT 5000"""


def _flagged(
    meta: MetaDB, allowed: list[str] | None, scope: QueryScope
) -> dict[tuple[str, str], int]:
    """Flagged schedule runs in the range whose sample names an entity, per entity. Only
    runs that read nothing outside the caller's sources count."""
    with meta.connect() as con:
        rows = con.execute(
            "SELECT started_at, sources_in_scope, columns, sample FROM schedule_runs"
            " WHERE flagged = 1 AND sample IS NOT NULL ORDER BY started_at DESC LIMIT 500"
        ).fetchall()
    permitted = None if allowed is None else set(allowed)
    out: dict[tuple[str, str], int] = {}
    for r in rows:
        started = datetime.fromisoformat(r["started_at"])
        if (scope.start and started < scope.start) or (scope.end and started >= scope.end):
            continue
        read = set(json.loads(r["sources_in_scope"] or "[]"))
        if permitted is not None and not read <= permitted:
            continue
        try:
            columns = list(json.loads(r["columns"] or "[]"))
            sample = list(json.loads(r["sample"] or "[]"))
        except ValueError:
            continue
        named: set[tuple[str, str]] = set()
        for kind, col in COLUMN.items():
            if col not in columns:
                continue
            i = columns.index(col)
            named |= {(kind, str(row[i])) for row in sample if len(row) > i and row[i]}
        for key in named:
            out[key] = out.get(key, 0) + 1
    return out


def entity_risk(
    engine: QueryEngine,
    meta: MetaDB,
    allowed: list[str] | None,
    scope: QueryScope,
    ident: IdentityMap | None = None,
) -> tuple[dict[EntityKind, list[Risk]], int, list[str]]:
    """Ranked users, source IPs, and hosts; the number of matches considered; sources read."""
    matches = visible_matches(meta, allowed)
    found: dict[tuple[str, str], Risk] = {}
    read: list[str] = [] if scope.sources is None else list(scope.sources)
    if matches:
        result = engine.run(
            RISK_SQL,
            scope,
            {
                "ids": [m.event_id for m in matches],
                "levels": [m.level for m in matches],
                "rules": [m.rule for m in matches],
            },
            timeout_s=TIMEOUT_S,
        )
        read = result.sources
        for kind, value, crit, high, med, low, events, rules in result.rows:
            found[(kind, value)] = Risk(
                kind=kind,
                value=str(value),
                critical=int(crit),
                high=int(high),
                medium=int(med),
                low=int(low),
                events=int(events),
                rules=[str(x) for x in rules or []],
            )
    for (kind, value), n in _flagged(meta, allowed, scope).items():
        risk = found.setdefault((kind, value), Risk(kind=kind, value=value))  # type: ignore[arg-type]  # kind comes from COLUMN keys
        risk.flagged_runs = n
    ident = ident or IdentityMap()
    merged = _merge_users([r for r in found.values() if r.kind == "user"], ident)
    out: dict[EntityKind, list[Risk]] = {"user": [], "ip": [], "host": []}
    for risk in [r for r in found.values() if r.kind != "user"] + merged:
        risk.score = (
            WEIGHTS["critical"] * risk.critical
            + WEIGHTS["high"] * risk.high
            + WEIGHTS["medium"] * risk.medium
            + risk.low
            + FLAG_POINTS * risk.flagged_runs
        )
        if not risk.search_sql:
            risk.search_sql = search_sql(f"{COLUMN[risk.kind]} = {quote(risk.value)}")
        out[risk.kind].append(risk)
    for kind in out:
        out[kind].sort(key=lambda r: (-r.score, r.value))
        out[kind] = out[kind][:50]
    return out, len(matches), read


def _merge_users(rows: list[Risk], ident: IdentityMap) -> list[Risk]:
    """One row per person (ADR-0018): names that count as the same person are added up."""
    groups: dict[str, list[Risk]] = {}
    for r in rows:
        groups.setdefault(ident.key(r.value), []).append(r)
    out: list[Risk] = []
    for key, rs in groups.items():
        email = any(ident.org_email(r.value) for r in rs)
        total = Risk(kind="user", value=ident.display(key, email))
        for r in rs:
            total.critical += r.critical
            total.high += r.high
            total.medium += r.medium
            total.low += r.low
            total.events += r.events
            total.flagged_runs += r.flagged_runs
            total.rules = sorted(set(total.rules) | set(r.rules))[:5]
        total.names = sorted({r.value for r in rs})
        total.search_sql = search_sql(user_filter_sql(ident, ident.keys_for(key)))
        out.append(total)
    return out


# --- graph ------------------------------------------------------------------------------


@dataclass(slots=True)
class Card:
    id: str
    lane: int
    label: str
    sublabel: str = ""
    events: int = 0
    matches: int = 0
    max_severity: int = 0
    badges: list[str] = field(default_factory=list)
    search_sql: str | None = None
    group: str = ""  # a heading inside the lane ("MCP servers"); empty for none


@dataclass(slots=True)
class Edge:
    source: str
    target: str
    events: int


@dataclass(slots=True)
class Graph:
    mode: Literal["entity", "ai"]
    lanes: list[str]
    cards: list[Card]
    edges: list[Edge]
    more: list[int]  # cards left out per lane
    sources: list[str]


# Lines that differ only in numbers (ports, pids, addresses, ttys) are one activity.
PATTERN = "regexp_replace(message, '[0-9]+', '#', 'g')"

ENTITY_SQL = """
SELECT source_id, class_uid,
       coalesce(nullif(left({PATTERN}, 60), ''), '(no message)') AS activity,
       coalesce(nullif(dst_endpoint_hostname, ''), nullif(dst_endpoint_ip, '')) AS target,
       count(*) AS n,
       count(*) FILTER (WHERE event_id IN (SELECT unnest($ids))) AS m,
       max(coalesce(severity_id, 0)) AS sev
FROM events
WHERE {where}
GROUP BY 1, 2, 3, 4
ORDER BY n DESC
LIMIT 2000"""

# MCP inventory client ids (scripts/endpoint) as people know them; Claude Code telemetry
# and the inventory's claude_code are one client.
CLIENT_NAMES = {
    "claude_code": "Claude Code",
    "claude_desktop": "Claude Desktop",
    "vscode": "VS Code",
    "cursor": "Cursor",
    "windsurf": "Windsurf",
}

CLASS_NAMES = {
    0: "Other",
    1001: "File activity",
    1006: "Scheduled job activity",
    2001: "Security finding",
    3005: "User access management",
    3006: "Group management",
    4002: "HTTP activity",
    4004: "DHCP activity",
    5001: "Device inventory",
    1007: "Process activity",
    2004: "Detection finding",
    3001: "Account change",
    3002: "Authentication",
    3004: "Entity management",
    4001: "Network activity",
    4003: "DNS activity",
    5020: "Software inventory",
    6003: "API activity",
}


class _Builder:
    """Collects cards and edges, then keeps the largest cards per lane."""

    def __init__(self, lanes: list[str]) -> None:
        self.lanes = lanes
        self.cards: dict[str, Card] = {}
        self.edges: dict[tuple[str, str], int] = {}

    def card(self, lane: int, key: str, label: str, n: int, m: int = 0, sev: int = 0) -> str:
        cid = f"{lane}:{key}"
        c = self.cards.get(cid)
        if c is None:
            c = self.cards[cid] = Card(id=cid, lane=lane, label=label)
        c.events += n
        c.matches += m
        c.max_severity = max(c.max_severity, sev)
        return cid

    def edge(self, a: str, b: str, n: int) -> None:
        self.edges[(a, b)] = self.edges.get((a, b), 0) + n

    def build(self, mode: Literal["entity", "ai"], sources: list[str]) -> Graph:
        keep: set[str] = set()
        more: list[int] = []
        for lane in range(len(self.lanes)):
            in_lane = sorted(
                (c for c in self.cards.values() if c.lane == lane),
                key=lambda c: (-c.matches, -c.events, c.label),
            )
            room = PER_LANE if lane else 5
            keep |= {c.id for c in in_lane[:room]}
            more.append(max(0, len(in_lane) - room))
        cards = [c for c in self.cards.values() if c.id in keep][:MAX_CARDS]
        kept = {c.id for c in cards}
        edges = [Edge(a, b, n) for (a, b), n in self.edges.items() if a in kept and b in kept]
        cards.sort(key=lambda c: (c.lane, -c.matches, -c.events, c.label))
        return Graph(mode, self.lanes, cards, edges, more, sources)


def entity_graph(
    engine: QueryEngine,
    meta: MetaDB,
    allowed: list[str] | None,
    scope: QueryScope,
    kind: Literal["user", "ip", "host"],
    value: str,
    ident: IdentityMap | None = None,
) -> Graph:
    """Entity -> Sources -> Activities -> Targets (ADR-0016 row 5). A user is everyone
    named as the same person (ADR-0018)."""
    ident = ident or IdentityMap()
    ids = [m.event_id for m in visible_matches(meta, allowed)]
    params: dict[str, object] = {"ids": ids or [""]}
    where = WHERE[kind]
    label = value
    if kind == "user":
        keys = ident.keys_for(value)
        where = f"list_contains($keys, {key_sql('actor_user_name')})"
        params |= {"keys": keys, **ident.params()}
    else:
        params["v"] = value
        label = ident.display(ident.key(value), ident.org_email(value))
    result = engine.run(
        ENTITY_SQL.format(where=where, PATTERN=PATTERN),
        scope,
        params,
        timeout_s=TIMEOUT_S,
    )
    literal = (
        user_filter_sql(ident, params["keys"])  # type: ignore[arg-type]  # set just above for users
        if kind == "user"
        else WHERE[kind].replace("$v", quote(value))
    )
    b = _Builder(["Entity", "Sources", "Activities", "Targets"])
    root = b.card(0, "root", label, 0)
    b.cards[root].sublabel = {"user": "User", "ip": "IP address", "host": "Host"}[kind]
    if kind == "ip":
        # Who had the address most recently in the range (ADR-0020 row 1).
        at = scope.end or datetime.now(UTC)
        try:
            holders = lookup(engine, QueryScope(scope.sources), value, at)
        except ParamInvalidError:
            holders = []
        names = [h.name for h in holders if h.kind == "user"][:1]
        names += [h.name for h in holders if h.kind == "host"][:1]
        if names:
            b.cards[root].sublabel = f"IP address · {', '.join(names)}"
    b.cards[root].search_sql = search_sql(literal)
    for source_id, class_uid, activity, target, n, m, sev in result.rows:
        n, m, sev = int(n), int(m), int(sev or 0)
        b.cards[root].events += n
        b.cards[root].matches += m
        b.cards[root].max_severity = max(b.cards[root].max_severity, sev)
        s = b.card(1, str(source_id), str(source_id), n, m, sev)
        b.cards[s].search_sql = search_sql(f"{literal} AND source_id = {quote(str(source_id))}")
        a = b.card(2, f"{class_uid}|{activity}", str(activity), n, m, sev)
        b.cards[a].sublabel = CLASS_NAMES.get(int(class_uid or 0), f"Class {class_uid}")
        b.cards[a].group = b.cards[a].sublabel
        b.cards[a].search_sql = search_sql(
            f"{literal} AND left({PATTERN}, 60) = {quote(str(activity))}"
        )
        b.edge(root, s, n)
        b.edge(s, a, n)
        if target:
            t = b.card(3, str(target), str(target), n, m, sev)
            b.cards[t].group = "IP addresses" if _is_ip(str(target)) else "Hosts"
            b.cards[t].search_sql = search_sql(
                f"{literal} AND (dst_endpoint_hostname"
                f" = {quote(str(target))} OR dst_endpoint_ip = {quote(str(target))})"
            )
            b.edge(a, t, n)
    for c in b.cards.values():
        if c.matches:
            c.badges.append(f"{c.matches} rule {'match' if c.matches == 1 else 'matches'}")
        if c.max_severity >= 4:
            c.badges.append("High severity")
    return b.build("entity", result.sources)


# AI flow: one row per (person, client, tool, destination) with counts. Claude Code
# telemetry, the MCP inventory, and network logs matched to the AI catalog.
def ai_sql(pairs_sql: str, where: str, pre: str = "true") -> str:
    """`pre` filters events early in each branch; `{m}` in it is that branch's machine."""
    cc_pre = pre.replace("{m}", "device_hostname")
    net_pre = pre.replace("{m}", MACHINE_EXPR)
    if pre != "true":
        # Rows that name only an address are kept when the address was this person's
        # (logon and User-ID events), so resolution below can name them (ADR-0020 row 1).
        theirs = "SELECT ip FROM addr_user WHERE list_contains($names, lower(who))"
        net_pre = f"(({net_pre}) OR ({WHO_EXPR} IS NULL AND src_endpoint_ip IN ({theirs})))"
    return f"""
WITH cat(service_id, domain) AS (VALUES {pairs_sql}),
{OBS_SQL},
cc AS (
  SELECT {WHO_EXPR} AS who, 'Claude Code' AS client,
         coalesce({MCP_EXPR},
                  json_extract_string(unmapped, '$.attr.tool_name')) AS tool,
         CASE WHEN message IN ('claude_code.api_request', 'claude_code.api_error')
              THEN 'api.anthropic.com' END AS dest,
         TRY_CAST(json_extract_string(unmapped, '$.attr.sensitive_total') AS BIGINT) AS sens,
         device_hostname AS machine, {MCP_EXPR} IS NOT NULL AS mcp
  FROM events WHERE template_id = 'claude_code_otel' AND {cc_pre}
),
inv AS (
  SELECT {WHO_EXPR} AS who,
         coalesce(json_extract_string(unmapped, '$.client'),
                  json_extract_string(unmapped, '$.attr.client'), 'MCP client') AS client,
         message AS tool, nullif(dst_endpoint_hostname, '') AS dest, 0 AS sens,
         device_hostname AS machine, true AS mcp
  FROM events WHERE template_id = 'mcp_inventory' AND {cc_pre}
),
net AS (
  SELECT {WHO_EXPR} AS who, 'Browser or app' AS client, CAST(NULL AS VARCHAR) AS tool,
         {HOST_EXPR} AS host, 0 AS sens, nullif(src_endpoint_hostname, '') AS shost,
         nullif(src_endpoint_ip, '') AS ip, device_hostname AS dev,
         coalesce(time, time_observed) AS t
  FROM events
  WHERE template_id NOT IN ('claude_code_otel', 'mcp_inventory') AND {net_pre}
),
{HOST_MATCH_SQL.format(src="net")},
netm AS (SELECT net.*, hm.service_id FROM net JOIN hm USING (host)),
{address_ctes("netm", "who IS NULL OR shost IS NULL", obs=False)},
netr AS (
  SELECT client, tool, sens, service_id, coalesce(who, addr.rwho) AS who,
         coalesce(shost, addr.rhost, netm.ip, dev) AS machine
  FROM netm {join_addr("netm")}
),
flow AS (
  SELECT coalesce(who, machine) AS person, who IS NOT NULL AS named, client, tool, dest, sens,
         mcp FROM cc
  UNION ALL SELECT coalesce(who, machine), who IS NOT NULL, client, tool, dest, sens, mcp
  FROM inv
  UNION ALL SELECT coalesce(who, machine), who IS NOT NULL, client, tool,
         'svc:' || service_id, sens, false
  FROM netr
)
SELECT person, client, tool, dest, count(*) AS n, coalesce(sum(sens), 0) AS sens,
       bool_or(mcp) AS mcp, bool_or(named) AS named
FROM flow
WHERE person IS NOT NULL AND {where}
GROUP BY 1, 2, 3, 4
ORDER BY n DESC
LIMIT 3000"""  # noqa: S608  # fixed text; catalog domains are checked before use


NAMES_SQL = """SELECT DISTINCT lower(trim(actor_user_name)) FROM events
WHERE nullif(trim(actor_user_name), '') IS NOT NULL LIMIT 200000"""


def person_names(
    engine: QueryEngine, scope: QueryScope, ident: IdentityMap, person: str
) -> list[str]:
    """Every logged name (lower case) that counts as this person, plus the person value
    itself for events that only carry a machine name or address."""
    keys = set(ident.keys_for(person))
    rows = engine.run(NAMES_SQL, scope, timeout_s=TIMEOUT_S).rows
    found = {str(n) for (n,) in rows if ident.key(str(n)) in keys}
    return sorted(found | keys | {person.strip().lower()})


_FLOW_SELECT = """
SELECT person, client, tool, dest, sum(w)::BIGINT AS n, coalesce(sum(sens), 0) AS sens,
       bool_or(mcp) AS mcp, bool_or(named) AS named
FROM flow
WHERE person IS NOT NULL AND {where}
GROUP BY 1, 2, 3, 4
ORDER BY n DESC
LIMIT 3000"""


def ai_tools_sql(where: str) -> str:
    """The AI flow's Claude Code and MCP inventory rows: small, by template."""
    return f"""
WITH cc AS (
  SELECT {WHO_EXPR} AS who, 'Claude Code' AS client,
         coalesce({MCP_EXPR},
                  json_extract_string(unmapped, '$.attr.tool_name')) AS tool,
         CASE WHEN message IN ('claude_code.api_request', 'claude_code.api_error')
              THEN 'api.anthropic.com' END AS dest,
         TRY_CAST(json_extract_string(unmapped, '$.attr.sensitive_total') AS BIGINT) AS sens,
         device_hostname AS machine, {MCP_EXPR} IS NOT NULL AS mcp
  FROM events WHERE template_id = 'claude_code_otel'
),
inv AS (
  SELECT {WHO_EXPR} AS who,
         coalesce(json_extract_string(unmapped, '$.client'),
                  json_extract_string(unmapped, '$.attr.client'), 'MCP client') AS client,
         message AS tool, nullif(dst_endpoint_hostname, '') AS dest, 0 AS sens,
         device_hostname AS machine, true AS mcp
  FROM events WHERE template_id = 'mcp_inventory'
),
flow AS (
  SELECT coalesce(who, machine) AS person, who IS NOT NULL AS named, client, tool, dest, sens,
         mcp, 1 AS w FROM cc
  UNION ALL SELECT coalesce(who, machine), who IS NOT NULL, client, tool, dest, sens, mcp, 1
  FROM inv
){_FLOW_SELECT.replace("{where}", where)}"""  # noqa: S608  # fixed text


def ai_web_sql(pairs: list[tuple[str, str]], where: str, rollup: bool) -> str:
    """The AI flow's browser and app rows: the same use rows as AI usage (`_use_ctes`),
    so closed days come from the daily AI rollup instead of a scan of every event
    (owner re-time, 2026-11-01: the person graph read 30 days of DNS for each load)."""
    return f"""
WITH {_use_ctes(pairs, rollup)},
flow AS (
  SELECT coalesce(who, machine) AS person, who IS NOT NULL AS named,
         'Browser or app' AS client, CAST(NULL AS VARCHAR) AS tool,
         'svc:' || service_id AS dest, 0 AS sens, false AS mcp, n AS w
  FROM r
){_FLOW_SELECT.replace("{where}", where)}"""  # noqa: S608  # catalog domains checked in _values


def _ai_rows_rolled(
    engine: QueryEngine,
    catalog: Catalog,
    scope: QueryScope,
    where: str,
    params: dict[str, object],
    skip: list[str],
    covered: list[str],
    after: tuple[list[str], datetime] | None,
) -> tuple[list[Any], list[str]]:
    """The AI flow's rows with closed days from the rollup: Claude Code and MCP inventory
    from events (small, by template; `skip_days` would drop them), the rest from the
    rollup and the days it does not cover, both at once."""
    web_params = {**params, "covered": covered, **fact_range(scope, scope.end or datetime.now(UTC))}
    with ThreadPoolExecutor(max_workers=1) as pool:
        tools = pool.submit(
            in_context(engine.run),
            ai_tools_sql(where),
            scope,
            params or None,
            timeout_s=TIMEOUT_S,
            name="graph.ai_tools",
        )
        web = engine.run(
            ai_web_sql(catalog.domain_table(), where, True),
            scope,
            web_params,
            timeout_s=TIMEOUT_S,
            rollup=True,
            skip_days=skip,
            after=after,
            name="graph.ai_web",
        )
        found = tools.result()
    rows = sorted([*found.rows, *web.rows], key=lambda r: -int(r[4]))[:3000]
    return rows, sorted(set(found.sources) | set(web.sources))


def ai_graph(
    engine: QueryEngine,
    catalog: Catalog,
    scope: QueryScope,
    kind: Literal["user", "mcp", "service"] | None,
    value: str | None,
    ident: IdentityMap | None = None,
    rollup: AiRollup | None = None,
) -> Graph:
    """People -> AI clients -> Tools and MCP servers -> Destinations (ADR-0016 row 5).
    People are merged by identity (ADR-0018)."""
    ident = ident or IdentityMap()
    where = {
        None: "true",
        "user": f"list_contains($keys, {key_sql('person')})",
        "mcp": "tool = $v",
        "service": "dest = 'svc:' || $v",
    }[kind]
    params: dict[str, object] = {}
    if kind == "user" and value:
        params = {"keys": ident.keys_for(value), **ident.params()}
    elif kind:
        params["v"] = value
    # Browser and app use comes from the daily AI rollup when it has days in range, like
    # AI usage (owner re-time, 2026-11-01: the graph read 30 days of DNS on every load).
    planned = scope if scope.end is not None else replace(scope, end=datetime.now(UTC))
    skip, covered, after = rollup.plan(planned) if rollup is not None else ([], [], None)
    if covered:
        rows, sources = _ai_rows_rolled(engine, catalog, scope, where, params, skip, covered, after)
    else:
        pre = "true"
        if kind == "user" and value:
            # Their raw names come from a cheap distinct scan, so each branch keeps only
            # their events before any host parsing; the exact key test in `where` applies.
            pre = "list_contains($names, lower(coalesce(" + WHO_EXPR + ", {m})))"
            params["names"] = person_names(engine, scope, ident, value)
        result = engine.run(
            ai_sql(catalog_values(catalog.domain_table()), where, pre),
            scope,
            params or None,
            timeout_s=TIMEOUT_S,
            name="graph.ai",
        )
        rows, sources = result.rows, result.sources
    seen_email: dict[str, bool] = {}
    names: dict[str, set[str]] = {}
    named_keys: dict[str, bool] = {}  # person cards that a logged person name produced
    services = {s.id: s for s in catalog.services()}
    rules = catalog.mcp_rules()
    domains = sorted(catalog.domain_table(), key=lambda p: -len(p[1]))

    def as_service(host: str) -> str:
        """A raw destination host that is a catalog service becomes that service's card."""
        h = host.lower().rstrip(".")
        for sid, dom in domains:
            if h == dom or h.endswith("." + dom):
                hit = services.get(sid)
                return host if hit is not None and hit.kind == NON_USAGE else f"svc:{sid}"
        return host

    b = _Builder(["People", "AI clients", "Tools and MCP servers", "Destinations"])
    for person, client, tool, dest, n, sens, mcp, named in rows:
        if dest and str(dest).startswith("svc:"):
            hit = services.get(str(dest)[4:])
            if hit is not None and hit.kind == NON_USAGE:
                continue  # a vendor tag on another site is not AI use
        n, sens = int(n), int(sens or 0)
        pkey = ident.key(str(person))
        seen_email[pkey] = seen_email.get(pkey, False) or ident.org_email(str(person))
        names.setdefault(pkey, set()).add(str(person))
        p = b.card(0, pkey, pkey, n)
        named_keys[pkey] = named_keys.get(pkey, False) or bool(named)
        cname = CLIENT_NAMES.get(str(client), str(client))
        c = b.card(1, cname.lower(), cname, n)
        b.edge(p, c, n)
        last = c
        if tool and str(tool).lower() not in NO_MCP_NAMES:
            t = b.card(2, str(tool), str(tool), n)
            if mcp:
                b.cards[t].group = "MCP servers"
            elif not b.cards[t].group:
                b.cards[t].group = "Built-in tools"
            status = catalog.mcp_status(str(tool), rules)
            if status == "not_approved" and "Not approved" not in b.cards[t].badges:
                b.cards[t].badges.append("Not approved")
            b.edge(c, t, n)
            last = t
        if dest:
            d = str(dest) if str(dest).startswith("svc:") else as_service(str(dest))
            label, sub, refused = d, "", False
            if d.startswith("svc:"):
                svc = services.get(d[4:])
                label = svc.name if svc else d[4:]
                sub = svc.vendor if svc else "AI service"
                refused = bool(svc and svc.status == "not_approved")
            dcard = b.card(3, d, label, n)
            b.cards[dcard].group = "AI services" if d.startswith("svc:") else "Other hosts"
            b.cards[dcard].sublabel = sub
            if refused and "Not approved" not in b.cards[dcard].badges:
                b.cards[dcard].badges.append("Not approved")
            b.cards[dcard].search_sql = (
                search_sql(f"dst_endpoint_hostname = {quote(d)}")
                if not d.startswith("svc:")
                else None
            )
            b.edge(last, dcard, n)
        if sens:
            for cid in (p, c, last):
                if "Sensitive data" not in b.cards[cid].badges:
                    b.cards[cid].badges.append("Sensitive data")
    for pkey, raw in names.items():
        card = b.cards[f"0:{pkey}"]
        card.label = ident.display(pkey, seen_email[pkey])
        if len(raw) > 1:
            card.sublabel = f"{len(raw)} names"
        elif _is_ip(pkey):
            card.sublabel = "No user name in these logs"
        # A device or address with no person named is shown apart, never as a person
        # (owner, 2026-10-22): addresses, then machine names, each in their own group.
        card.group = (
            "People"
            if named_keys.get(pkey)
            else "Addresses"
            if _is_ip(pkey)
            else "Devices not matched to a person"
        )
        card.search_sql = search_sql(
            f"({user_filter_sql(ident, ident.keys_for(pkey))} OR device_hostname IN"
            f" ({', '.join(quote(r) for r in sorted(raw))}))"
        )
    return b.build("ai", sources)


def _is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return False
    return True


def to_json(obj: Any) -> Any:
    """Dataclasses to plain dicts for the API layer."""
    if isinstance(obj, list):
        return [to_json(x) for x in obj]
    if hasattr(obj, "__dataclass_fields__"):
        return {k: to_json(getattr(obj, k)) for k in obj.__dataclass_fields__}
    return obj
