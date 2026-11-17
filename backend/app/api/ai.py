"""AI usage page API (ADR-0015 rows 1, 7, 8, 9). Router only.

Usage numbers come from the caller's own events view and reading them is audited
(`ai.view`). Review status, MCP rules, and the AI watch are admin changes, audited.
"""

import asyncio
from dataclasses import fields, replace
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.ai.accounts import accounts
from app.ai.agents import BASELINE_DAYS as AGENT_DAYS
from app.ai.agents import agents
from app.ai.agents import masked as masked_agents
from app.ai.agents_overview import overview as agents_overview
from app.ai.catalog import NON_USAGE, Catalog, DataLevel, Service, ServiceDef
from app.ai.inventory import Exclusions, inventory, not_approved, to_review
from app.ai.inventory import export as inventory_export
from app.ai.people_view import HIDDEN, audit_ai_view, can_view_people, mask_person, tie
from app.ai.person_ai import activity as person_activity
from app.ai.session_summary import summary as session_summary
from app.ai.sessions import sessions, timeline
from app.ai.usage import Earlier, ServiceUse, Usage, merge_people, seen_through
from app.ai.watch import AiWatch, describe
from app.ai.watch_summary import source_classes
from app.ai.watch_summary import summary as watch_summary
from app.alerts.items import AlertItem, AlertItems
from app.api.access import AdminUser, CurrentUser, client_ip, require_ai_people, require_role
from app.api.access import now as app_now
from app.api.cache import STALE_MAX_S, PageCache, Refresher, scope_key
from app.api.dashboard_sections import HistoryOut, KpiOut
from app.api.identities import caller_identities
from app.auth.service import AuthService
from app.auth.users import User
from app.core.errors import NotFoundError, ParamInvalidError
from app.core.job_status import Failure
from app.core.times import UtcDateTime
from app.engine.duckdb import QueryEngine, QueryScope
from app.engine.views import permitted_sources, scope_sources
from app.meta.db import MetaDB
from app.meta.page_loads import AI_WATCH, PageLoadAudit, declared

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


class NetUseOut(BaseModel):
    who: str
    services: list[str]
    lookups: int
    devices: int
    last_seen: str | None


class PersonOut(BaseModel):
    # The name, or for a viewer without View people in AI usage the machine (or "Hidden",
    # D242): `UsageOut.masked` says which.
    person: str
    # A stable row key that is never a name: the name when names are shown, else the row's
    # place, so two people on one machine stay two rows.
    key: str = ""
    cost_usd: float
    tokens: int
    # False: no cost or token metric arrived, so cost and tokens are unknown, not 0.
    cost_reported: bool = False
    sessions: int
    tool_calls: int
    errors: int
    sensitive: int
    models: list[str]
    # How this person was seen using Claude: plugin, network, or both (owner, 2026-11-02).
    seen_through: Literal["plugin", "network", "both"] = "plugin"
    via: list[str] = []  # telemetry, hooks
    network: NetUseOut | None = None  # what DNS, firewall, or proxy logs saw (D190)
    maybe: str | None = None  # a network name only: the plugin person it may be


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
    # Claude users by how they were seen: plugin only, network only (no plugin), and both.
    claude_seen: dict[str, int] = {}
    # True: person cells show machines (or "Hidden"), and top people and the "may be" hint
    # are left out, for a viewer without View people in AI usage (D242). Counts are the same.
    masked: bool = False


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


def _window(
    start: datetime | None, end: datetime | None, now: datetime, days: int, most_days: int = 90
) -> tuple[datetime | None, datetime | None]:
    """The window an Agents read covers (PR 639), by one rule on the server's clock: the
    last `most_days` of what was chosen. The end is the chosen end (never past now) or now;
    the start is the chosen start (or `days` before the end), never earlier than
    `most_days` before the end. Only an end before the start is refused. Neither side:
    (None, None), `days` back from now."""
    if start is None and end is None:
        return None, None
    stop = min(end or now, now)
    first = start if start is not None else stop - timedelta(days=days)
    if stop <= first:
        raise ParamInvalidError("The end is before the start")
    return max(first, stop - timedelta(days=most_days)), stop


async def _scope(
    request: Request, user: User, start: datetime | None, end: datetime | None
) -> QueryScope:
    meta: MetaDB = request.app.state.meta
    allowed = await run_in_threadpool(permitted_sources, meta, user)
    return QueryScope(sources=scope_sources(allowed, None), start=start, end=end)


