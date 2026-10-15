"""AI usage page API (ADR-0015 rows 1, 7, 8, 9). Router only.

Usage numbers come from the caller's own events view and reading them is audited
(`ai.view`). Review status, MCP rules, and the AI watch are admin changes, audited.
"""

from dataclasses import fields
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.ai.catalog import Catalog, Service, ServiceDef
from app.ai.usage import Usage
from app.ai.watch import AiWatch
from app.api.access import AdminUser, CurrentUser, client_ip
from app.auth.service import AuthService
from app.auth.users import User
from app.engine.duckdb import QueryScope
from app.engine.views import permitted_sources, scope_sources
from app.meta.db import MetaDB

router = APIRouter(tags=["ai"])

Status = Literal["approved", "not_approved", "unreviewed"]


class ServiceOut(BaseModel):
    id: str
    name: str
    vendor: str
    kind: str
    domains: list[str]
    status: Status
    custom: bool
    note: str


class ServiceUseOut(BaseModel):
    service: ServiceOut
    events: int
    people: int
    machines: int
    first_seen: str | None
    last_seen: str | None
    top_people: list[str]
    top_machines: list[str]


class McpUseOut(BaseModel):
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


class PersonOut(BaseModel):
    person: str
    cost_usd: float
    tokens: int
    sessions: int
    tool_calls: int
    errors: int
    sensitive: int
    models: list[str]


class UsageOut(BaseModel):
    services: list[ServiceUseOut]
    mcp: list[McpUseOut]
    people: list[PersonOut]
    sources_in_scope: list[str]


def _catalog(request: Request) -> Catalog:
    c: Catalog = request.app.state.ai_catalog
    return c


def _audit(request: Request) -> AuthService:
    a: AuthService = request.app.state.auth
    return a


def _service_out(s: Service) -> ServiceOut:
    return ServiceOut(
        id=s.id,
        name=s.name,
        vendor=s.vendor,
        kind=s.kind,
        domains=list(s.domains),
        status=s.status,
        custom=s.custom,
        note=s.note,
    )


async def _scope(
    request: Request, user: User, start: datetime | None, end: datetime | None
) -> QueryScope:
    meta: MetaDB = request.app.state.meta
    allowed = await run_in_threadpool(permitted_sources, meta, user)
    return QueryScope(sources=scope_sources(allowed, None), start=start, end=end)


@router.get("/ai/usage")
async def ai_usage(
    request: Request, user: CurrentUser, start: datetime | None = None, end: datetime | None = None
) -> UsageOut:
    """Services, MCP servers, and Claude usage per person, from the sources the caller
    may read. Audited ai.view."""
    usage: Usage = request.app.state.ai_usage
    scope = await _scope(request, user, start, end)
    services, sources = await run_in_threadpool(usage.services, scope)
    mcp = await run_in_threadpool(usage.mcp, scope)
    ident = await run_in_threadpool(request.app.state.identities.load)
    people = await run_in_threadpool(usage.people, scope, ident)
    await run_in_threadpool(
        _audit(request).audit.write,
        "ai.view",
        "success",
        user.user_id,
        client_ip(request),
        {"sources_in_scope": sources},
    )
    return UsageOut(
        services=[
            ServiceUseOut(
                service=_service_out(u.service),
                events=u.events,
                people=u.people,
                machines=u.machines,
                first_seen=u.first_seen,
                last_seen=u.last_seen,
                top_people=u.top_people,
                top_machines=u.top_machines,
            )
            for u in services
        ],
        mcp=[McpUseOut(**_slots(m)) for m in mcp],
        people=[PersonOut(**_slots(p)) for p in people],
        sources_in_scope=sources,
    )


def _slots(obj: object) -> dict[str, Any]:
    """Fields of a slotted dataclass, for the response models."""
    return {f.name: getattr(obj, f.name) for f in fields(obj)}  # type: ignore[arg-type]  # dataclass instances only


@router.get("/ai/catalog")
async def ai_catalog(request: Request, _: CurrentUser) -> list[ServiceOut]:
    return [_service_out(s) for s in await run_in_threadpool(_catalog(request).services)]


