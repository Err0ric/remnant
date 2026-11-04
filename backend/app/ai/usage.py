"""AI usage numbers (ADR-0015 rows 2, 6, 8): server-built SQL over the caller's events view.

Every query here is fixed text plus catalog domains (each checked against a strict
domain pattern before it is written into SQL) and runs through the engine and its guard
like any other, so people see only sources they may read.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from app.ai.catalog import DOMAIN, NON_USAGE, Catalog, Service, Status
from app.ai.internal_tools import counted
from app.engine.duckdb import QueryEngine, QueryScope
from app.search.addresses import address_ctes, join_addr
from app.search.identity import IdentityMap

TIMEOUT_S = 20.0
NO_MCP_NAMES = ("", "custom", "mcp_tool", "third-party")

_CANDIDATES = (
    "dst_endpoint_hostname",
    "json_extract_string(unmapped, '$.query')",
    "json_extract_string(unmapped, '$.qname')",
    "json_extract_string(unmapped, '$.url')",
    "json_extract_string(unmapped, '$.url_filename')",
    "json_extract_string(unmapped, '$.hostname')",
    "json_extract_string(unmapped, '$.dstname')",
)
# The destination host of an event, from the column or the fields DNS, proxy, and
# firewall templates leave in unmapped, with any URL scheme, path, and port removed. A
# plain host name in the column (the usual case) skips the JSON and regex work.
_SLOW_HOST = (
    "rtrim(lower(regexp_extract(coalesce(" + ", ".join(_CANDIDATES) + "),"
    " '^(?:[A-Za-z][A-Za-z0-9+.-]*://)?([^/:?#\\s]+)', 1)), '.')"
)
HOST_EXPR = (
    "(CASE WHEN nullif(dst_endpoint_hostname, '') IS NOT NULL"
    " AND strpos(dst_endpoint_hostname, '/') = 0 AND strpos(dst_endpoint_hostname, ':') = 0"
    " THEN rtrim(lower(dst_endpoint_hostname), '.') ELSE " + _SLOW_HOST + " END)"
)
# Hosts are matched to catalog domains once per distinct host (longest domain wins), then
# events join that small table by exact host: far cheaper than matching every event.
HOST_MATCH_SQL = """hosts AS (SELECT DISTINCT host FROM {src} WHERE host IS NOT NULL),
hm AS (
  SELECT host, arg_max(service_id, length(domain)) AS service_id
  FROM hosts JOIN cat ON host = domain OR ends_with(host, '.' || domain)
  GROUP BY host
)"""
WHO_EXPR = "nullif(actor_user_name, '')"
MACHINE_EXPR = "coalesce(nullif(src_endpoint_hostname, ''), src_endpoint_ip, device_hostname)"
MCP_EXPR = (
    "coalesce(json_extract_string(unmapped, '$.attr.mcp_server_name'),"
    " json_extract_string(unmapped, '$.mcp_server_name'))"
)


@dataclass(slots=True)
class ServiceUse:
    service: Service
    events: int
    people: int
    machines: int
    first_seen: str | None
    last_seen: str | None
    top_people: list[str] = field(default_factory=list)
    top_machines: list[str] = field(default_factory=list)


@dataclass(slots=True)
class McpUse:
    name: str
    status: Status
    calls: int
    people: int
    machines: int
    installs: int
    clients: list[str]
    first_seen: str | None
    last_seen: str | None
    sources: list[str]


@dataclass(slots=True)
class Gone:
    """A service or MCP server seen in the period before the range but not in it."""

    kind: Literal["service", "mcp"]
    id: str  # service id, or the MCP server name
    name: str
    status: Status
    last_seen: str | None


@dataclass(slots=True)
class Changes:
    """What changed against the period of the same length just before the range."""

    new_services: list[str]
    new_mcp: list[str]
    gone: list[Gone]
    earlier: int = 0  # services and MCP servers seen in the earlier period at all


@dataclass(slots=True)
class NetUse:
    """A person seen reaching a Claude service on DNS, firewall, or proxy logs (D190)."""

    who: str
    services: list[str] = field(default_factory=list)
    lookups: int = 0
    devices: int = 0
    last_seen: str | None = None


@dataclass(slots=True)
class PersonUse:
    person: str
    cost_usd: float
    tokens: int
    sessions: int
    tool_calls: int
    errors: int
    sensitive: int
    models: list[str]
    # How this person was seen using Claude (owner, 2026-11-02): "plugin" (telemetry or the
    # hooks plugin), "network" (DNS, firewall, or proxy to a Claude service), or "both".
    seen_through: str = "plugin"
    via: list[str] = field(default_factory=list)  # telemetry, hooks
    # What the network saw for this person (network and both rows), and for a network
    # name no plugin person matches, the plugin person it may be (D190).
    network: NetUse | None = None
    maybe: str | None = None


def _values(pairs: list[tuple[str, str]]) -> str:
    rows = []
    for sid, domain in pairs:
        if not DOMAIN.fullmatch(domain) or not sid.replace("_", "").isalnum():
            continue  # never written into SQL unless it is a plain id and domain
        rows.append(f"('{sid}', '{domain}')")
    return ", ".join(rows) or "('none', 'none.invalid')"


# Public name for other server-built SQL (the investigator's AI flow) that needs the list.
catalog_values = _values


_ANY_HOST = "coalesce(" + ", ".join(_CANDIDATES) + ") IS NOT NULL"
# Events reduced to one row per service, person, machine, address, and hour (F46). The
# daily AI rollup (ADR-0035 Part 1) stores exactly these rows per source and closed day.
_HOUR_ROWS = f"""{WHO_EXPR} AS who0, nullif(src_endpoint_hostname, '') AS shost,
         nullif(src_endpoint_ip, '') AS ip, device_hostname AS dev,
         date_trunc('hour', coalesce(time, time_observed)) AS t,
         count(*) AS n, min(coalesce(time, time_observed)) AS first_t,
         max(coalesce(time, time_observed)) AS last_t"""


def _match_ctes(pairs: list[tuple[str, str]]) -> str:
    """Catalog domains, the distinct hosts of the events `where` selects, and which
    service each host is."""
    return f"""cat(service_id, domain) AS (VALUES {_values(pairs)}),