@router.get("/ai/usage")
async def ai_usage(
    request: Request,
    user: CurrentUser,
    start: UtcDateTime | None = None,
    end: UtcDateTime | None = None,
) -> UsageOut:
    """Services, MCP servers, and Claude usage per person, from the sources the caller
    may read; with a start, also what is new and what is no longer seen against the
    period of the same length before it. Without View people in AI usage, machines stand in
    for names (D242). Audited ai.view_people when names are shown, else ai.view."""
    usage: Usage = request.app.state.ai_usage
    # Down to the minute, so a reload within a minute is the same question: kept 60 s,
    # cleared by any change in the app (owner, 2026-10-31).
    start = start.replace(second=0, microsecond=0) if start else None
    end = end.replace(second=0, microsecond=0) if end else None
    scope = await _scope(request, user, start, end)
    cache: PageCache = request.app.state.page_cache
    # Admin or not is part of the key: people are shown with the whole map or the part
    # the page's names show (D223). So is the permission: a named answer is never served
    # to a caller without it (D242).
    named_ok = can_view_people(user)
    key = ("ai_usage", scope_key(scope.sources), start, end, user.role == "admin", named_ok)
    audit, ip = _audit(request).audit, client_ip(request)
    hit = cache.get(key)
    if hit is not None:
        out, read = hit
        await run_in_threadpool(
            audit_ai_view, audit, user, ip, "ai.usage", start, end, read,
            named_ok and _has_names(out), cached=True,
        )  # fmt: skip
        return out  # type: ignore[no-any-return]  # a UsageOut this route stored
    full = await run_in_threadpool(request.app.state.identities.load)
    # With a start, the period of the same length before it, compared with the range below.
    earlier: datetime | None = None
    before: QueryScope | None = None
    if start is not None:
        stop = end or app_now(request)
        earlier = start - (stop - start)
        # The scope's end is inclusive; stop just short of `start` so no event is in both.
        before = await _scope(request, user, earlier, start - timedelta(microseconds=1))

    async def earlier_reads() -> Earlier | None:
        return None if before is None else await run_in_threadpool(usage.earlier, before, full)

    # The independent reads at once, the period before included: a page load waits for the
    # slowest, not the sum. MCP people are counted with `full`: a count over names the
    # caller's rows show adds up only names those rows link (T70); nothing from the map is
    # shown. The comparison uses only service and MCP server names, never people.
    (found, sources), mcp, rows, (pending, of), network, old = await asyncio.gather(
        run_in_threadpool(usage.all_services, scope),
        run_in_threadpool(usage.mcp, scope, full),
        run_in_threadpool(usage.people, scope),
        run_in_threadpool(usage.people_pending, scope),
        run_in_threadpool(usage.claude_network_people, scope),
        earlier_reads(),
    )
    # The shown names: the whole map for an administrator (D223); for anyone else only
    # the links and organization domains the page's own names show (T70, D219), so a
    # person is never given a domain the caller's events do not show. No scan.
    ident = full if user.role == "admin" else full.seen_in(
        [r.person for r in rows] + [n.who for n in network]
    )  # fmt: skip
    people, claude_seen = seen_through(merge_people(rows, ident), network, ident)
    services = [u for u in found if u.service.kind != NON_USAGE]
    other = [u for u in found if u.service.kind == NON_USAGE]
    changes, compared_from = None, None
    if old is not None and earlier is not None:
        changes, read_before = usage.compare(services, mcp, old)
        sources = sorted(set(sources) | set(read_before))
        if changes.earlier:
            compared_from = earlier.isoformat()
        else:  # nothing at all before: every row would be "New" (QA F10), so no comparison
            changes = None
    result = UsageOut(
        services=[_use_out(u) for u in services],
        non_usage=[_use_out(u) for u in other],
        mcp=[McpUseOut(**_slots(m)) for m in mcp],
        people=[
            PersonOut(**{**_slots(p), "network": _slots(p.network) if p.network else None})
            for p in people
        ],
        sources_in_scope=sources,
        compared_from=compared_from,
        new_services=changes.new_services if changes else [],
        new_mcp=changes.new_mcp if changes else [],
        gone=[GoneOut(**_slots(g)) for g in changes.gone] if changes else [],
        people_pending_days=pending,
        people_days=of,
        claude_seen=claude_seen,
    )
    if not named_ok:
        # The plugin's machine, else the one the network names (G2: the machine when known).
        result = _masked(
            result,
            {p.person: p.machine or (p.network.machine if p.network else None) for p in people},
        )
    for p in result.people:
        p.key = p.key or p.person
    await run_in_threadpool(
        audit_ai_view, audit, user, ip, "ai.usage", start, end, sources,
        named_ok and _has_names(result),
    )  # fmt: skip
    cache.put(key, (result, sources))
    return result


def _masked(out: UsageOut, machines: dict[str, str | None]) -> UsageOut:
    """The answer for a viewer without View people in AI usage (D242): each person as the
    machine they used most (or "Hidden"), no top people (the machines are already listed),
    no "may be" hint, and the network name as its machine. Counts are untouched, and rows
    are never merged: two people on one machine stay two rows, keyed by place."""

    def person(p: PersonOut) -> PersonOut:
        machine = machines.get(p.person)
        network = p.network
        if network is not None:
            shown = mask_person(network.who, machine) or HIDDEN
            network = network.model_copy(update={"who": shown})
        return p.model_copy(
            update={"person": mask_person(p.person, machine) or HIDDEN, "network": network,
                    "maybe": None},
        )  # fmt: skip

    shown = [(person(p), p.person) for p in out.people]
    shown.sort(
        key=lambda r: (
            r[0].seen_through == "network", -r[0].cost_usd, -r[0].tokens, -r[0].sessions,
            -r[0].tool_calls, -r[0].errors, -r[0].sensitive,
            -(r[0].network.lookups if r[0].network else 0), r[0].person, tie(r[1]),
        )
    )  # fmt: skip
    people = [p.model_copy(update={"key": f"row-{i}"}) for i, (p, _) in enumerate(shown)]
    return out.model_copy(
        update={
            "services": [u.model_copy(update={"top_people": []}) for u in out.services],
            "non_usage": [u.model_copy(update={"top_people": []}) for u in out.non_usage],
            "people": people,
            "masked": True,
        }
    )


