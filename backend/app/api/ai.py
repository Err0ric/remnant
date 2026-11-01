"""AI usage page API (ADR-0015 rows 1, 7, 8, 9). Router only.

Usage numbers come from the caller's own events view and reading them is audited
(`ai.view`). Review status, MCP rules, and the AI watch are admin changes, audited.
"""

import asyncio
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.ai.accounts import accounts
from app.ai.agents import agents
from app.ai.agents_overview import overview as agents_overview
from app.ai.catalog import NON_USAGE, Catalog, DataLevel, Service, ServiceDef
from app.ai.inventory import Exclusions, inventory
from app.ai.inventory import export as inventory_export
from app.ai.sessions import sessions, timeline
from app.ai.usage import ServiceUse, Usage
from app.ai.watch import AiWatch
from app.ai.watch_summary import source_classes
from app.ai.watch_summary import summary as watch_summary
from app.alerts.items import AlertItem, AlertItems
from app.api.access import AdminUser, CurrentUser, client_ip, require_role
from app.api.dashboard_sections import HistoryOut, KpiOut
from app.auth.service import AuthService
from app.auth.users import User
from app.core.errors import NotFoundError
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
    # "Rebuilding people for N of M days": closed days whose identity file is not written
    # yet show their AI use without people (owner, 2026-10-29).
    people_pending_days: int = 0
    people_days: int = 0


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
    ident = await run_in_threadpool(request.app.state.identities.load)
    # The independent reads at once: a page load waits for the slowest, not the sum.
    (found, sources), mcp, people, (pending, of) = await asyncio.gather(
        run_in_threadpool(usage.all_services, scope),
        run_in_threadpool(usage.mcp, scope, ident),
        run_in_threadpool(usage.people, scope, ident),
        run_in_threadpool(usage.people_pending, scope),
    )
    services = [u for u in found if u.service.kind != NON_USAGE]
    other = [u for u in found if u.service.kind == NON_USAGE]
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
        people_pending_days=pending,
        people_days=of,
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
    drill: str | None = None  # ADR-0039 templates with {from} and {to}
    drill_before: str | None = None
    devices_drill: str | None = None
    blocked_drill: str | None = None


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
    compared: bool = True  # False: under 90% of the period before has AI use data
    since: str | None = None
    before: str = ""
    chart_drill: str | None = None
    people_pending_days: int = 0  # see UsageOut
    people_days: int = 0


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
    now = request.app.state.ai_watch.now()
    pending, of = await run_in_threadpool(
        request.app.state.ai_usage.people_pending,
        QueryScope(allowed, now - timedelta(days=30), now),
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
        compared=s.compared,
        since=s.since,
        before=s.before,
        chart_drill=s.chart_drill,
        people_pending_days=pending,
        people_days=of,
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
    request: Request,
    user: CurrentUser,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
    person: Annotated[str | None, Query(max_length=256)] = None,
) -> list[SessionOut]:
    """Recent Claude Code and Cowork sessions from the hooks plugin (ADR-0026), newest
    first, from the sources the caller may read; with `person`, only that person's under
    any form of the name (ADR-0038 row 27). Audited ai.view."""
    meta: MetaDB = request.app.state.meta
    allowed = await run_in_threadpool(permitted_sources, meta, user)
    engine: QueryEngine = request.app.state.engine
    rows = await run_in_threadpool(sessions, engine, allowed, datetime.now(UTC), days)
    if person:
        ident = await run_in_threadpool(request.app.state.identities.load)
        keys = set(ident.keys_for(person))
        rows = [s for s in rows if s.person and ident.key(s.person) in keys]
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


class AccountRowOut(BaseModel):
    email: str | None
    tier: str
    account_from: str | None
    devices: list[str]
    os_users: list[str]
    sessions: int
    first_seen: str | None
    last_seen: str | None
    evidence: str


class AccountsOut(BaseModel):
    days: int
    domains_set: bool
    has_signins: bool
    rows: list[AccountRowOut]
    counts: dict[str, int]