hosts AS (
  SELECT DISTINCT {HOST_EXPR} AS host FROM events
  WHERE {_ANY_HOST}
),
hm AS (
  SELECT host, arg_max(service_id, length(domain)) AS service_id
  FROM hosts JOIN cat ON host = domain OR ends_with(host, '.' || domain)
  WHERE host IS NOT NULL
  GROUP BY host
)"""  # noqa: S608  # fixed SQL text; domains checked against DOMAIN in _values


def rollup_build_sql(pairs: list[tuple[str, str]]) -> str:
    """One source's closed day as rollup rows, with the source's classification as the
    events had it (ADR-0035 row 4)."""
    return f"""
WITH {_match_ctes(pairs)}
SELECT source_id, classification, hm.service_id, {_HOUR_ROWS}
FROM events JOIN hm ON {HOST_EXPR} = hm.host
WHERE {_ANY_HOST}
GROUP BY ALL
LIMIT 1000000"""  # noqa: S608  # fixed SQL text; domains checked against DOMAIN in _values


def first_services_sql(pairs: list[tuple[str, str]]) -> str:
    """When each service was first seen in the events in scope: for a closed day too large
    for the rollup, so the first-seen index still has it (F63)."""
    return f"""
WITH {_match_ctes(pairs)}
SELECT hm.service_id, min(coalesce(time, time_observed)) AS first_t
FROM events JOIN hm ON {HOST_EXPR} = hm.host
WHERE {_ANY_HOST}
GROUP BY 1
LIMIT 5000"""  # noqa: S608  # fixed SQL text; domains checked against DOMAIN in _values


def _use_ctes(pairs: list[tuple[str, str]], rollup: bool) -> str:
    """Events reduced to service, person, machine, address, and hour, with rows that name
    only an address given the person and machine that had it at the time, from logon and
    User-ID events (ADR-0020 row 1). Ends in `r`, one row per service, person, machine,
    and hour.

    Shaped for memory (install finding F46): hosts are matched to the catalog once per
    distinct host, events are reduced to one row per service, person, machine, address,
    and hour before anything else, and the address lookup joins that small result. No
    step holds a row per event, so a week of busy DNS fits a small per-query budget.

    With `rollup`, the days listed in `$covered` ("source|YYYY-MM-DD") come from the daily
    AI rollup and only the rest is read from events (ADR-0035 rows 3 and 8). The engine
    leaves those days' files out of `events` altogether (`skip_days`), so closed days are
    never scanned again, not even to be filtered out (F63)."""
    from_rollup = (
        """
  UNION ALL
  SELECT service_id, source_id, who0, shost, ip, dev, t, n, first_t, last_t FROM ai_rollup
  WHERE (source_id || '|' || strftime(t, '%Y-%m-%d')) IN (SELECT unnest($covered))
    AND t >= $fact_lo AND t <= $fact_hi
  UNION ALL
  SELECT service_id, source_id, who0, shost, ip, dev, t, n, first_t, last_t FROM ai_today
  WHERE (source_id || '|' || label) IN (SELECT unnest($covered))
    AND t >= $fact_lo AND t <= $fact_hi"""
        if rollup
        else ""
    )
    return f"""{_match_ctes(pairs)},