def _has_names(out: UsageOut) -> bool:
    """Whether the answer shows anyone by name: the audit row says so (G3)."""
    if out.masked:
        return False
    return bool(out.people) or any(u.top_people for u in [*out.services, *out.non_usage])


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
    not_approved: int | None = None  # services card: marked Not approved (D184)
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
    starts: str | None = None  # while not compared: when comparisons start
    before: str = ""
    chart_drill: str | None = None
    services_in_use: int = 0  # AI services with any use in the period, whatever their status
    people_pending_days: int = 0  # see UsageOut
    people_days: int = 0
    # When these numbers were computed: the page shows "updated N s ago" (D147).
    updated_at: datetime | None = None


# The Dashboard's window for each `days` it asks AI Watch for (frontend `WINDOWS`).
_WATCH_WINDOWS = {1: "24h", 7: "7d", 30: "30d"}


def _audit_watch(
    request: Request,
    user: User,
    allowed: list[str] | None,
    read: list[str],
    names: bool,
    days: int,
    tz: str,
    cached: bool,
) -> None:
    """One AI Watch answer in the audit log (ADR-0029 G3 as amended 2026-11-12). With names:
    its own `ai.view_people` row, always. Without names, on the Dashboard (its page-load
    headers): the part `ai_watch` of the visit's row, written at once when no row of the
    visit covers it yet. Without names anywhere else: an `ai.view` row. Blocking."""
    audit, ip = _audit(request).audit, client_ip(request)
    extra: dict[str, Any] = {"days": days, "tz": tz}
    if cached:
        extra["cached"] = True
    visit = None if names else declared(request.headers)
    # The row must say what was read: only an answer for the visit's own window is part of
    # the visit's row (the request's `days`, never the header alone). Any other `days`, or
    # a visit with no window, is audited on its own.
    window = _WATCH_WINDOWS.get(days)
    if visit is None or window is None or visit.window != window:
        audit_ai_view(audit, user, ip, "ai.watch.summary", None, None, read, names, **extra)
        return
    loads: PageLoadAudit = request.app.state.page_loads
    detail = {"surface": "ai.watch.summary", "start": None, "end": None,
              "sources_in_scope": read, **extra}  # fmt: skip
    loads.record(visit, user.user_id, ip, [AI_WATCH], window, allowed, ("ai.view", detail))


@router.get("/ai/watch/summary", response_model=WatchSummaryOut)
async def ai_watch_summary(
    request: Request,
    user: CurrentUser,
    days: Annotated[int, Query(ge=1, le=30)] = 7,
    tz: Annotated[str, Query(max_length=64)] = "UTC",
) -> Response:
    """AI Watch (ADR-0035 rows 10, 12, 13): five cards against the period before, AI use
    over 30 days by review status, and the top services, all on the caller's view.
    Without View people in AI usage, card text and new agents show machines, never names
    (D242). Audited ai.view_people when names are shown; else as part of the Dashboard
    visit's row when the request belongs to one, or ai.view on its own."""
    app = request.app
    meta: MetaDB = app.state.meta
    allowed = await run_in_threadpool(permitted_sources, meta, user)
    # Kept per viewer, window, and zone; any change made in the app (a review, a closed
    # alert) clears it, so a decision shows at once (owner, 2026-10-31). The 7-day view is
    # refreshed in the background and served at once (D147). The permission is part of the
    # key, and each computation masks for the viewer as they are then, so a named answer
    # is never served to a caller without it (D242).
    cache: PageCache = app.state.page_cache
    named_ok = can_view_people(user)
    key = ("ai_watch", user.user_id, scope_key(allowed), days, tz, named_ok)
    default = days == 7

    def compute(viewer: User, scope: list[str] | None) -> tuple[bytes, list[str], bool]:
        items_store: AlertItems = app.state.alert_items
        ai_items = [i for i in items_store.items(viewer, "all", 5000) if i.kind == "ai_watch"]
        kinds = source_classes(
            [(x.source_id, x.kind or "file", x.template_id) for x in app.state.sources.list()]
        )

        def readable(i: AlertItem) -> bool:
            return scope is None or set(i.sources) <= set(scope)

        now = app.state.ai_watch.now()
        s = watch_summary(
            app.state.ai_usage, app.state.ai_catalog, app.state.engine, scope, ai_items,
            readable, kinds, now, days, tz,
            # Named only when the key and the viewer as they are now both allow it: a
            # background refresh never puts names under a key without the permission.
            named_ok and can_view_people(viewer),
        )  # fmt: skip
        pending, of = app.state.ai_usage.people_pending(
            QueryScope(scope, now - timedelta(days=30), now)
        )
        result = WatchSummaryOut(
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
            starts=s.starts,
            before=s.before,
            chart_drill=s.chart_drill,
            services_in_use=s.services_in_use,
            people_pending_days=pending,
            people_days=of,
            updated_at=app_now(request),
        )
        return result.model_dump_json().encode(), list(s.sources), s.names

    peeked = cache.peek(key, STALE_MAX_S) if default else None
    hit = (peeked[0] if peeked is not None else None) if default else cache.get(key)
    if hit is not None:
        body, read, names = hit
        await run_in_threadpool(_audit_watch, request, user, allowed, read, names, days, tz, True)
        if default:  # seen now: refreshed while viewed, again after a lapse (D147)
            app.state.refresher.watch(key, user.user_id, scope_key(allowed), compute)
        return Response(body, media_type="application/json")

    body, read, names = await run_in_threadpool(compute, user, allowed)
    await run_in_threadpool(_audit_watch, request, user, allowed, read, names, days, tz, False)
    cache.put(key, (body, read, names))
    if default:
        app.state.refresher.watch(key, user.user_id, scope_key(allowed), compute)
    return Response(body, media_type="application/json")


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
        reason, note = "approved", "Approved"
    elif status == "not_approved":
        reason, note = "resolved", "Marked not approved"
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