@router.get("/agents/accounts")
async def agents_accounts(
    request: Request, user: CurrentUser, days: Annotated[int, Query(ge=1, le=90)] = 30
) -> AccountsOut:
    """Claude accounts the hooks plugin reported, by tier (ADR-0030 amendment): company
    confirmed by an Entra sign-in, company reported, company not confirmed, personal, or not
    checked; each with its evidence. Audited ai.view."""
    meta: MetaDB = request.app.state.meta
    allowed = await run_in_threadpool(permitted_sources, meta, user)
    srcs = [
        (s.source_id, s.kind or "file", s.template_id) for s in request.app.state.sources.list()
    ]
    kinds = source_classes(srcs)

    def mine(ids: list[str]) -> list[str]:
        return ids if allowed is None else [s for s in ids if s in set(allowed)]

    domains = (await run_in_threadpool(request.app.state.identities.load)).domains
    out = await run_in_threadpool(
        accounts,
        request.app.state.engine,
        allowed,
        mine(kinds.get("telemetry", [])),
        mine(kinds.get("m365", [])),
        domains,
        datetime.now(UTC),
        days,
    )
    await run_in_threadpool(
        _audit(request).audit.write,
        "ai.view",
        "success",
        user.user_id,
        client_ip(request),
        {"sources_in_scope": out.sources, "view": "accounts"},
    )
    return AccountsOut(
        days=out.days,
        domains_set=out.domains_set,
        has_signins=out.has_signins,
        rows=[AccountRowOut(**_slots(r)) for r in out.rows],
        counts=out.counts,
    )


class ToolRowOut(BaseModel):
    tool: str
    mcp: bool
    status: str
    people: int
    devices: int
    calls: int
    failed: int
    first_seen: str | None
    last_seen: str | None
    drill: str


class AgentsOverviewOut(BaseModel):
    days: int
    start: str
    end: str
    before: str
    has_source: bool
    history: HistoryOut
    sessions: KpiOut | None
    people: KpiOut | None
    calls: KpiOut | None
    failed: KpiOut | None
    mcp_not_approved: KpiOut | None
    late_devices: KpiOut | None
    missing_devices: list[str]
    tools: list[ToolRowOut]


@router.get("/agents/overview")
async def agents_overview_get(
    request: Request, user: CurrentUser, days: Annotated[int, Query(ge=1, le=90)] = 7
) -> AgentsOverviewOut:
    """Agents > Overview and Tools (ADR-0038 section 6): sessions, people, tool calls,
    failures, MCP servers not approved, late or silent devices, and one row per tool, from
    the hooks plugin sources the caller may read. Audited ai.view."""
    meta: MetaDB = request.app.state.meta
    allowed = await run_in_threadpool(permitted_sources, meta, user)
    srcs = [
        (s.source_id, s.kind or "file", s.template_id) for s in request.app.state.sources.list()
    ]
    telemetry = source_classes(srcs).get("telemetry", [])
    if allowed is not None:
        telemetry = [s for s in telemetry if s in set(allowed)]
    out = await run_in_threadpool(
        agents_overview,
        request.app.state.engine,
        _catalog(request),
        telemetry,
        datetime.now(UTC),
        days,
    )
    await run_in_threadpool(
        _audit(request).audit.write,
        "ai.view",
        "success",
        user.user_id,
        client_ip(request),
        {"sources_in_scope": out.sources, "view": "agents_overview"},
    )

    def kpi(k: Any) -> KpiOut | None:
        return KpiOut(**_slots(k)) if k is not None else None

    return AgentsOverviewOut(
        days=out.days,
        start=out.start,
        end=out.end,
        before=out.before,
        has_source=out.has_source,
        history=HistoryOut(
            compared=out.history.compared,
            since=out.history.since,
        ),
        sessions=kpi(out.sessions),
        people=kpi(out.people),
        calls=kpi(out.calls),
        failed=kpi(out.failed),
        mcp_not_approved=kpi(out.mcp_not_approved),
        late_devices=kpi(out.late_devices),
        missing_devices=out.missing_devices,
        tools=[ToolRowOut(**_slots(t)) for t in out.tools],
    )


InventoryType = Literal["service", "agent", "mcp", "m365_app"]
Exporter = Annotated[User, Depends(require_role("admin", "analyst"))]


class ExclusionOut(BaseModel):
    reason: str
    by: str
    at: str


class InventoryItemOut(BaseModel):
    type: InventoryType
    key: str
    name: str
    status: Status | None
    people: int
    devices: int | None
    first_seen: str | None
    last_seen: str | None
    where: list[str]
    excluded: ExclusionOut | None


class InventoryOut(BaseModel):
    days: int
    items: list[InventoryItemOut]
    sources_in_scope: list[str]