hj AS (
  SELECT hm.service_id, source_id, {_HOUR_ROWS}
  FROM events JOIN hm ON {HOST_EXPR} = hm.host
  WHERE {_ANY_HOST}
  GROUP BY ALL{from_rollup}
),
{address_ctes("hj", "who0 IS NULL OR shost IS NULL", kept=rollup)},
r AS (
  SELECT service_id, hj.source_id, n, first_t, last_t, hj.t, coalesce(who0, addr.rwho) AS who,
         coalesce(shost, addr.rhost, hj.ip, dev) AS machine
  FROM hj {join_addr("hj")}
)"""  # noqa: S608  # fixed SQL text; domains checked against DOMAIN in _values


# The page fills these with the window's bounds (ADR-0039); AI use is counted by hour.
_DRILL_BOUNDS = "t >= TIMESTAMPTZ '{from}' AND t < TIMESTAMPTZ '{to}'"
_DRILL_SELECT = {
    # One row per service: what the services card and a chart day count.
    "services": (
        "SELECT service_id, sum(n)::BIGINT AS events, count(DISTINCT who) AS people,\n"
        "       count(DISTINCT machine) AS devices, min(first_t) AS first_seen,"
        " max(last_t) AS last_seen\nFROM r\nWHERE {bounds}\nGROUP BY 1 ORDER BY events DESC"
    ),
    # One row per person: the people card.
    "people": (
        "SELECT who AS person, list(DISTINCT service_id ORDER BY service_id) AS services,\n"
        "       sum(n)::BIGINT AS events, max(last_t) AS last_seen\nFROM r\n"
        "WHERE who IS NOT NULL AND {bounds}\nGROUP BY 1 ORDER BY events DESC"
    ),
    # Devices seen with no person in the window: the people card's "more devices" line.
    "devices": (
        "SELECT machine AS device, list(DISTINCT service_id ORDER BY service_id) AS services,\n"
        "       sum(n)::BIGINT AS events, max(last_t) AS last_seen\nFROM r\n"
        "WHERE machine IS NOT NULL AND {bounds}\nGROUP BY 1\nHAVING count(who) = 0\n"
        "ORDER BY events DESC"
    ),
}


def drill_pairs(table: list[tuple[str, str]], ids: set[str]) -> list[tuple[str, str]]:
    """The catalog rows a drill needs: the services' own domains, and any more specific
    domain of another service under them (it takes the match, as in the full catalog)."""
    mine = [d for sid, d in table if sid in ids]
    return [(sid, d) for sid, d in table if sid in ids or any(d.endswith("." + m) for m in mine)]


def drill_sql(table: list[tuple[str, str]], ids: set[str], kind: str) -> str:
    """Search SQL for an AI Watch number (ADR-0039): the same use rows as the card, read
    from events (Search has no rollup), for these services only so the query stays
    readable."""
    wanted = "[" + ", ".join("'" + i.replace("'", "''") + "'" for i in sorted(ids)) + "]"
    bounds = f"list_contains({wanted}, service_id) AND {_DRILL_BOUNDS}"
    select = _DRILL_SELECT[kind].replace("{bounds}", bounds)
    return f"WITH {_use_ctes(drill_pairs(table, ids), False).strip()}\n{select}"


def services_sql(pairs: list[tuple[str, str]], rollup: bool = False) -> str:
    """Use per service (see `_use_ctes`)."""
    return f"""
WITH {_use_ctes(pairs, rollup)}
SELECT service_id, sum(n)::BIGINT AS events, count(DISTINCT who) AS people,
       count(DISTINCT machine) AS machines, min(first_t) AS first_seen,
       max(last_t) AS last_seen,
       list_slice(list(DISTINCT who ORDER BY who) FILTER (WHERE who IS NOT NULL), 1, 5) AS top,
       list_slice(list(DISTINCT machine ORDER BY machine) FILTER (WHERE machine IS NOT NULL), 1, 5)
FROM r
GROUP BY 1 ORDER BY 2 DESC
LIMIT 500"""  # noqa: S608  # fixed SQL text; domains checked against DOMAIN in _values


def daily_sql(pairs: list[tuple[str, str]], rollup: bool = False) -> str:
    """Use per service, person, machine, and UTC day: what AI Watch's cards and 30-day
    chart are counted from (ADR-0035 rows 10, 12). Person and machine stay apart, so a
    count never adds people and devices together (owner, 2026-10-22)."""
    return f"""
WITH {_use_ctes(pairs, rollup)}
SELECT service_id, who, machine, CAST(timezone($tz, t) AS DATE) AS day,
       sum(n)::BIGINT AS events, max(last_t) AS last_seen, min(first_t) AS first_seen
FROM r
GROUP BY 1, 2, 3, 4
LIMIT 500000"""  # noqa: S608  # fixed SQL text; domains checked against DOMAIN in _values


def review_sql(pairs: list[tuple[str, str]], rollup: bool = False) -> str:
    """Per service: the sources it was seen in, its people, and its machines, for the AI
    watch's review items (ADR-0035 row 11)."""
    return f"""
WITH {_use_ctes(pairs, rollup)}
SELECT service_id, list(DISTINCT source_id) AS sources,
       list(DISTINCT who) FILTER (WHERE who IS NOT NULL) AS people,
       list(DISTINCT machine) FILTER (WHERE machine IS NOT NULL AND who IS NULL) AS devices,
       list(DISTINCT machine) FILTER (WHERE machine IS NOT NULL AND who IS NOT NULL) AS matched
FROM r
GROUP BY 1
LIMIT 500"""  # noqa: S608  # fixed SQL text; domains checked against DOMAIN in _values