class FailingOut(BaseModel):
    """A background job that is failing (owner, 2026-11-03). `detail` (the engine's error
    and a message cut before any quoted value) is for administrators only."""

    job: str  # "ai_watch.review", "page.ai_watch"
    since: datetime
    last_at: datetime
    count: int
    detail: str | None = None


class WatchStatusOut(BaseModel):
    failing: list[FailingOut]


def failing_out(failures: list[Failure], admin: bool) -> list[FailingOut]:
    return [
        FailingOut(
            job=f.job, since=f.since, last_at=f.last_at, count=f.count,
            detail=describe(f.error, f.engine_error, f.detail) if admin else None,
        )
        for f in failures
    ]  # fmt: skip


@router.get("/ai/watch/status")
async def watch_status(request: Request, user: CurrentUser) -> WatchStatusOut:
    """Whether AI Watch's checks and its page refresh are failing, for the AI Watch panel:
    when they started failing and how often. No data; the error detail for admins."""
    watch: AiWatch = request.app.state.ai_watch
    refresher: Refresher = request.app.state.refresher
    failing = watch.jobs.failing("ai_watch.") + refresher.jobs.failing("page.ai_watch")
    return WatchStatusOut(failing=failing_out(failing, user.role == "admin"))


class WatchStepOut(BaseModel):
    step: str  # events | agents | review
    ok: bool
    detail: str | None


@router.post("/ai/watch/check")
async def check_watch(request: Request, user: AdminUser) -> list[WatchStepOut]:
    """Run every AI Watch step now, the hourly ones included, and say which failed and
    why (Health > Check now). Audited ai.watch_check."""
    watch: AiWatch = request.app.state.ai_watch
    steps = await run_in_threadpool(watch.check_now)
    await run_in_threadpool(
        _audit(request).audit.write, "ai.watch_check", "success", user.user_id,
        client_ip(request), {"failed": [s for s, d in steps if d is not None]},
    )  # fmt: skip
    return [WatchStepOut(step=s, ok=d is None, detail=d) for s, d in steps]


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


class AgentMachineOut(BaseModel):
    name: str
    last_seen: str
    events_24h: int


class AgentOut(BaseModel):
    kind: str
    agent: str
    label: str
    owners: list[str]
    machine: str | None  # the machine it ran on last
    machines: list[AgentMachineOut]  # every machine, newest first, with its own counts
    first_seen: str
    last_seen: str
    events_24h: int
    state: str
    new_items: list[AgentItemOut]
    usual_peak: int | None
    recent_peak: int | None
    # True: no owners, the label by machine, and a key by place, for a viewer without View
    # people in AI usage (D242).
    masked: bool = False
    owners_hidden: int = 0  # owners left out of a masked row


@router.get("/ai/agents")
async def ai_agents(request: Request, user: CurrentUser) -> list[AgentOut]:
    """AI agents (Claude Code per machine and person, MCP clients per machine, API keys)
    and what changed in the last 24 hours against the 30 days before, from the sources
    the caller may read. Without View people in AI usage, no owners and labels by machine
    (D242). Audited ai.view_people when owners are shown, else ai.view."""
    meta: MetaDB = request.app.state.meta
    allowed = await run_in_threadpool(permitted_sources, meta, user)
    engine: QueryEngine = request.app.state.engine
    at = app_now(request)
    rows = await run_in_threadpool(agents, engine, allowed, at)
    named_ok = can_view_people(user)
    # How many owners each shown row hides, so a masked Owner cell says "Hidden" where an
    # agent had owners and stays empty where it had none, as for every viewer (D242).
    pairs = masked_agents(rows) if not named_ok else [(a, None) for a in rows]
    await run_in_threadpool(
        audit_ai_view, _audit(request).audit, user, client_ip(request), "ai.agents",
        at - timedelta(days=AGENT_DAYS), at, allowed,
        named_ok and any(a.owners for a, _ in pairs),
    )  # fmt: skip
    return [
        AgentOut(
            **{**_slots(a), "machines": [_slots(m) for m in a.machines]},
            masked=not named_ok,
            owners_hidden=len(o.owners) if o is not None else 0,
        )
        for a, o in pairs
    ]


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
    state: Literal["ended", "idle", "open"] = "open"  # idle: no record for the idle time
    top_tools: list[str] = []  # the three most used, most first
    files: int = 0  # distinct paths touched
    unanswered: int = 0  # tool calls with no result (blocked, interrupted, or still running)
    new_mcp: list[str] = []  # MCP servers first used in this session (in the range)
    account: str | None = None  # the Claude account the plugin reported
    # The same on every row: the window's sessions and those with a step, before the list's
    # cap of 100 (so the newest 100 can say "100 of 300").
    total: int = 0
    with_steps: int = 0
    # The window this list read (the same on every row): the last 90 days of the choice.
    read_start: str = ""
    read_end: str = ""
    # True: `person` and `account` show the machine (or "Hidden"), for a viewer without View
    # people in AI usage (D242).
    masked: bool = False


