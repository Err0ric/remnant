"""Entity risk and the investigator graph (ADR-0016 rows 4, 5, 7). Router only.

Numbers come from the caller's own events view; reading them is audited
(`investigate.risk`, `investigate.graph`) with the sources read.
"""

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.ai.catalog import Catalog
from app.api.access import CurrentUser, client_ip
from app.auth.service import AuthService
from app.core.errors import SearchInvalidError
from app.engine.duckdb import QueryEngine, QueryScope
from app.engine.views import permitted_sources
from app.enrich.geoip import GeoIP
from app.meta.db import MetaDB
from app.search.entities import ai_graph, entity_graph, entity_risk, to_json
from app.search.entity_summary import entity_summary
from app.search.identity import IdentityMap, IdentityStore
from app.search.lookup import lookup

router = APIRouter(tags=["investigate"])


class RiskOut(BaseModel):
    kind: Literal["user", "ip", "host"]
    value: str
    score: int
    critical: int
    high: int
    medium: int
    low: int
    flagged_runs: int
    events: int
    rules: list[str]
    search_sql: str
    names: list[str]  # users: the logged names counted as this person (ADR-0018)


class RiskResponse(BaseModel):
    users: list[RiskOut]
    ips: list[RiskOut]
    hosts: list[RiskOut]
    matches_considered: int
    sources: list[str]


class CardOut(BaseModel):
    id: str
    lane: int
    label: str
    sublabel: str
    events: int
    matches: int
    max_severity: int
    badges: list[str]
    search_sql: str | None
    group: str


class EdgeOut(BaseModel):
    source: str
    target: str
    events: int


class ActivityOut(BaseModel):
    outcome: str
    kind: str
    user: str | None
    target: str | None
    events: int
    first: str | None
    last: str | None
    example: str
    search_sql: str


class TargetOut(BaseModel):
    kind: str
    value: str
    events: int


class GeoBrief(BaseModel):
    country: str | None = None
    country_name: str | None = None
    asn: int | None = None
    org: str | None = None


class SummaryOut(BaseModel):
    kind: str
    value: str
    events: int
    sign_ins: int
    succeeded: int
    failed: int
    users: int
    hosts: int
    addresses: int
    service_addresses: int = 0
    first_seen: str | None
    last_seen: str | None
    sources: list[str]
    activities: list[ActivityOut]
    targets: list[TargetOut]
    search_sql: str
    geo: GeoBrief | None = None


class LookupHit(BaseModel):
    kind: Literal["ip", "user", "host", "service"]
    value: str
    label: str
    events: int | None
    last_seen: str | None
    geo: GeoBrief | None = None
    aliases: list[str] = []  # other forms of the same person (ADR-0018)


class LookupOut(BaseModel):
    hits: list[LookupHit]
    days: int


class GraphOut(BaseModel):
    mode: Literal["entity", "ai"]
    lanes: list[str]
    cards: list[CardOut]
    edges: list[EdgeOut]
    more: list[int]
    sources: list[str]


async def _scope(
    request: Request, user: CurrentUser, start: datetime | None, end: datetime | None
) -> tuple[list[str] | None, QueryScope]:
    allowed = await run_in_threadpool(permitted_sources, request.app.state.meta, user)
    return allowed, QueryScope(sources=allowed, start=start, end=end)


async def _identities(request: Request) -> IdentityMap:
    store: IdentityStore = request.app.state.identities
    return await run_in_threadpool(store.load)


async def _audit(
    request: Request, user: CurrentUser, action: str, detail: dict[str, object]
) -> None:
    auth: AuthService = request.app.state.auth
    await run_in_threadpool(
        auth.audit.write, action, "success", user.user_id, client_ip(request), detail
    )


@router.get("/entities/risk")
async def risk(
    request: Request,
    user: CurrentUser,
    start: datetime | None = None,
    end: datetime | None = None,
) -> RiskResponse:
    """Users, source IPs, and hosts ranked by rule matches and flagged schedule runs."""
    allowed, scope = await _scope(request, user, start, end)
    engine: QueryEngine = request.app.state.engine
    meta: MetaDB = request.app.state.meta
    ident = await _identities(request)
    ranked, considered, read = await run_in_threadpool(
        entity_risk, engine, meta, allowed, scope, ident
    )
    await _audit(request, user, "investigate.risk", {"sources_in_scope": read})
    return RiskResponse(
        users=[RiskOut(**to_json(r)) for r in ranked["user"]],
        ips=[RiskOut(**to_json(r)) for r in ranked["ip"]],
        hosts=[RiskOut(**to_json(r)) for r in ranked["host"]],
        matches_considered=considered,
        sources=read,
    )


