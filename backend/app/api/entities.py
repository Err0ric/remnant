"""Entity risk and the investigator graph (ADR-0016 rows 4, 5, 7). Router only.

Numbers come from the caller's own events view; reading them is audited
(`investigate.risk`, `investigate.graph`) with the sources read.
"""

from datetime import datetime
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
from app.meta.db import MetaDB
from app.search.entities import ai_graph, entity_graph, entity_risk, to_json
from app.search.identity import IdentityMap, IdentityStore

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
        g = await run_in_threadpool(ai_graph, engine, catalog, scope, kind, value, ident)
    await _audit(
        request,
        user,
        "investigate.graph",
        {"mode": mode, "kind": kind, "value": (value or "")[:200], "sources_in_scope": g.sources},
    )
    return GraphOut(**to_json(g))