def _masked_session(s: SessionOut) -> SessionOut:
    """A session for a viewer without View people in AI usage (D242): the person and the
    Claude account as the session's machine, or "Hidden"."""
    return s.model_copy(
        update={"person": mask_person(s.person, s.machine),
                "account": mask_person(s.account, s.machine), "masked": True}
    )  # fmt: skip


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
    # prompt | tool_call | tool_result | file_access | access | other, derived on the server
    # from the record (app.ai.sessions.step_type), never stored
    type: Literal["prompt", "tool_call", "tool_result", "file_access", "access", "other"] = "other"
    counted: bool = True  # False: Claude Code bookkeeping (D186), never a failed or open call


class TimelineOut(BaseModel):
    session_id: str
    person: str | None
    machine: str | None
    steps: list[StepOut]
    masked: bool = False  # `person` is the machine (or "Hidden"), D242


@router.get("/ai/sessions")
async def ai_sessions(
    request: Request,
    user: CurrentUser,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
    person: Annotated[str | None, Query(max_length=256)] = None,
    start: UtcDateTime | None = None,
    end: UtcDateTime | None = None,
) -> list[SessionOut]:
    """Recent Claude Code and Cowork sessions from the hooks plugin (ADR-0026), newest
    first, from the sources the caller may read; with `person`, only that person's under
    any form of the name (ADR-0038 row 27). Without View people in AI usage, machines stand
    in for names and `person` is refused (D242). Audited ai.view_people when names are
    shown, else ai.view."""
    if person:
        await run_in_threadpool(require_ai_people, request, user)
    meta: MetaDB = request.app.state.meta
    allowed = await run_in_threadpool(permitted_sources, meta, user)
    engine: QueryEngine = request.app.state.engine
    idle = request.app.state.config.agents.session_idle_minutes
    at = app_now(request)
    # With `start`, exactly the page's time (Agents, PR 639); `days` otherwise.
    start, end = _window(start, end, at, days)
    rows = await run_in_threadpool(sessions, engine, allowed, at, days, idle, start, end)
    if person:
        # As the rest of the person page: the part the caller's scope shows (T70, D219,
        # D223), the same kept set for the same days.
        ident = await caller_identities(
            request, user, QueryScope(allowed, start or at - timedelta(days=days), end or at)
        )
        keys = set(ident.keys_for(person))
        rows = [s for s in rows if s.person and ident.key(s.person) in keys]
        # The totals count what is listed: this person's sessions, not the caller's all.
        total, stepped = len(rows), sum(1 for s in rows if s.tool_calls or s.prompts)
        rows = [replace(s, total=total, with_steps=stepped) for s in rows]
    read_start = (start or at - timedelta(days=days)).isoformat()
    read_end = (end or at).isoformat()
    out = [SessionOut(**_slots(s), read_start=read_start, read_end=read_end) for s in rows]
    named_ok = can_view_people(user)
    if not named_ok:
        # Newest first as computed, never reordered by a hidden name.
        out = [_masked_session(s) for s in out]
    await run_in_threadpool(
        audit_ai_view, _audit(request).audit, user, client_ip(request), "ai.sessions",
        start or at - timedelta(days=days), end or at, allowed,
        named_ok and any(s.person or s.account for s in out),
        **({"person": person[:256]} if person else {}),
    )  # fmt: skip
    return out


