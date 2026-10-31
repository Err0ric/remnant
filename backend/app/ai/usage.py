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
  WHERE list_contains($covered, source_id || '|' || strftime(t, '%Y-%m-%d'))"""
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
SELECT service_id, who, machine, CAST(t AS DATE) AS day,
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
SELECT name, sum(call) AS calls, list(DISTINCT who) FILTER (WHERE who IS NOT NULL) AS people,
       count(DISTINCT machine) AS machines,
       count(DISTINCT CASE WHEN src = 'inventory' THEN machine END) AS installs,
       list(DISTINCT client) FILTER (WHERE client IS NOT NULL) AS clients,
       min(ts) AS first_seen, max(ts) AS last_seen, list(DISTINCT src) AS sources
FROM t WHERE lower(name) NOT IN {NO_MCP_NAMES}
GROUP BY 1 ORDER BY 2 DESC, 3 DESC
LIMIT 500"""  # noqa: S608  # fixed SQL text; domains checked against DOMAIN in _values

# Per MCP server: the sources it was seen in, its people, and its machines (with and
# without a person), for the AI watch's review items (ADR-0035 row 11, D116).
REVIEW_MCP_SQL = f"""
WITH t AS (
  SELECT {MCP_EXPR} AS name, {WHO_EXPR} AS who, device_hostname AS machine, source_id
  FROM events
  WHERE template_id = 'claude_code_otel' AND {MCP_EXPR} IS NOT NULL
  UNION ALL
  SELECT message, {WHO_EXPR}, device_hostname, source_id
  FROM events WHERE template_id = 'mcp_inventory' AND message IS NOT NULL
)
SELECT name, list(DISTINCT source_id) AS sources,
       list(DISTINCT who) FILTER (WHERE who IS NOT NULL) AS people,
       list(DISTINCT machine) FILTER (WHERE machine IS NOT NULL AND who IS NULL) AS devices,
       list(DISTINCT machine) FILTER (WHERE machine IS NOT NULL AND who IS NOT NULL) AS matched
FROM t WHERE lower(name) NOT IN {NO_MCP_NAMES}
GROUP BY 1
LIMIT 500"""  # noqa: S608  # fixed SQL text

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
       round(coalesce(sum(value) FILTER (WHERE message = 'claude_code.cost.usage'
         AND isfinite(value) AND value >= 0 AND value <= 1000000), 0), 4) AS usd,
       CAST(coalesce(sum(value) FILTER (WHERE message = 'claude_code.token.usage'
         AND isfinite(value) AND value >= 0 AND value < 1e15), 0) AS BIGINT),
       count(DISTINCT session) AS sessions,
       count(*) FILTER (WHERE message = 'claude_code.tool_result') AS tools,
       count(*) FILTER (WHERE message = 'claude_code.api_error') AS errors,
       coalesce(sum(sens), 0) AS sensitive,
       list(DISTINCT model) FILTER (WHERE model IS NOT NULL) AS models
FROM c WHERE person IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC, 3 DESC
LIMIT 1000"""


class Usage:
    def __init__(self, engine: QueryEngine, catalog: Catalog, rollup: Any = None) -> None:
        self._engine = engine
        self._catalog = catalog
        # The daily AI rollup (ADR-0035 row 8): ranges of 2 days or more read closed days
        # from it. `Any` to avoid an import cycle (app.ai.rollup imports this module).
        self._rollup = rollup

    def _rows(self, sql: str, scope: QueryScope) -> list[list[Any]]:
        return self._engine.run(sql, scope, timeout_s=TIMEOUT_S).rows

    def services(self, scope: QueryScope) -> tuple[list[ServiceUse], list[str]]:
        """Use per service, plus the sources read. Non-usage hosts are left out."""
        found, sources = self.all_services(scope)
        return [u for u in found if u.service.kind != NON_USAGE], sources

    def all_services(self, scope: QueryScope) -> tuple[list[ServiceUse], list[str]]:
        """Every catalog match, non-usage hosts included, plus the sources read."""
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

    def _run_use(self, build: Any, scope: QueryScope, name: str = "ai_use") -> Any:
        """Run a use query, reading closed days from the rollup for ranges of 2 days or
        more when it has them (ADR-0035 row 8). A range with a start and no end (the AI
        usage page sends only a start) uses the rollup's closed days too, and still reads
        everything after the start, events stamped ahead of the clock included."""
        upto = scope.end or datetime.now(UTC)
        covered: list[str] = []
        if (
            self._rollup is not None
            and scope.start is not None
            and upto - scope.start >= timedelta(days=2)
        ):
            covered = self._rollup.covered(replace(scope, end=upto))
        if covered:
            return self._engine.run(
                build(self._catalog.domain_table(), rollup=True),
                scope,
                {"covered": covered},
                timeout_s=TIMEOUT_S,
                rollup=True,
                skip_days=covered,
                name=name,
            )
        return self._engine.run(
            build(self._catalog.domain_table()), scope, timeout_s=TIMEOUT_S, name=name
        )

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
        return list(self._engine.run(REVIEW_MCP_SQL, scope, timeout_s=TIMEOUT_S).rows)

    def daily(self, scope: QueryScope) -> tuple[list[list[Any]], list[str]]:
        """(service id, person, machine, day, events, last seen, first seen) rows, and the
        sources read."""
        result = self._run_use(daily_sql, scope, "ai_use.daily")
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

    def mcp(self, scope: QueryScope, ident: IdentityMap | None = None) -> list[McpUse]:
        """MCP servers in use. People are counted once across names (`alice` from the
        inventory and `alice@example.com` from telemetry are one person, QA F4)."""
        rules = self._catalog.mcp_rules()
        out = []
        for row in self._rows(MCP_SQL, scope):
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