class ExcludeIn(BaseModel):
    type: InventoryType
    key: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=500)


async def _inventory(request: Request, user: User, days: int) -> tuple[list[Any], list[str]]:
    meta: MetaDB = request.app.state.meta
    allowed = await run_in_threadpool(permitted_sources, meta, user)
    ident = await run_in_threadpool(request.app.state.identities.load)
    excluded = await run_in_threadpool(Exclusions(meta).all)
    return await run_in_threadpool(
        inventory,
        request.app.state.engine,
        request.app.state.ai_usage,
        _catalog(request),
        allowed,
        ident,
        excluded,
        datetime.now(UTC),
        days,
    )


def _item_out(i: Any) -> InventoryItemOut:
    d = _slots(i)
    d["excluded"] = ExclusionOut(**_slots(i.excluded)) if i.excluded else None
    return InventoryItemOut(**d)


@router.get("/ai/inventory")
async def ai_inventory(
    request: Request, user: CurrentUser, days: Annotated[int, Query(ge=1, le=90)] = 30
) -> InventoryOut:
    """Everything AI seen (ADR-0038 section 7): services, agents, MCP servers, and
    Microsoft 365 apps with a granted consent, each with its exclusion if any. Audited
    ai.view."""
    items, sources = await _inventory(request, user, days)
    await run_in_threadpool(
        _audit(request).audit.write, "ai.view", "success", user.user_id, client_ip(request),
        {"sources_in_scope": sources, "view": "inventory"},
    )  # fmt: skip
    return InventoryOut(days=days, items=[_item_out(i) for i in items], sources_in_scope=sources)


@router.get("/ai/inventory/export")
async def ai_inventory_export(
    request: Request,
    user: Exporter,
    format: Literal["csv", "json"] = "csv",  # the query parameter's name
    days: Annotated[int, Query(ge=1, le=90)] = 30,
    type: InventoryType | None = None,  # the query parameter's name
    excluded: bool = False,
) -> Response:
    """The current view as a file (row 22): admins and analysts only, every export
    audited `ai.inventory_export` with its filters and row count."""
    items, sources = await _inventory(request, user, days)
    rows = [
        i for i in items
        if (type is None or i.type == type) and (i.excluded is not None) == excluded
    ]  # fmt: skip
    body = inventory_export(rows, format)
    await run_in_threadpool(
        _audit(request).audit.write, "ai.inventory_export", "success", user.user_id,
        client_ip(request),
        {"format": format, "days": days, "type": type, "excluded": excluded,
         "rows": len(rows), "sources_in_scope": sources},
    )  # fmt: skip
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    return Response(
        body,
        media_type="text/csv" if format == "csv" else "application/json",
        headers={"Content-Disposition": f'attachment; filename="ai-inventory-{stamp}.{format}"'},
    )


@router.put("/ai/inventory/exclusions")
async def ai_inventory_exclude(body: ExcludeIn, request: Request, user: AdminUser) -> ExclusionOut:
    """Move an item to Excluded with a reason (row 21). It still shows in Search, alerts,
    and AI Watch. Audited ai.inventory_exclude."""
    meta: MetaDB = request.app.state.meta
    ex = await run_in_threadpool(
        Exclusions(meta).set, body.type, body.key, body.reason, user.username
    )
    await run_in_threadpool(
        _audit(request).audit.write, "ai.inventory_exclude", "success", user.user_id,
        client_ip(request), {"type": body.type, "key": body.key[:200], "reason": ex.reason},
    )  # fmt: skip
    return ExclusionOut(**_slots(ex))


@router.delete("/ai/inventory/exclusions", status_code=status.HTTP_204_NO_CONTENT)
async def ai_inventory_include(
    request: Request,
    user: AdminUser,
    type: InventoryType,  # the query parameter's name
    key: Annotated[str, Query(min_length=1, max_length=500)],
) -> Response:
    """Move an item back to Active. Audited ai.inventory_include."""
    meta: MetaDB = request.app.state.meta
    found = await run_in_threadpool(Exclusions(meta).clear, type, key)
    if not found:
        raise NotFoundError("That item is not excluded")
    await run_in_threadpool(
        _audit(request).audit.write, "ai.inventory_include", "success", user.user_id,
        client_ip(request), {"type": type, "key": key[:200]},
    )  # fmt: skip
    return Response(status_code=status.HTTP_204_NO_CONTENT)