class StatusIn(BaseModel):
    status: Status
    note: str = Field(default="", max_length=500)


@router.put("/ai/services/{service_id}/status")
async def set_service_status(
    service_id: str, body: StatusIn, request: Request, user: AdminUser
) -> ServiceOut:
    before = await run_in_threadpool(
        _catalog(request).set_status, service_id, body.status, body.note, user.user_id
    )
    await run_in_threadpool(
        _audit(request).audit.write,
        "ai.service_change",
        "success",
        user.user_id,
        client_ip(request),
        {"service_id": service_id, "from": before, "to": body.status},
    )
    (svc,) = [s for s in await run_in_threadpool(_catalog(request).services) if s.id == service_id]
    return _service_out(svc)


@router.post("/ai/services", status_code=status.HTTP_201_CREATED)
async def add_service(body: ServiceDef, request: Request, user: AdminUser) -> ServiceOut:
    await run_in_threadpool(_catalog(request).add_custom, body, user.user_id)
    await run_in_threadpool(
        _audit(request).audit.write,
        "ai.service_change",
        "success",
        user.user_id,
        client_ip(request),
        {"service_id": body.id, "added": body.model_dump()},
    )
    (svc,) = [s for s in await run_in_threadpool(_catalog(request).services) if s.id == body.id]
    return _service_out(svc)


@router.delete("/ai/services/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service(service_id: str, request: Request, user: AdminUser) -> Response:
    await run_in_threadpool(_catalog(request).delete_custom, service_id)
    await run_in_threadpool(
        _audit(request).audit.write,
        "ai.service_change",
        "success",
        user.user_id,
        client_ip(request),
        {"service_id": service_id, "removed": True},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class McpRuleOut(BaseModel):
    pattern: str
    status: Literal["approved", "not_approved"]
    note: str
    updated_at: str
    updated_by: str | None


class McpRuleIn(BaseModel):
    pattern: str = Field(min_length=1, max_length=121)
    status: Literal["approved", "not_approved"] | None  # null removes the rule
    note: str = Field(default="", max_length=500)


@router.get("/ai/mcp-rules")
async def mcp_rules(request: Request, _: CurrentUser) -> list[McpRuleOut]:
    return [McpRuleOut(**_slots(r)) for r in await run_in_threadpool(_catalog(request).mcp_rules)]


@router.put("/ai/mcp-rules")
async def set_mcp_rule(body: McpRuleIn, request: Request, user: AdminUser) -> list[McpRuleOut]:
    await run_in_threadpool(
        _catalog(request).set_mcp_rule, body.pattern, body.status, body.note, user.user_id
    )
    await run_in_threadpool(
        _audit(request).audit.write,
        "ai.mcp_change",
        "success",
        user.user_id,
        client_ip(request),
        {"pattern": body.pattern, "to": body.status},
    )
    return [McpRuleOut(**_slots(r)) for r in await run_in_threadpool(_catalog(request).mcp_rules)]


class WatchOut(BaseModel):
    enabled: bool
    include_unreviewed: bool
    sensitive: bool
    target_ids: list[str]
    updated_at: str | None
    updated_by: str | None


class WatchIn(BaseModel):
    enabled: bool
    include_unreviewed: bool = False
    sensitive: bool = True
    target_ids: list[str] = Field(default_factory=list, max_length=10)


@router.get("/ai/watch")
async def get_watch(request: Request, _: AdminUser) -> WatchOut:
    watch: AiWatch = request.app.state.ai_watch
    return WatchOut(**_slots(await run_in_threadpool(watch.settings)))


@router.put("/ai/watch")
async def put_watch(body: WatchIn, request: Request, user: AdminUser) -> WatchOut:
    watch: AiWatch = request.app.state.ai_watch
    s = await run_in_threadpool(
        watch.configure,
        body.enabled,
        body.include_unreviewed,
        body.sensitive,
        body.target_ids,
        user.user_id,
        client_ip(request),
    )
    return WatchOut(**_slots(s))