@router.get("/entities/graph")
async def graph(
    request: Request,
    user: CurrentUser,
    mode: Literal["entity", "ai"] = "entity",
    kind: Literal["user", "ip", "host", "mcp", "service"] | None = None,
    value: str | None = Query(default=None, max_length=512),
    start: datetime | None = None,
    end: datetime | None = None,
) -> GraphOut:
    """Entity mode: Entity, Sources, Activities, Targets. AI flow: People, AI clients,
    Tools and MCP servers, Destinations; optionally for one person, MCP server, or service."""
    allowed, scope = await _scope(request, user, start, end)
    engine: QueryEngine = request.app.state.engine
    if mode == "entity":
        if kind not in ("user", "ip", "host") or not value:
            raise SearchInvalidError("Pick a user, IP address, or host to investigate")
        meta: MetaDB = request.app.state.meta
        ident = await _identities(request)
        g = await run_in_threadpool(entity_graph, engine, meta, allowed, scope, kind, value, ident)
    else:
        if kind not in (None, "user", "mcp", "service") or (kind and not value):
            raise SearchInvalidError("AI flow is for a person, an MCP server, or an AI service")
        catalog: Catalog = request.app.state.ai_catalog
        ident = await _identities(request)
        g = await run_in_threadpool(
            ai_graph, engine, catalog, scope, kind, value, ident, request.app.state.ai_rollup
        )
    await _audit(
        request,
        user,
        "investigate.graph",
        {"mode": mode, "kind": kind, "value": (value or "")[:200], "sources_in_scope": g.sources},
    )
    return GraphOut(**to_json(g))


@router.get("/entities/summary")
async def summary(
    request: Request,
    user: CurrentUser,
    kind: Literal["user", "ip", "host"],
    value: str = Query(min_length=1, max_length=512),
    start: datetime | None = None,
    end: datetime | None = None,
) -> SummaryOut:
    """The top of an entity's page: counts, sign-in outcomes, who and what it touched,
    first and last seen, and activities by outcome with a real example line."""
    _allowed, scope = await _scope(request, user, start, end)
    engine: QueryEngine = request.app.state.engine
    ident = await _identities(request)
    s = await run_in_threadpool(entity_summary, engine, scope, kind, value, ident)
    geo = None
    if kind == "ip":
        geoip: GeoIP = request.app.state.geoip
        found = await run_in_threadpool(geoip.enrich, [value])
        if value in found:
            info = found[value]
            geo = GeoBrief(
                country=info.country,
                country_name=info.country_name,
                asn=info.asn,
                org=info.org,
            )
    await _audit(
        request,
        user,
        "investigate.summary",
        {"kind": kind, "value": value[:200], "sources_in_scope": s.read},
    )
    data = to_json(s)
    data.pop("read", None)
    return SummaryOut(**data, geo=geo)


LOOKUP_DAYS = 30


@router.get("/entities/lookup")
async def entity_lookup(
    request: Request,
    user: CurrentUser,
    q: str = Query(min_length=2, max_length=100),
    start: datetime | None = None,
    end: datetime | None = None,
) -> LookupOut:
    """The top bar search (ADR-0038 edit 10): addresses, users, and hosts seen in the
    caller's own sources (the last 30 days unless a range is given), and AI services by
    name."""
    end = end or datetime.now(UTC)
    start = start or end - timedelta(days=LOOKUP_DAYS)
    _allowed, scope = await _scope(request, user, start, end)
    engine: QueryEngine = request.app.state.engine
    catalog: Catalog = request.app.state.ai_catalog
    services = await run_in_threadpool(catalog.services)
    ident = await run_in_threadpool(request.app.state.identities.load)
    found = await run_in_threadpool(lookup, engine, scope, q, services, ident)
    geoip: GeoIP = request.app.state.geoip
    ips = [h.value for h in found.hits if h.kind == "ip"]
    geo = await run_in_threadpool(geoip.enrich, ips) if ips else {}
    await _audit(
        request,
        user,
        "investigate.lookup",
        {"q": q[:100], "sources_in_scope": found.read},
    )
    hits = []
    for h in found.hits:
        info = geo.get(h.value) if h.kind == "ip" else None
        hits.append(
            LookupHit(
                kind=h.kind,  # type: ignore[arg-type]  # one of the four, set in lookup()
                value=h.value,
                label=h.label,
                events=h.events,
                last_seen=h.last_seen,
                aliases=h.aliases,
                geo=GeoBrief(
                    country=info.country,
                    country_name=info.country_name,
                    asn=info.asn,
                    org=info.org,
                )
                if info
                else None,
            )
        )
    return LookupOut(hits=hits, days=LOOKUP_DAYS)
