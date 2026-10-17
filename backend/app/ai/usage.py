"""AI usage numbers (ADR-0015 rows 2, 6, 8): server-built SQL over the caller's events view.

Every query here is fixed text plus catalog domains (each checked against a strict
domain pattern before it is written into SQL) and runs through the engine and its guard
like any other, so people see only sources they may read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.ai.catalog import DOMAIN, Catalog, Service, Status
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
class PersonUse:
    person: str
    cost_usd: float
    tokens: int
    sessions: int
    tool_calls: int
    errors: int
    sensitive: int
    models: list[str]


def _values(pairs: list[tuple[str, str]]) -> str:
    rows = []
    for sid, domain in pairs:
        if not DOMAIN.fullmatch(domain) or not sid.replace("_", "").isalnum():
            continue  # never written into SQL unless it is a plain id and domain
        rows.append(f"('{sid}', '{domain}')")
    return ", ".join(rows) or "('none', 'none.invalid')"


# Public name for other server-built SQL (the investigator's AI flow) that needs the list.
catalog_values = _values


def services_sql(pairs: list[tuple[str, str]]) -> str:
    """Use per service. Rows that name only an address get the person and machine that
    had it at the time, from logon and User-ID events (ADR-0020 row 1)."""
    return f"""
WITH h AS (
  SELECT {HOST_EXPR} AS host, {WHO_EXPR} AS who0,
         nullif(src_endpoint_hostname, '') AS shost, nullif(src_endpoint_ip, '') AS ip,
         device_hostname AS dev, coalesce(time, time_observed) AS t
  FROM events
  WHERE coalesce({", ".join(_CANDIDATES)}) IS NOT NULL
),
cat(service_id, domain) AS (VALUES {_values(pairs)}),
{HOST_MATCH_SQL.format(src="h")},
hj AS (SELECT h.*, hm.service_id FROM h JOIN hm USING (host)),
{address_ctes("hj", "who0 IS NULL OR shost IS NULL")},
r AS (
  SELECT service_id, t, coalesce(who0, addr.rwho) AS who,
         coalesce(shost, addr.rhost, hj.ip, dev) AS machine
  FROM hj {join_addr("hj")}
)
SELECT service_id, count(*) AS events, count(DISTINCT who) AS people,
       count(DISTINCT machine) AS machines, min(t) AS first_seen, max(t) AS last_seen,
       list_slice(list(DISTINCT who ORDER BY who) FILTER (WHERE who IS NOT NULL), 1, 5) AS top,
       list_slice(list(DISTINCT machine ORDER BY machine) FILTER (WHERE machine IS NOT NULL), 1, 5)
FROM r
GROUP BY 1 ORDER BY 2 DESC
LIMIT 500"""  # noqa: S608  # fixed SQL text; domains checked against DOMAIN in _values


MCP_SQL = f"""
WITH t AS (
  SELECT {MCP_EXPR} AS name, {WHO_EXPR} AS who, device_hostname AS machine,
         coalesce(time, time_observed) AS ts, 'telemetry' AS src,
         CASE WHEN message = 'claude_code.tool_result' THEN 1 ELSE 0 END AS call,
         CAST(NULL AS VARCHAR) AS client
  FROM events
  WHERE template_id = 'claude_code_otel' AND {MCP_EXPR} IS NOT NULL
  UNION ALL
  SELECT message, {WHO_EXPR}, device_hostname, coalesce(time, time_observed), 'inventory', 0,
         coalesce(json_extract_string(unmapped, '$.client'),
                  json_extract_string(unmapped, '$.attr.client'))
  FROM events WHERE template_id = 'mcp_inventory' AND message IS NOT NULL
)
SELECT name, sum(call) AS calls, count(DISTINCT who) AS people,
       count(DISTINCT machine) AS machines,
       count(DISTINCT CASE WHEN src = 'inventory' THEN machine END) AS installs,
       list(DISTINCT client) FILTER (WHERE client IS NOT NULL) AS clients,
       min(ts) AS first_seen, max(ts) AS last_seen, list(DISTINCT src) AS sources
FROM t WHERE lower(name) NOT IN {NO_MCP_NAMES}
GROUP BY 1 ORDER BY 2 DESC, 3 DESC
LIMIT 500"""  # noqa: S608  # fixed SQL text; domains checked against DOMAIN in _values

PEOPLE_SQL = """
WITH c AS (
  SELECT nullif(actor_user_name, '') AS person, message,
         TRY_CAST(json_extract_string(unmapped, '$.value') AS DOUBLE) AS value,
         json_extract_string(unmapped, '$.attr.session_id') AS session,
         json_extract_string(unmapped, '$.attr.model') AS model,
         TRY_CAST(json_extract_string(unmapped, '$.attr.sensitive_total') AS BIGINT) AS sens,
         status_id
  FROM events WHERE template_id = 'claude_code_otel'
)
SELECT person,
       round(coalesce(sum(value) FILTER (WHERE message = 'claude_code.cost.usage'), 0), 4) AS usd,
       CAST(coalesce(sum(value) FILTER (WHERE message = 'claude_code.token.usage'), 0) AS BIGINT),
       count(DISTINCT session) AS sessions,
       count(*) FILTER (WHERE message = 'claude_code.tool_result') AS tools,
       count(*) FILTER (WHERE message = 'claude_code.api_error') AS errors,
       coalesce(sum(sens), 0) AS sensitive,
       list(DISTINCT model) FILTER (WHERE model IS NOT NULL) AS models
FROM c WHERE person IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC, 3 DESC
LIMIT 1000"""


class Usage:
    def __init__(self, engine: QueryEngine, catalog: Catalog) -> None:
        self._engine = engine
        self._catalog = catalog

    def _rows(self, sql: str, scope: QueryScope) -> list[list[Any]]:
        return self._engine.run(sql, scope, timeout_s=TIMEOUT_S).rows

    def services(self, scope: QueryScope) -> tuple[list[ServiceUse], list[str]]:
        """Use per service, plus the sources read."""
        known = {s.id: s for s in self._catalog.services()}
        result = self._engine.run(
            services_sql(self._catalog.domain_table()), scope, timeout_s=TIMEOUT_S
        )
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

    def mcp(self, scope: QueryScope) -> list[McpUse]:
        rules = self._catalog.mcp_rules()
        out = []
        for row in self._rows(MCP_SQL, scope):
            name, calls, people, machines, installs, clients, first, last, sources = row
            out.append(
                McpUse(
                    name=str(name),
                    status=self._catalog.mcp_status(str(name), rules),
                    calls=int(calls or 0),
                    people=int(people),
                    machines=int(machines),
                    installs=int(installs),
                    clients=sorted(str(c) for c in (clients or [])),
                    first_seen=first,
                    last_seen=last,
                    sources=sorted(str(s) for s in (sources or [])),
                )
            )
        return out

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
                                        r.errors, r.sensitive, list(r.models))  # fmt: skip
                continue
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
            )
            for p, usd, tokens, sessions, tools, errors, sens, models in self._rows(
                PEOPLE_SQL, scope
            )
        ]