# MCP servers seen by Claude Code telemetry, the MCP inventory, and the hooks plugin
# (D151, owner 2026-11-01). Presence (first and last seen, people, machines) joins the
# three by server name. Calls come from one source per session: telemetry when it saw the
# session, otherwise the hook records, so a session both report is never counted twice. A
# hook record sent twice (offline queue) is one record (`_ONE_COPY` in ai/sessions.py).
_HOOK_ONE_COPY = """hooks AS (
  SELECT * FROM events
  WHERE template_id = 'claude_hooks'
    AND json_extract_string(unmapped, '$.attr.mcp_server_name') IS NOT NULL
  QUALIFY json_extract_string(unmapped, '$.attr.seq') IS NULL OR row_number() OVER (
    PARTITION BY json_extract_string(unmapped, '$.attr.install_id'),
                 json_extract_string(unmapped, '$.attr.seq')
    ORDER BY time_observed, event_id) = 1
)"""
_MCP_ROWS = f"""{_HOOK_ONE_COPY},
t AS (
  SELECT {MCP_EXPR} AS name, {WHO_EXPR} AS who, device_hostname AS machine,
         coalesce(time, time_observed) AS ts, 'telemetry' AS src,
         CASE WHEN message = 'claude_code.tool_result' THEN 1 ELSE 0 END AS call,
         CAST(NULL AS VARCHAR) AS client, source_id, classification,
         json_extract_string(unmapped, '$.attr.session_id') AS session
  FROM events
  WHERE template_id = 'claude_code_otel' AND {MCP_EXPR} IS NOT NULL
  UNION ALL
  SELECT message, {WHO_EXPR}, device_hostname, coalesce(time, time_observed), 'inventory', 0,
         coalesce(json_extract_string(unmapped, '$.client'),
                  json_extract_string(unmapped, '$.attr.client')), source_id, classification,
         NULL
  FROM events WHERE template_id = 'mcp_inventory' AND message IS NOT NULL
  UNION ALL
  SELECT json_extract_string(unmapped, '$.attr.mcp_server_name'), {WHO_EXPR}, device_hostname,
         coalesce(time, time_observed), 'hooks',
         CASE WHEN message = 'claude_hooks.pre_tool_use' THEN 1 ELSE 0 END, NULL, source_id,
         classification, json_extract_string(unmapped, '$.attr.session_id')
  FROM hooks
),
tele AS (SELECT DISTINCT session FROM t WHERE src = 'telemetry' AND session IS NOT NULL)"""  # noqa: S608  # fixed SQL text

# One closed day's MCP rows, for the rollup's mcp.parquet (D151).
MCP_DAY_SQL = f"""
WITH {_MCP_ROWS}
SELECT name, src, session, who, machine, client, sum(call)::BIGINT, min(ts), max(ts),
       source_id, any_value(classification)
FROM t WHERE name IS NOT NULL
GROUP BY name, src, session, who, machine, client, source_id
LIMIT 200000"""  # noqa: S608  # fixed SQL text


def mcp_sql(rollup: bool) -> str:
    """MCP servers in use (see MCP_SQL). With `rollup`, closed days listed in
    `$mcp_days` ("source|day") come from the rollup's MCP rows, and only the rest (today,
    days not built yet) from events (owner, 2026-11-01: the AI inventory read every hook
    record)."""
    if not rollup:
        return MCP_SQL
    return f"""
WITH {_MCP_ROWS},
u AS (
  SELECT name, src, session, who, machine, client, call AS calls, ts AS first_t, ts AS last_t
  FROM t
  UNION ALL
  SELECT name, src, session, who, machine, client, calls, first_t, last_t FROM ai_mcp
  WHERE (source_id || '|' || day) IN (SELECT unnest($mcp_days))
),
tele_all AS (SELECT DISTINCT session FROM u WHERE src = 'telemetry' AND session IS NOT NULL)
SELECT name,
       coalesce(sum(calls) FILTER (WHERE src <> 'hooks' OR session IS NULL
                                   OR session NOT IN (SELECT session FROM tele_all)), 0),
       list(DISTINCT who) FILTER (WHERE who IS NOT NULL) AS people,
       count(DISTINCT machine) AS machines,
       count(DISTINCT CASE WHEN src = 'inventory' THEN machine END) AS installs,
       list(DISTINCT client) FILTER (WHERE client IS NOT NULL) AS clients,
       min(first_t) AS first_seen, max(last_t) AS last_seen, list(DISTINCT src) AS sources
FROM u WHERE lower(name) NOT IN {NO_MCP_NAMES}
GROUP BY 1 ORDER BY 2 DESC, 3 DESC
LIMIT 500"""  # noqa: S608  # fixed SQL text


MCP_SQL = f"""
WITH {_MCP_ROWS}
SELECT name,
       coalesce(sum(call) FILTER (WHERE src <> 'hooks' OR session IS NULL
                                  OR session NOT IN (SELECT session FROM tele)), 0) AS calls,
       list(DISTINCT who) FILTER (WHERE who IS NOT NULL) AS people,
       count(DISTINCT machine) AS machines,
       count(DISTINCT CASE WHEN src = 'inventory' THEN machine END) AS installs,
       list(DISTINCT client) FILTER (WHERE client IS NOT NULL) AS clients,
       min(ts) AS first_seen, max(ts) AS last_seen, list(DISTINCT src) AS sources
FROM t WHERE lower(name) NOT IN {NO_MCP_NAMES}
GROUP BY 1 ORDER BY 2 DESC, 3 DESC
LIMIT 500"""  # noqa: S608  # fixed SQL text