@router.get("/ai/sessions/{session_id}")
async def ai_session(
    session_id: str,
    request: Request,
    user: CurrentUser,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> TimelineOut:
    """One session in order: start, prompts, each tool call and its result, stop. Without
    View people in AI usage, the machine stands in for the person (D242); step paths are
    left as they are (a residual in D242). Audited ai.view_people when the person is shown,
    else ai.view, with the session id."""
    meta: MetaDB = request.app.state.meta
    allowed = await run_in_threadpool(permitted_sources, meta, user)
    engine: QueryEngine = request.app.state.engine
    at = app_now(request)
    t = await run_in_threadpool(timeline, engine, allowed, session_id, at, days)
    named_ok = can_view_people(user)
    await run_in_threadpool(
        audit_ai_view, _audit(request).audit, user, client_ip(request), "ai.session",
        at - timedelta(days=days), at, allowed, named_ok and t.person is not None,
        session_id=session_id[:200],
    )  # fmt: skip
    return TimelineOut(
        session_id=t.session_id,
        person=t.person if named_ok else mask_person(t.person, t.machine),
        machine=t.machine,
        steps=[StepOut(**_slots(x)) for x in t.steps],
        masked=not named_ok,
    )


class SessionSummaryOut(BaseModel):
    session_id: str
    person: str | None
    machine: str | None
    account: str | None  # the Claude account the plugin reported
    started: str
    last: str
    length_s: int
    state: Literal["ended", "idle", "open"]
    prompts: int  # requests
    tool_calls: int
    failed: int
    unanswered: int  # tool calls with no result (blocked, interrupted, or still running)
    # Null when no token metrics arrived for this session ("Not reported", never 0).
    tokens_in: int | None
    tokens_out: int | None
    files: int  # distinct paths touched
    files_outside: int  # distinct paths written outside the session's folder
    new_mcp: list[str]  # MCP servers first used in this session (in the range)
    types: dict[str, int]  # steps per type, every type listed
    steps: int  # every step, also those the steps list leaves out
    steps_cut: bool  # the steps list stops before the session's end
    sql: str = ""  # the session's records for Logs, the window as placeholders
    masked: bool = False  # `person` and `account` are the machine (or "Hidden"), D242


@router.get("/ai/sessions/{session_id}/summary")
async def ai_session_summary(
    session_id: str,
    request: Request,
    user: CurrentUser,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> SessionSummaryOut:
    """One session in numbers, counted over the whole session: prompts, tool calls with
    how many failed or got no result, tokens in and out (null when Claude Code telemetry
    sent none), files touched and how many were written outside the session's folder, the
    flags' inputs, and the steps per type. Metadata only. Without View people in AI usage,
    the machine stands in for the person and the account (D242). Audited as one session:
    ai.view_people when a name is shown, else ai.view, with the session id."""
    meta: MetaDB = request.app.state.meta
    allowed = await run_in_threadpool(permitted_sources, meta, user)
    engine: QueryEngine = request.app.state.engine
    idle = request.app.state.config.agents.session_idle_minutes
    at = app_now(request)
    s = await run_in_threadpool(session_summary, engine, allowed, session_id, at, days, idle)
    named_ok = can_view_people(user)
    await run_in_threadpool(
        audit_ai_view, _audit(request).audit, user, client_ip(request), "ai.session_summary",
        at - timedelta(days=days), at, allowed,
        named_ok and (s.person is not None or s.account is not None),
        session_id=session_id[:200],
    )  # fmt: skip
    out = SessionSummaryOut(**_slots(s))
    if named_ok:
        return out
    return out.model_copy(
        update={"person": mask_person(s.person, s.machine),
                "account": mask_person(s.account, s.machine), "masked": True}
    )  # fmt: skip


class AccountRowOut(BaseModel):
    # The account, or for a viewer without View people in AI usage its first device (or
    # "Hidden"), with `os_users` left empty (D242): `AccountsOut.masked` says which.
    email: str | None
    key: str = ""  # a stable row key that is never a hidden name
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
    masked: bool = False
    # The window read: the last 90 days of the choice (PR 639).
    read_start: str = ""
    read_end: str = ""


@router.get("/agents/accounts")
async def agents_accounts(
    request: Request,
    user: CurrentUser,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
    start: UtcDateTime | None = None,
    end: UtcDateTime | None = None,
) -> AccountsOut:
    """Claude accounts the hooks plugin reported, by tier (ADR-0030 amendment): company
    confirmed by an Entra sign-in, company reported, company not confirmed, personal, or not
    checked; each with its evidence. Without View people in AI usage, each account shows
    its first device instead and no OS users (D242). Audited ai.view_people when names are
    shown, else ai.view."""
    meta: MetaDB = request.app.state.meta
    allowed = await run_in_threadpool(permitted_sources, meta, user)
    srcs = [
        (s.source_id, s.kind or "file", s.template_id) for s in request.app.state.sources.list()
    ]
    kinds = source_classes(srcs)

    def mine(ids: list[str]) -> list[str]:
        return ids if allowed is None else [s for s in ids if s in set(allowed)]

    domains = (await run_in_threadpool(request.app.state.identities.load)).domains
    at = app_now(request)
    start, end = _window(start, end, at, days)
    if end is not None:
        at = end
    out = await run_in_threadpool(
        accounts,
        request.app.state.engine,
        allowed,
        mine(kinds.get("telemetry", [])),
        mine(kinds.get("m365", [])),
        domains,
        at,
        days,
        start,
    )
    named_ok = can_view_people(user)
    rows = []
    for i, r in enumerate(out.rows):
        row = AccountRowOut(**_slots(r), key=r.email or f"row-{i}")
        if not named_ok:
            row = _masked_account(row, i)
        rows.append(row)
    await run_in_threadpool(
        audit_ai_view, _audit(request).audit, user, client_ip(request), "agents.accounts",
        start or at - timedelta(days=days), at, out.sources,
        named_ok and any(r.email or r.os_users for r in rows),
    )  # fmt: skip
    return AccountsOut(
        days=out.days,
        domains_set=out.domains_set,
        has_signins=out.has_signins,
        rows=rows,
        counts=out.counts,
        masked=not named_ok,
        read_start=(start or at - timedelta(days=days)).isoformat(),
        read_end=at.isoformat(),
    )


def _masked_account(row: AccountRowOut, i: int) -> AccountRowOut:
    """An account row for a viewer without View people in AI usage (D242): the first device
    for the email, no OS users, a key by place. Counts stay, rows keep their order. A
    personal domain can be a name (carol-family.example), so its evidence drops it too."""
    first = row.devices[0] if row.devices else None
    evidence = "Not an organization domain" if row.tier == "personal" else row.evidence
    return row.model_copy(
        update={"email": mask_person(row.email, first), "os_users": [], "key": f"row-{i}",
                "evidence": evidence}
    )  # fmt: skip


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


class SessionPartsOut(BaseModel):
    listed: int = 0  # hook-plugin sessions with a prompt or a tool call
    empty: int = 0  # hook-plugin sessions with neither (hidden by default)
    telemetry_only: int = 0  # sessions only Claude Code telemetry reported


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
    mcp_unreviewed: int = 0  # MCP servers seen in the window, still unreviewed
    # The window read (`start` to `end` above): the last 90 days of the choice, PR 639.
    read_start: str = ""
    read_end: str = ""
    # The Sessions tile in parts that add up to it (listed + empty + telemetry_only).
    session_parts: SessionPartsOut = SessionPartsOut()
    missing_devices: list[str]
    tools: list[ToolRowOut]


@router.get("/agents/overview")
async def agents_overview_get(
    request: Request,
    user: CurrentUser,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
    start: UtcDateTime | None = None,
    end: UtcDateTime | None = None,
) -> AgentsOverviewOut:
    """Agents > Overview and Tools (ADR-0038 section 6): sessions, people, tool calls,
    failures, MCP servers not approved, late or silent devices, and one row per tool, from
    the hooks plugin sources the caller may read; `days` back from now, or with `start`
    exactly the page's time (PR 639). The MCP counts are the MCP servers table's own rows
    (`Usage.mcp`) for the same window. Audited ai.view."""
    at = app_now(request)
    asked_end = end
    start, end = _window(start, end, at, days)
    # The MCP servers table's rows for the window read, bounded as the page asks AI usage
    # for them: the start to the minute, the end the chosen one taken to the next minute
    # (inclusive) or open. So the counts and the table they open are one answer.
    mcp_from = (start or at - timedelta(days=days)).replace(second=0, microsecond=0)
    mcp_to = None
    if asked_end is not None:
        whole = asked_end.replace(second=0, microsecond=0)
        mcp_to = whole if whole == asked_end else whole + timedelta(minutes=1)
    mcp_scope = await _scope(request, user, mcp_from, mcp_to)
    mcp_rows, mcp_read = await run_in_threadpool(
        request.app.state.ai_usage.mcp_and_sources, mcp_scope
    )
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
        at,
        days,
        mcp_rows,
        start,
        end,
    )
    await run_in_threadpool(
        _audit(request).audit.write,
        "ai.view",
        "success",
        user.user_id,
        client_ip(request),
        # Every source this request read: the overview's and the MCP table's (rule 2.14).
        {"sources_in_scope": sorted(set(out.sources) | set(mcp_read)), "view": "agents_overview"},
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
            starts=out.history.starts,
        ),
        sessions=kpi(out.sessions),
        people=kpi(out.people),
        calls=kpi(out.calls),
        failed=kpi(out.failed),
        mcp_not_approved=kpi(out.mcp_not_approved),
        late_devices=kpi(out.late_devices),
        mcp_unreviewed=out.mcp_unreviewed,
        read_start=out.start,
        read_end=out.end,
        session_parts=SessionPartsOut(**_slots(out.session_parts)),
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
    # True: agents show machines, never their owners' names (D242).
    masked: bool = False
    # Active items still unreviewed: the same number as `/ai/inventory/count`.
    to_review: int = 0
    # Active items marked Not approved, counted by the same server rule as the count.
    not_approved: int = 0


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
        app_now(request),
        days,
        can_view_people(user),
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
    Microsoft 365 apps with a granted consent, each with its exclusion if any. Without
    View people in AI usage, agents show machines instead of owners (D242). Audited
    ai.view_people when an agent with an owner is listed with names, else ai.view."""
    items, sources = await _inventory(request, user, days)
    named_ok, at = can_view_people(user), app_now(request)
    await run_in_threadpool(
        audit_ai_view, _audit(request).audit, user, client_ip(request), "ai.inventory",
        at - timedelta(days=days), at, sources,
        named_ok and any(i.type == "agent" and i.people for i in items),
    )  # fmt: skip
    return InventoryOut(
        days=days,
        items=[_item_out(i) for i in items],
        sources_in_scope=sources,
        masked=not named_ok,
        to_review=to_review(items),
        not_approved=not_approved(items),
    )


class InventoryCountOut(BaseModel):
    to_review: int
    not_approved: int = 0


@router.get("/ai/inventory/count")
async def ai_inventory_count(request: Request, user: CurrentUser) -> InventoryCountOut:
    """How many items of the viewer's Inventory are still to review, for the rail's AI
    usage count (D258): active items nobody has marked Approved or Not approved, as the
    Inventory's header counts them, on the viewer's own sources over its 30 days; and how
    many are marked Not approved, for AI usage's Needs attention line. Numbers
    only: it names nothing, so like `/health/count` it writes no audit row. Kept in the
    page cache for 60 s, which any change in the app empties, so a review shows at once;
    the audited Inventory read never comes from this answer."""
    meta: MetaDB = request.app.state.meta
    allowed = await run_in_threadpool(permitted_sources, meta, user)
    cache: PageCache = request.app.state.page_cache
    key = ("ai_inventory_count", scope_key(allowed), can_view_people(user))
    hit = cache.get(key)
    if hit is None:
        items, _ = await _inventory(request, user, 30)
        hit = (to_review(items), not_approved(items))
        cache.put(key, hit)
    review, refused = hit
    return InventoryCountOut(to_review=int(review), not_approved=int(refused))


@router.get("/ai/inventory/export")
async def ai_inventory_export(
    request: Request,
    user: Exporter,
    format: Literal["csv", "json"] = "csv",  # the query parameter's name
    days: Annotated[int, Query(ge=1, le=90)] = 30,
    type: InventoryType | None = None,  # the query parameter's name
    excluded: bool = False,
    review: Annotated[
        Literal["approved", "not_approved", "unreviewed"] | None, Query(alias="status")
    ] = None,  # `status` is the fastapi module here
) -> Response:
    """The current view as a file (row 22): admins and analysts only, every export
    audited `ai.inventory_export` with its filters and row count. Without View people in
    AI usage, agents show machines, as on the page (D242)."""
    items, sources = await _inventory(request, user, days)
    rows = [
        i for i in items
        if (type is None or i.type == type) and (i.excluded is not None) == excluded
        and (review is None or i.status == review)
    ]  # fmt: skip
    body = inventory_export(rows, format)
    detail = {"format": format, "days": days, "type": type, "excluded": excluded,
              "status": review, "rows": len(rows), "sources_in_scope": sources}  # fmt: skip
    await run_in_threadpool(
        _audit(request).audit.write, "ai.inventory_export", "success", user.user_id,
        client_ip(request), detail,
    )  # fmt: skip
    if can_view_people(user) and any(i.type == "agent" for i in rows):
        # Agent names carry their owners for this caller: a named export (ADR-0029 G3, G4).
        await run_in_threadpool(
            _audit(request).audit.write, "ai.export_people", "success", user.user_id,
            client_ip(request), {**detail, "surface": "ai.inventory_export"},
        )  # fmt: skip
    stamp = app_now(request).strftime("%Y%m%d-%H%M")
    return Response(
        body,
        media_type="text/csv" if format == "csv" else "application/json",
        headers={"Content-Disposition": f'attachment; filename="ai-inventory-{stamp}.{format}"'},
    )


@router.put("/ai/inventory/exclusions")
async def ai_inventory_exclude(body: ExcludeIn, request: Request, user: AdminUser) -> ExclusionOut:
    """Move an item to Excluded with a reason (row 21). It still shows in Logs, alerts,
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


class CountOut(BaseModel):
    name: str
    n: int


class ServiceSeenOut(BaseModel):
    service_id: str
    name: str
    events: int
    last_seen: str | None


class SessionLineOut(BaseModel):
    session_id: str
    machine: str | None
    started: str
    last: str
    summary: str
    flagged: bool


class FlagOut(BaseModel):
    kind: str
    text: str
    count: int
    examples: list[str]


class PersonAiOut(BaseModel):
    person: str
    start: str
    end: str
    accounts: list[AccountRowOut]
    devices: list[str]
    services: list[ServiceSeenOut]
    sessions: list[SessionLineOut]
    tools: list[CountOut]
    files: list[CountOut]
    commands: list[CountOut]
    domains: list[CountOut]
    mcp: list[CountOut]
    flags: list[FlagOut]
    cut: bool


@router.get("/ai/people/{person}/activity")
async def ai_person_activity(
    person: str,
    request: Request,
    user: CurrentUser,
    days: Annotated[int, Query(ge=1, le=30)] = 7,
) -> PersonAiOut:
    """One person's AI activity (D189): accounts and devices, AI services the network saw,
    Claude Code sessions with a one-line summary, rollups (tools, files written or edited,
    commands, web domains, MCP servers), and flags. Metadata only, from the sources the
    caller may read. Refused without View people in AI usage (D242). Audited
    ai.view_people."""
    await run_in_threadpool(require_ai_people, request, user)
    meta: MetaDB = request.app.state.meta
    allowed = await run_in_threadpool(permitted_sources, meta, user)
    srcs = [
        (s.source_id, s.kind or "file", s.template_id) for s in request.app.state.sources.list()
    ]
    kinds = source_classes(srcs)

    def mine(ids: list[str]) -> list[str]:
        return ids if allowed is None else [s for s in ids if s in set(allowed)]

    at = app_now(request)
    # The person's other forms, as far as the caller's scope shows them (T70, D219, D223);
    # the same window as person_activity reads.
    ident = await caller_identities(
        request, user, QueryScope(allowed, at - timedelta(days=days), at)
    )
    # Each account's tier says only whether its own domain is an organization domain.
    domains = (await run_in_threadpool(request.app.state.identities.load)).domains
    accts = await run_in_threadpool(
        accounts, request.app.state.engine, allowed, mine(kinds.get("telemetry", [])),
        mine(kinds.get("m365", [])), domains, at, max(days, 30),
    )  # fmt: skip
    catalog = _catalog(request)
    out = await run_in_threadpool(
        person_activity, request.app.state.engine, allowed, ident, catalog.domain_table(),
        {s.id: s.name for s in catalog.services()}, accts.rows, person[:256], at, days,
        request.app.state.ai_rollup,
    )  # fmt: skip
    await run_in_threadpool(
        audit_ai_view, _audit(request).audit, user, client_ip(request), "ai.person_activity",
        at - timedelta(days=days), at, out.sources, True, person=out.person[:256],
    )  # fmt: skip
    return PersonAiOut(
        person=out.person, start=out.start, end=out.end,
        accounts=[AccountRowOut(**_slots(a)) for a in out.accounts], devices=out.devices,
        services=[ServiceSeenOut(**_slots(s)) for s in out.services],
        sessions=[SessionLineOut(**_slots(s)) for s in out.sessions],
        tools=[CountOut(**_slots(c)) for c in out.tools],
        files=[CountOut(**_slots(c)) for c in out.files],
        commands=[CountOut(**_slots(c)) for c in out.commands],
        domains=[CountOut(**_slots(c)) for c in out.domains],
        mcp=[CountOut(**_slots(c)) for c in out.mcp],
        flags=[FlagOut(**_slots(f)) for f in out.flags], cut=out.cut,
    )  # fmt: skip
