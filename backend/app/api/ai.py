"""AI usage page API (ADR-0015 rows 1, 7, 8, 9). Router only.

Usage numbers come from the caller's own events view and reading them is audited
(`ai.view`). Review status, MCP rules, and the AI watch are admin changes, audited.
"""

from dataclasses import fields
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request, Response, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.ai.agents import agents
from app.ai.catalog import NON_USAGE, Catalog, DataLevel, Service, ServiceDef
from app.ai.sessions import sessions, timeline
from app.ai.usage import ServiceUse, Usage
from app.ai.watch import AiWatch
from app.ai.watch_summary import source_classes
from app.ai.watch_summary import summary as watch_summary
from app.alerts.items import AlertItem, AlertItems
from app.api.access import AdminUser, CurrentUser, client_ip
from app.auth.service import AuthService
from app.auth.users import User
from app.engine.duckdb import QueryEngine, QueryScope
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
    data_level: DataLevel | None = None


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


class GoneOut(BaseModel):
    kind: Literal["service", "mcp"]
    id: str
    name: str
    status: Status
    last_seen: str | None


class UsageOut(BaseModel):
    services: list[ServiceUseOut]
    # Vendor hosts other sites load (ad and measurement tags): shown apart, not AI use.
    non_usage: list[ServiceUseOut] = []
    mcp: list[McpUseOut]
    people: list[PersonOut]
    sources_in_scope: list[str]
    # Compared with the period of the same length just before `start` (none without one).
    compared_from: str | None = None
    new_services: list[str] = []
    new_mcp: list[str] = []
    gone: list[GoneOut] = []


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
        data_level=s.data_level,
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
    may read; with a start, also what is new and what is no longer seen against the
    period of the same length before it. Audited ai.view."""
    usage: Usage = request.app.state.ai_usage
    scope = await _scope(request, user, start, end)
    found, sources = await run_in_threadpool(usage.all_services, scope)
    services = [u for u in found if u.service.kind != NON_USAGE]
    other = [u for u in found if u.service.kind == NON_USAGE]
    ident = await run_in_threadpool(request.app.state.identities.load)
    mcp = await run_in_threadpool(usage.mcp, scope, ident)
    changes, compared_from = None, None
    if start is not None:
        stop = end or datetime.now(UTC)
        earlier = start - (stop - start)
        # The scope's end is inclusive; stop just short of `start` so no event is in both.
        before = await _scope(request, user, earlier, start - timedelta(microseconds=1))
        changes, read_before = await run_in_threadpool(usage.changes, services, mcp, before, ident)
        sources = sorted(set(sources) | set(read_before))
        if changes.earlier:
            compared_from = earlier.isoformat()
        else:  # nothing at all before: every row would be "New" (QA F10), so no comparison
            changes = None
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
        services=[_use_out(u) for u in services],
        non_usage=[_use_out(u) for u in other],
        mcp=[McpUseOut(**_slots(m)) for m in mcp],
        people=[PersonOut(**_slots(p)) for p in people],
        sources_in_scope=sources,
        compared_from=compared_from,
        new_services=changes.new_services if changes else [],
        new_mcp=changes.new_mcp if changes else [],
        gone=[GoneOut(**_slots(g)) for g in changes.gone] if changes else [],
    )


def _use_out(u: ServiceUse) -> ServiceUseOut:
    return ServiceUseOut(
        service=_service_out(u.service),
        events=u.events,
        people=u.people,
        machines=u.machines,
        first_seen=u.first_seen,
        last_seen=u.last_seen,
        top_people=u.top_people,
        top_machines=u.top_machines,
    )


def _slots(obj: object) -> dict[str, Any]:
    """Fields of a slotted dataclass, for the response models."""
    return {f.name: getattr(obj, f.name) for f in fields(obj)}  # type: ignore[arg-type]  # dataclass instances only


class CardOut(BaseModel):
    key: str
    label: str
    value: int | None
    previous: int | None
    context: str
    needs: str | None
    restricted: bool
    devices: int | None = None  # people card: devices not matched to a person, apart
    unreviewed: int | None = None  # services card: still not reviewed
    blocked: int | None = None  # consent card: attempts a policy blocked, apart
    blocked_context: str = ""
    rows_sql: str | None = None  # Search SQL for the card's rows (consent card)
    blocked_sql: str | None = None


class DayOut(BaseModel):
    day: str
    approved: int
    unreviewed: int
    not_approved: int


class TopServiceOut(BaseModel):
    service_id: str
    name: str
    status: str
    people: int
    machines: int
    events: int
    first_seen: str | None
    last_seen: str | None


class NewOut(BaseModel):
    kind: str
    id: str
    name: str
    first_seen: str
    item_id: str | None


class WatchSummaryOut(BaseModel):
    days: int
    start: str
    end: str
    cards: list[CardOut]
    chart: list[DayOut]
    top: list[TopServiceOut]
    sources: list[str]
    new: list[NewOut] = []  # first seen in 24 hours, from the data (ADR-0037 row 6)


@router.get("/ai/watch/summary")
async def ai_watch_summary(
    request: Request, user: CurrentUser, days: Annotated[int, Query(ge=1, le=30)] = 7
) -> WatchSummaryOut:
    """AI Watch (ADR-0035 rows 10, 12, 13): five cards against the period before, AI use
    over 30 days by review status, and the top services, all on the caller's view.
    Audited ai.view."""
    meta: MetaDB = request.app.state.meta
    allowed = await run_in_threadpool(permitted_sources, meta, user)
    items_store: AlertItems = request.app.state.alert_items
    ai_items = [
        i
        for i in await run_in_threadpool(items_store.items, user, "all", 5000)
        if i.kind == "ai_watch"
    ]
    kinds = source_classes(
        [(s.source_id, s.kind or "file", s.template_id) for s in request.app.state.sources.list()]
    )

    def readable(i: AlertItem) -> bool:
        return allowed is None or set(i.sources) <= set(allowed)

    s = await run_in_threadpool(
        watch_summary,
        request.app.state.ai_usage,
        _catalog(request),
        request.app.state.engine,
        allowed,
        ai_items,
        readable,
        kinds,
        request.app.state.ai_watch.now(),
        days,
    )
    await run_in_threadpool(
        _audit(request).audit.write,
        "ai.view",
        "success",
        user.user_id,
        client_ip(request),
        {"sources_in_scope": s.sources, "view": "watch"},
    )
    return WatchSummaryOut(
        days=s.days,
        start=s.start,
        end=s.end,
        cards=[CardOut(**_slots(c)) for c in s.cards],
        chart=[DayOut(**_slots(d)) for d in s.chart],
        top=[TopServiceOut(**_slots(t)) for t in s.top],
        sources=s.sources,
        new=[NewOut(**_slots(n)) for n in s.new],
    )


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
    await run_in_threadpool(_answer_review, request, user, f"service:{service_id}", body.status)
    (svc,) = [s for s in await run_in_threadpool(_catalog(request).services) if s.id == service_id]
    return _service_out(svc)


def _answer_review(request: Request, user: User, subject: str, status: str) -> None:
    """Approving or not approving a service or MCP server answers its open review items on
    Alerts (ADR-0035 row 11): closed with the decision, audited as alert.close."""
    if status == "approved":
        reason, note = "benign", "Approved"
    elif status == "not_approved":
        reason, note = "true_positive", "Marked not approved"
    else:
        return
    items: AlertItems = request.app.state.alert_items
    items.close_subject("ai_watch", subject, user, reason, note, client_ip(request))


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
    await run_in_threadpool(_answer_mcp_reviews, request, user)
    return [McpRuleOut(**_slots(r)) for r in await run_in_threadpool(_catalog(request).mcp_rules)]


def _answer_mcp_reviews(request: Request, user: User) -> None:
    """A rule can cover many servers: each open MCP review item whose server the rules now
    decide is closed with that decision."""
    items: AlertItems = request.app.state.alert_items
    catalog = _catalog(request)
    rules = catalog.mcp_rules()
    for subject in items.open_subjects("ai_watch", "mcp:"):
        status = catalog.mcp_status(subject.removeprefix("mcp:"), rules)
        _answer_review(request, user, subject, status)


class WatchOut(BaseModel):
    enabled: bool
    include_unreviewed: bool
    sensitive: bool
    target_ids: list[str]
    updated_at: str | None
    updated_by: str | None
    agents: bool = False


class WatchIn(BaseModel):
    enabled: bool
    include_unreviewed: bool = False
    sensitive: bool = True
    target_ids: list[str] = Field(default_factory=list, max_length=10)
    agents: bool = False


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
        body.agents,
    )
    return WatchOut(**_slots(s))


class DataLevelIn(BaseModel):
    data_level: DataLevel | None  # null clears it


@router.put("/ai/services/{service_id}/data-level")
async def set_data_level(
    service_id: str, body: DataLevelIn, request: Request, user: AdminUser
) -> ServiceOut:
    """The most sensitive data allowed to this service (ADR-0020 row 4). Audited as
    ai.service_change."""
    before = await run_in_threadpool(
        _catalog(request).set_data_level, service_id, body.data_level, user.user_id
    )
    await run_in_threadpool(
        _audit(request).audit.write,
        "ai.service_change",
        "success",
        user.user_id,
        client_ip(request),
        {"service_id": service_id, "data_level": {"from": before, "to": body.data_level}},
    )
    (svc,) = [s for s in await run_in_threadpool(_catalog(request).services) if s.id == service_id]
    return _service_out(svc)


class AgentItemOut(BaseModel):
    kind: str
    name: str


class AgentOut(BaseModel):
    kind: str
    agent: str
    label: str
    owners: list[str]
    machine: str | None
    first_seen: str
    last_seen: str
    events_24h: int
    state: str
    new_items: list[AgentItemOut]
    usual_peak: int | None
    recent_peak: int | None


@router.get("/ai/agents")
async def ai_agents(request: Request, user: CurrentUser) -> list[AgentOut]:
    """AI agents (Claude Code per machine and person, MCP clients per machine, API keys)
    and what changed in the last 24 hours against the 30 days before, from the sources
    the caller may read. Audited ai.view."""
    meta: MetaDB = request.app.state.meta
    allowed = await run_in_threadpool(permitted_sources, meta, user)
    engine: QueryEngine = request.app.state.engine
    rows = await run_in_threadpool(agents, engine, allowed, datetime.now(UTC))
    await run_in_threadpool(
        _audit(request).audit.write,
        "ai.view",
        "success",
        user.user_id,
        client_ip(request),
        {"sources_in_scope": allowed, "view": "agents"},
    )
    return [AgentOut(**_slots(a)) for a in rows]


class SessionOut(BaseModel):
    session_id: str
    person: str | None
    machine: str | None
    started: str
    last: str
    prompts: int
    tool_calls: int
    tools: list[str]
    hosts: list[str]
    stopped: bool  # ended
    failed: int = 0  # tool calls that failed


class StepOut(BaseModel):
    time: str
    event: str
    role: str | None
    tool: str | None
    mcp_server: str | None
    mcp_tool: str | None
    path: str | None
    web_host: str | None
    program: str | None
    prompt_chars: int | None
    input_chars: int | None
    output_chars: int | None
    event_id: str
    late_s: int | None = None  # delivered this long after it happened (offline queue)


class TimelineOut(BaseModel):
    session_id: str
    person: str | None
    machine: str | None
    steps: list[StepOut]


@router.get("/ai/sessions")
async def ai_sessions(
    request: Request, user: CurrentUser, days: Annotated[int, Query(ge=1, le=90)] = 7
) -> list[SessionOut]:
    """Recent Claude Code and Cowork sessions from the hooks plugin (ADR-0026), newest
    first, from the sources the caller may read. Audited ai.view."""
    meta: MetaDB = request.app.state.meta
    allowed = await run_in_threadpool(permitted_sources, meta, user)
    engine: QueryEngine = request.app.state.engine
    rows = await run_in_threadpool(sessions, engine, allowed, datetime.now(UTC), days)
    await run_in_threadpool(
        _audit(request).audit.write,
        "ai.view",
        "success",
        user.user_id,
        client_ip(request),
        {"sources_in_scope": allowed, "view": "sessions"},
    )
    return [SessionOut(**_slots(s)) for s in rows]


@router.get("/ai/sessions/{session_id}")
async def ai_session(
    session_id: str,
    request: Request,
    user: CurrentUser,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> TimelineOut:
    """One session in order: start, prompts, each tool call and its result, stop. Audited
    ai.view with the session id."""
    meta: MetaDB = request.app.state.meta
    allowed = await run_in_threadpool(permitted_sources, meta, user)
    engine: QueryEngine = request.app.state.engine
    t = await run_in_threadpool(timeline, engine, allowed, session_id, datetime.now(UTC), days)
    await run_in_threadpool(
        _audit(request).audit.write,
        "ai.view",
        "success",
        user.user_id,
        client_ip(request),
        {"sources_in_scope": allowed, "view": "session", "session_id": session_id[:200]},
    )
    return TimelineOut(
        session_id=t.session_id,
        person=t.person,
        machine=t.machine,
        steps=[StepOut(**_slots(x)) for x in t.steps],
    )