# Per MCP server: the sources it was seen in, its people, and its machines (with and
# without a person), for the AI watch's review items (ADR-0035 row 11, D116). Hook-only
# servers are included, so one added through a hooks-only client is reviewed (D151).
REVIEW_MCP_SQL = f"""
WITH {_MCP_ROWS}
SELECT name, list(DISTINCT source_id) AS sources,
       list(DISTINCT who) FILTER (WHERE who IS NOT NULL) AS people,
       list(DISTINCT machine) FILTER (WHERE machine IS NOT NULL AND who IS NULL) AS devices,
       list(DISTINCT machine) FILTER (WHERE machine IS NOT NULL AND who IS NOT NULL) AS matched
FROM t WHERE lower(name) NOT IN {NO_MCP_NAMES}
GROUP BY 1
LIMIT 500"""  # noqa: S608  # fixed SQL text

# Claude Code per person from telemetry and the hooks plugin (owner, 2026-11-02: a person
# seen only through hooks is a Claude Code user too). Sessions, tool calls, and errors come
# from one source per session: telemetry when it saw the session, else the hook records
# (as D151 counts MCP calls), so a session both report is counted once. Cost, tokens, and
# models come from telemetry only. `via` says which sent anything.
PEOPLE_SQL = f"""
WITH c AS (
  SELECT nullif(actor_user_name, '') AS person, message,
         TRY_CAST(json_extract_string(unmapped, '$.value') AS DOUBLE) AS value,
         json_extract_string(unmapped, '$.attr.session_id') AS session,
         json_extract_string(unmapped, '$.attr.model') AS model,
         TRY_CAST(json_extract_string(unmapped, '$.attr.sensitive_total') AS BIGINT) AS sens,
         status_id
  FROM events WHERE template_id = 'claude_code_otel'
),
seen AS (SELECT DISTINCT session FROM c WHERE session IS NOT NULL),
h AS (
  SELECT nullif(actor_user_name, '') AS person, message,
         json_extract_string(unmapped, '$.attr.session_id') AS session
  FROM events WHERE template_id = 'claude_hooks'
    -- Claude Code's own bookkeeping is not a tool call (D186).
    AND {counted("json_extract_string(unmapped, '$.attr.tool_name')")}
),
hk AS (
  SELECT person,
         count(DISTINCT session)
           FILTER (WHERE session NOT IN (SELECT session FROM seen)) AS sessions,
         count(*) FILTER (WHERE message = 'claude_hooks.pre_tool_use'
           AND coalesce(session NOT IN (SELECT session FROM seen), true)) AS tools,
         count(*) FILTER (WHERE message = 'claude_hooks.post_tool_use_failure'
           AND coalesce(session NOT IN (SELECT session FROM seen), true)) AS errors
  FROM h WHERE person IS NOT NULL GROUP BY 1
),
tel AS (
  SELECT person,
         round(coalesce(sum(value) FILTER (WHERE message = 'claude_code.cost.usage'
           AND isfinite(value) AND value >= 0 AND value <= 1000000), 0), 4) AS usd,
         CAST(coalesce(sum(value) FILTER (WHERE message = 'claude_code.token.usage'
           AND isfinite(value) AND value >= 0 AND value < 1e15), 0) AS BIGINT) AS tokens,
         count(DISTINCT session) AS sessions,
         count(*) FILTER (WHERE message = 'claude_code.tool_result') AS tools,
         count(*) FILTER (WHERE message = 'claude_code.api_error') AS errors,
         coalesce(sum(sens), 0) AS sensitive,
         list(DISTINCT model) FILTER (WHERE model IS NOT NULL) AS models
  FROM c WHERE person IS NOT NULL GROUP BY 1
)
SELECT coalesce(tel.person, hk.person) AS person,
       coalesce(tel.usd, 0), coalesce(tel.tokens, 0),
       coalesce(tel.sessions, 0) + coalesce(hk.sessions, 0),
       coalesce(tel.tools, 0) + coalesce(hk.tools, 0),
       coalesce(tel.errors, 0) + coalesce(hk.errors, 0),
       coalesce(tel.sensitive, 0), coalesce(tel.models, []),
       list_filter(['telemetry', 'hooks'], x -> (x = 'telemetry' AND tel.person IS NOT NULL)
                                               OR (x = 'hooks' AND hk.person IS NOT NULL)) AS via
FROM tel FULL OUTER JOIN hk ON tel.person = hk.person
ORDER BY 2 DESC, 3 DESC, 4 DESC
LIMIT 1000"""  # noqa: S608  # fixed SQL text


def fact_range(scope: QueryScope, upto: datetime) -> dict[str, datetime]:
    """The hours of rollup facts a range reads (they are per hour): a day only partly in
    range keeps its hours in range, so the first day of a week is not counted whole, and
    today's build before the start is left out (2026-11-01)."""
    lo = scope.start or datetime(1970, 1, 1, tzinfo=UTC)
    return {"fact_lo": lo.replace(minute=0, second=0, microsecond=0), "fact_hi": upto}


class Usage:
    def __init__(self, engine: QueryEngine, catalog: Catalog, rollup: Any = None) -> None:
        self._engine = engine
        self._catalog = catalog
        # The daily AI rollup (ADR-0035 row 8): ranges of 2 days or more read closed days
        # from it. `Any` to avoid an import cycle (app.ai.rollup imports this module).
        self._rollup = rollup
        # The page cache (`app.api.cache.PageCache`): AI usage and the inventory ask the
        # same questions, so they share answers for 60 s (owner, 2026-11-01: /ai then
        # /ai/inventory ran it twice). Emptied by any change in the app, like the pages.
        self.cache: Any = None

    def _memo(self, key: tuple[Any, ...], compute: Any) -> Any:
        if self.cache is None:
            return compute()
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        value = compute()
        self.cache.put(key, value)
        return value

    @staticmethod
    def _scope_key(scope: QueryScope) -> tuple[Any, ...]:
        return (
            None if scope.sources is None else tuple(sorted(scope.sources)),
            scope.start,
            scope.end,
        )

    def _rows(self, sql: str, scope: QueryScope) -> list[list[Any]]:
        return self._engine.run(sql, scope, timeout_s=TIMEOUT_S, page=True).rows

    def services(self, scope: QueryScope) -> tuple[list[ServiceUse], list[str]]:
        """Use per service, plus the sources read. Non-usage hosts are left out."""
        found, sources = self.all_services(scope)
        return [u for u in found if u.service.kind != NON_USAGE], sources

    def all_services(self, scope: QueryScope) -> tuple[list[ServiceUse], list[str]]:
        """Every catalog match, non-usage hosts included, plus the sources read."""
        key = ("usage.all_services", self._catalog_key(), *self._scope_key(scope))
        return self._memo(key, lambda: self._all_services(scope))  # type: ignore[no-any-return]  # what _all_services returns

    def _catalog_key(self) -> Any:
        """The catalog and the rollup's state: a rebuilt day or today's build is a new key."""
        rollup = self._rollup
        if rollup is None:
            return None
        return (rollup.catalog_key(), getattr(rollup, "generation", 0))

    def _all_services(self, scope: QueryScope) -> tuple[list[ServiceUse], list[str]]:
        known = {s.id: s for s in self._catalog.services()}
        result = self._run_use(services_sql, scope, "ai_use.services")
        out = []
        for sid, events, people, machines, first, last, top, top_m in result.rows:
            if sid in known:
                out.append(
                    ServiceUse(
                        known[sid],
                        int(events),
                        int(people),
                        int(machines),
                        first,
                        last,
                        list(top or []),
                        list(top_m or []),
                    )
                )
        return out, result.sources

    def _run_use(
        self,
        build: Any,
        scope: QueryScope,
        name: str = "ai_use",
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Run a use query, reading closed days from the rollup for ranges of 2 days or
        more when it has them (ADR-0035 row 8). A range with a start and no end (the AI
        usage page sends only a start) uses the rollup's closed days too, and still reads
        everything after the start, events stamped ahead of the clock included."""
        upto = scope.end or datetime.now(UTC)
        covered: list[str] = []
        keys: list[str] = []
        after = None
        if self._rollup is not None and scope.start is not None:
            if upto - scope.start >= timedelta(days=2):
                covered = self._rollup.covered(replace(scope, end=upto))
            # Today so far, for any range that reaches today (D136).
            part = self._rollup.today(replace(scope, end=upto))
            keys = covered + (part[0] if part else [])
            after = (part[1], part[2]) if part else None
        if keys:
            return self._engine.run(
                build(self._catalog.domain_table(), rollup=True),
                scope,
                {"covered": keys, **fact_range(scope, upto), **(params or {})},
                timeout_s=TIMEOUT_S,
                rollup=True,
                skip_days=covered,
                name=name,
                after=after,
                page=True,
            )
        return self._engine.run(
            build(self._catalog.domain_table()), scope, params or None, timeout_s=TIMEOUT_S,
            name=name, page=True,
        )  # fmt: skip

    def people_pending(self, scope: QueryScope) -> tuple[int, int]:
        """(days still being re-checked for who had an address, days read from the rollup)
        in the range: until a day is re-checked, its AI use shows without people."""
        upto = scope.end or datetime.now(UTC)
        if self._rollup is None or scope.start is None or upto - scope.start < timedelta(days=2):
            return 0, 0
        covered = self._rollup.covered(replace(scope, end=upto))
        pending = {c.split("|")[1] for c in covered if self._rollup.pending([c])}
        return len(pending), len({c.split("|")[1] for c in covered})

    def first_seen(self, sources: list[str] | None) -> dict[str, datetime]:
        """When each service, MCP server, and agent was first seen in the closed days the
        rollup has indexed ("service:<id>", "mcp:<name>", "agent:<key>"); empty without
        the rollup (F63)."""
        return {} if self._rollup is None else dict(self._rollup.first_seen(sources))

    def review(self, scope: QueryScope) -> list[list[Any]]:
        """(service id, sources, people, devices without a person, devices with one)."""
        return list(self._run_use(review_sql, scope, "ai_use.review").rows)

    def review_mcp(self, scope: QueryScope) -> list[list[Any]]:
        """(server name, sources, people, devices without a person, devices with one)."""
        return list(self._engine.run(REVIEW_MCP_SQL, scope, timeout_s=TIMEOUT_S, page=True).rows)

    def daily(self, scope: QueryScope, tz: str = "UTC") -> tuple[list[list[Any]], list[str]]:
        """(service id, person, machine, day, events, last seen, first seen) rows, and the
        sources read. Days are the viewer's (`tz`)."""
        result = self._run_use(daily_sql, scope, "ai_use.daily", {"tz": tz})
        return result.rows, result.sources

    def changes(
        self,
        services: list[ServiceUse],
        mcp: list[McpUse],
        before: QueryScope,
        ident: IdentityMap | None = None,
    ) -> tuple[Changes, list[str]]:
        """Compare the range with `before`: what is new in it, and what was seen before it
        and not in it (an approved service nobody uses any more is worth a review). Returns
        the sources read for the earlier period too."""
        old_services, sources = self.services(before)
        old_mcp = self.mcp(before, ident)
        now_s = {u.service.id for u in services}
        now_m = {m.name for m in mcp}
        was_s = {u.service.id for u in old_services}
        was_m = {m.name for m in old_mcp}
        gone = [
            Gone("service", u.service.id, u.service.name, u.service.status, u.last_seen)
            for u in old_services
            if u.service.id not in now_s
        ] + [
            Gone("mcp", m.name, m.name, m.status, m.last_seen)
            for m in old_mcp
            if m.name not in now_m
        ]
        return (
            Changes(
                new_services=sorted(now_s - was_s),
                new_mcp=sorted(now_m - was_m),
                gone=sorted(gone, key=lambda g: (g.status != "approved", g.kind, g.name)),
                earlier=len(was_s) + len(was_m),
            ),
            sources,
        )

    def claude_network_people(self, scope: QueryScope) -> list[NetUse]:
        """People seen reaching a Claude service (vendor Anthropic in the catalog) on the
        network: DNS, firewall, or proxy records (owner, 2026-11-02)."""
        ids = sorted(s.id for s in self._catalog.services() if s.vendor == "Anthropic")
        if not ids:
            return []
        wanted = "[" + ", ".join("'" + i.replace("'", "''") + "'" for i in ids) + "]"

        def build(pairs: list[tuple[str, str]], rollup: bool = False) -> str:
            return (
                f"WITH {_use_ctes(pairs, rollup)}\n"
                "SELECT who, list(DISTINCT service_id ORDER BY service_id), sum(n),"
                " count(DISTINCT machine), max(last_t)"
                f" FROM r WHERE who IS NOT NULL AND list_contains({wanted}, service_id)"
                " GROUP BY 1 LIMIT 100000"
            )

        result = self._run_use(build, scope, "ai_use.claude_people")
        names = {s.id: s.name for s in self._catalog.services()}
        return [
            NetUse(
                str(who), [names.get(str(s), str(s)) for s in sids or []], int(n or 0),
                int(devs or 0), last.isoformat() if isinstance(last, datetime) else (
                    str(last) if last else None),
            )
            for who, sids, n, devs, last in result.rows
        ]  # fmt: skip

    def unreviewed_use(self, scope: QueryScope) -> list[tuple[str | None, str | None]]:
        """(person, machine) pairs seen using an AI service nobody has reviewed yet, on the
        network (People and devices ranking, D195)."""
        ids = sorted(
            s.id for s in self._catalog.services()
            if s.status == "unreviewed" and s.kind != NON_USAGE
        )  # fmt: skip
        if not ids:
            return []
        wanted = "[" + ", ".join("'" + i.replace("'", "''") + "'" for i in ids) + "]"

        def build(pairs: list[tuple[str, str]], rollup: bool = False) -> str:
            return (
                f"WITH {_use_ctes(pairs, rollup)}\n"
                f"SELECT DISTINCT who, machine FROM r WHERE list_contains({wanted}, service_id)"
                " LIMIT 100000"
            )

        result = self._run_use(build, scope, "ai_use.unreviewed_people")
        return [
            (None if w is None else str(w), None if m is None else str(m)) for w, m in result.rows
        ]

    def mcp(self, scope: QueryScope, ident: IdentityMap | None = None) -> list[McpUse]:
        """MCP servers in use. People are counted once across names (`alice` from the
        inventory and `alice@example.com` from telemetry are one person, QA F4)."""
        who = None if ident is None else (
            tuple(ident.domains), tuple(sorted(ident.aliases.items())),
            tuple(sorted(ident.email_people)),
        )  # fmt: skip
        del who
        return self.mcp_and_sources(scope, ident)[0]

    def _mcp_rows(self, scope: QueryScope) -> tuple[list[list[Any]], list[str]]:
        """MCP_SQL's rows: closed days the rollup has MCP rows for come from there, the rest
        (today, days not built yet) from events (D151)."""
        days: list[str] = []
        if self._rollup is not None and scope.start is not None:
            days = self._rollup.mcp_covered(replace(scope, end=scope.end or datetime.now(UTC)))
        if not days:
            res = self._engine.run(MCP_SQL, scope, timeout_s=TIMEOUT_S, name="ai_mcp", page=True)
        else:
            res = self._engine.run(
                mcp_sql(True), scope, {"mcp_days": days}, timeout_s=TIMEOUT_S, rollup=True,
                skip_days=days, name="ai_mcp", page=True,
            )  # fmt: skip
        return list(res.rows), list(res.sources)

    def mcp_sources(self, scope: QueryScope, ident: IdentityMap | None = None) -> list[str]:
        """The sources the MCP list was read from (for the audit row)."""
        return self.mcp_and_sources(scope, ident)[1]

    def mcp_and_sources(
        self, scope: QueryScope, ident: IdentityMap | None = None
    ) -> tuple[list[McpUse], list[str]]:
        """`mcp`, and the sources read for it."""
        who = None if ident is None else (
            tuple(ident.domains), tuple(sorted(ident.aliases.items())),
            tuple(sorted(ident.email_people)),
        )  # fmt: skip
        key = ("usage.mcp+read", self._catalog_key(), who, *self._scope_key(scope))

        return self._memo(key, lambda: self._mcp(scope, ident))  # type: ignore[no-any-return]  # what _mcp returns

    def _mcp(
        self, scope: QueryScope, ident: IdentityMap | None = None
    ) -> tuple[list[McpUse], list[str]]:
        rules = self._catalog.mcp_rules()
        out = []
        rows, read = self._mcp_rows(scope)
        for row in rows:
            name, calls, people, machines, installs, clients, first, last, sources = row
            out.append(
                McpUse(
                    name=str(name),
                    status=self._catalog.mcp_status(str(name), rules),
                    calls=int(calls or 0),
                    people=len({ident.key(str(p)) if ident else str(p) for p in people or []}),
                    machines=int(machines),
                    installs=int(installs),
                    clients=sorted(str(c) for c in (clients or [])),
                    first_seen=first,
                    last_seen=last,
                    sources=sorted(str(s) for s in (sources or [])),
                )
            )
        return out, read

    def people(self, scope: QueryScope, ident: IdentityMap | None = None) -> list[PersonUse]:
        """Claude usage per person; names that are one person are added up (ADR-0018).
        Sessions add up too, since one session is reported under one name."""
        rows = self._people(scope)
        if ident is None:
            return rows
        merged: dict[str, PersonUse] = {}
        email: dict[str, bool] = {}
        for r in rows:
            key = ident.key(r.person)
            email[key] = email.get(key, False) or ident.org_email(r.person)
            cur = merged.get(key)
            if cur is None:
                merged[key] = PersonUse(key, r.cost_usd, r.tokens, r.sessions, r.tool_calls,
                                        r.errors, r.sensitive, list(r.models),
                                        via=list(r.via))  # fmt: skip
                continue
            cur.via = sorted(set(cur.via) | set(r.via))
            cur.cost_usd = round(cur.cost_usd + r.cost_usd, 4)
            cur.tokens += r.tokens
            cur.sessions += r.sessions
            cur.tool_calls += r.tool_calls
            cur.errors += r.errors
            cur.sensitive += r.sensitive
            cur.models = sorted(set(cur.models) | set(r.models))
        for key, p in merged.items():
            p.person = ident.display(key, email[key])
        return sorted(merged.values(), key=lambda p: (-p.cost_usd, -p.tokens))

    def _people(self, scope: QueryScope) -> list[PersonUse]:
        return [
            PersonUse(
                person=str(p),
                cost_usd=float(usd or 0),
                tokens=int(tokens or 0),
                sessions=int(sessions),
                tool_calls=int(tools),
                errors=int(errors),
                sensitive=int(sens or 0),
                models=sorted(str(m) for m in (models or [])),
                via=[str(v) for v in (via or [])],
            )
            for p, usd, tokens, sessions, tools, errors, sens, models, via in self._rows(
                PEOPLE_SQL, scope
            )
        ]


def seen_through(
    people: list[PersonUse], network: list[NetUse] | list[str], ident: IdentityMap | None = None
) -> tuple[list[PersonUse], dict[str, int]]:
    """Each Claude user with how they were seen (owner, 2026-11-02): "plugin" (telemetry
    or the hooks plugin), "network" (DNS, firewall, or proxy to a Claude service), or
    "both". People seen only on the network are added with no plugin numbers, so a Claude
    Code user missing the plugin (or a browser-only user) shows up. Returns the people and
    the count of each."""

    def key(name: str) -> str:
        return ident.key(name) if ident else name.lower()

    from app.search.timeline import related  # timeline imports this module

    net: dict[str, NetUse] = {}
    for n in network:
        u = n if isinstance(n, NetUse) else NetUse(n)
        cur = net.get(key(u.who))
        if cur is None:
            net[key(u.who)] = NetUse(u.who, list(u.services), u.lookups, u.devices, u.last_seen)
            continue
        cur.services = sorted(set(cur.services) | set(u.services))
        cur.lookups += u.lookups
        cur.devices += u.devices
        cur.last_seen = max(filter(None, [cur.last_seen, u.last_seen]), default=None)
    out: list[PersonUse] = []
    seen: set[str] = set()
    for p in people:
        k = key(p.person)
        seen.add(k)
        p.seen_through = "both" if k in net else "plugin"
        p.network = net.get(k)
        out.append(p)
    for k, u in sorted(net.items()):
        if k in seen:
            continue
        shown = ident.display(k, ident.org_email(u.who)) if ident else u.who
        # A network name no plugin person matches, that reads as one of them ("dana" and
        # "dana.lee@example.com"): the hint offers the alias in Identities.
        maybe = next((p.person for p in people if related(k, key(p.person))), None)
        out.append(
            PersonUse(shown, 0.0, 0, 0, 0, 0, 0, [], seen_through="network", network=u, maybe=maybe)
        )
    counts = {c: sum(1 for p in out if p.seen_through == c) for c in ("both", "plugin", "network")}
    return out, counts
