"""/api/alerts: the one queue of things that fired, with Close, reopen, and mutes (ADR-0037).
Router only; the rules live in `app.alerts.items`.

Everyone may read the alerts they can see; Admins and Analysts close and reopen; only Admins
mute. Items whose run read a source the viewer may not read are never described, and never
counted: the viewer only learns that some exist (`restricted`, owner 2026-11-12).
"""

import ipaddress
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.ai.alert_mask import has_names, mask_item, mask_mute
from app.ai.host_people import Asked, DevicePerson, for_alerts
from app.ai.people_view import audit_ai_view, can_view_people
from app.alerts.external import MAX_PAGE, SHOWN_IDS, alert_ids, is_external, item_events
from app.alerts.items import MAX_NOTE, REASONS, AlertItem, AlertItems, Mute, label
from app.api.access import AdminUser, CurrentUser, client_ip, require_role
from app.auth.users import User
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ParamInvalidError
from app.engine.views import permitted_sources

router = APIRouter(tags=["alerts"])
Decider = Annotated[User, Depends(require_role("admin", "analyst"))]
State = Literal["open", "closed", "all"]
Review = Literal["approved", "not_approved", "unreviewed", "unknown"]


class EventOut(BaseModel):
    at: str
    user: str | None
    action: str
    reason: str | None
    reason_label: str | None = None
    note: str | None


class DevicePersonOut(BaseModel):
    """Who used a device the alert names, from the hooks plugin's records the viewer reads
    (owner item 5; ADR-0048 C1): one person is attributed, several are possible."""

    device: str
    level: Literal["attributed", "possible"]
    people: list[str]  # up to 3; none without View people in AI usage (D242)
    count: int
    how: Literal["hooks", "hooks_identities"]


class AlertIdOut(BaseModel):
    product: str
    alert_id: str


class AlertIdsOut(BaseModel):
    count: int
    ids: list[AlertIdOut]


class AlertEventsOut(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    elapsed_ms: int


class ItemOut(BaseModel):
    item_id: str
    kind: str
    subject: str
    ref_id: str | None
    title: str
    detail: str
    why: str | None
    count: int | None
    sources: list[str]
    range_start: str | None
    range_end: str | None
    created_at: str
    state: str
    closed_at: str | None
    closed_by: str | None
    close_reason: str | None
    close_reason_label: str | None
    note: str | None
    resolved: str | None
    schedule_id: str | None  # the schedule whose run fired: its rows are that run's sample
    severity: str | None  # high | medium as stored on the item; the only severity it has
    people: list[str] = []
    devices: list[str] = []
    # An AI Watch item for a viewer without View people in AI usage (D242): no names in
    # any text and no people listed; `people_hidden` is how many it is about.
    masked: bool = False
    people_hidden: int = 0
    muted_until: str | None
    history: list[EventOut]
    # The group (ADR-0043): one open item per entity, rule, and day, with its repeats.
    entity: str | None = None
    rule: str | None = None
    day: str | None = None
    last_seen: str | None = None
    changes: list[str] = []
    more_changes: int = 0
    # AI service and MCP server items: the catalog status now, which "Why it matters"
    # follows; "unknown" for a service the catalog does not list; None for other items.
    review_status: Review | None = None
    device_people: list[DevicePersonOut] = []
    # An external alert item's vendor alerts (D228): the count and the first SHOWN_IDS on
    # the item's own page; the rest page through /alerts/{id}/alert-ids. Never on the list.
    alert_ids: AlertIdsOut | None = None
    # The closed item this one follows: a vendor alert that rose after it was closed.
    follows: str | None = None
    # Raised or grown by a rule re-run over reparsed events (D241), with their time range.
    late: bool = False
    late_start: str | None = None
    late_end: str | None = None


class MuteOut(BaseModel):
    mute_id: str
    kind: str
    subject: str
    title: str
    until: str
    created_by: str | None
    created_at: str


class ListOut(BaseModel):
    items: list[ItemOut]
    open: int  # open items the viewer may read
    # True when an open item read a source the viewer may not read: no count, no item (owner,
    # 2026-11-12). Always false for an admin, who reads every source.
    restricted: bool
    muted: int  # active mutes
    reasons: dict[str, str]
    # Open items the viewer may read, by their stored severity ("other" when none): the
    # Alerts strip shows these, so it can never disagree with the badges in the list.
    by_severity: dict[str, int] = {}


class CountOut(BaseModel):
    """Open alerts as numbers only (the alert badge, the Dashboard's count): no item."""

    open: int
    restricted: bool  # as ListOut.restricted: a flag, never a count
    by_severity: dict[str, int] = {}


class LinesOut(BaseModel):
    """The few open alerts a summary shows (the Dashboard's "Needs you", Health's newest):
    one item per kind and subject, its newest, with how many open items it stands for."""

    items: list[ItemOut]
    runs: dict[str, int] = {}  # item_id: open items of its kind and subject
    groups: int  # every kind and subject open and readable, shown or not
    gap_sources: list[str] = []  # sources with an open gap alert (no extra source line)
    open: int
    restricted: bool  # as ListOut.restricted: a flag, never a count
    by_severity: dict[str, int] = {}


Reason = Literal["expected", "approved", "false_positive", "resolved"]


class CloseIn(BaseModel):
    reason: Reason
    note: str | None = Field(default=None, max_length=MAX_NOTE)
    # AI Watch items for a service or MCP server: closing may also decide its review
    # status (owner, 2026-10-29). Admins only; None leaves it unreviewed. Closing as
    # Approved approves it (ADR-0043 row 17).
    review_status: Literal["approved", "not_approved"] | None = None


class BulkCloseIn(BaseModel):
    item_ids: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(
        min_length=1, max_length=200
    )
    reason: Reason
    note: str | None = Field(default=None, max_length=MAX_NOTE)


class BulkOut(BaseModel):
    closed: list[str]
    skipped: dict[str, str]  # item id -> why it was not closed


class MuteIn(BaseModel):
    days: Literal[7, 30]


def _store(request: Request) -> AlertItems:
    items: AlertItems = request.app.state.alert_items
    return items


def _name(request: Request, user_id: str | None) -> str | None:
    if user_id is None:
        return None
    u = request.app.state.auth.users.get(user_id)
    return u.username if u is not None else user_id


def _readable(request: Request, user: User) -> Callable[[AlertItem], bool]:
    allowed = permitted_sources(request.app.state.meta, user)
    return lambda i: allowed is None or set(i.sources) <= set(allowed)


def _review_status(request: Request, i: AlertItem) -> Review | None:
    if i.kind != "ai_watch":
        return None
    catalog = request.app.state.ai_catalog
    if i.subject.startswith("service:"):
        sid = i.subject.removeprefix("service:")
        svc = next((s for s in catalog.services() if s.id == sid), None)
        return "unknown" if svc is None else svc.status
    if i.subject.startswith("mcp:"):
        status: Review = catalog.mcp_status(i.subject.removeprefix("mcp:"), catalog.mcp_rules())
        return status
    return None


def _device_people(
    request: Request, user: User, items: list[AlertItem]
) -> dict[str, list[DevicePerson]]:
    """People on the hosts AI service and MCP server items name, from hooks sources the
    caller reads only (T70, D219); the whole Identities map for an administrator (D223)."""
    asked = [
        Asked(i.item_id, [d for d in i.devices if not _is_ip(d)],
              datetime.fromisoformat(i.range_start), datetime.fromisoformat(i.range_end))
        for i in items
        if _review_target_of(i) is not None and i.range_start and i.range_end
    ]  # fmt: skip
    if not any(a.hosts for a in asked):
        return {}
    hooks = [
        s.source_id for s in request.app.state.sources.list()
        if s.kind == "otlp" or s.template_id == "claude_hooks"
    ]  # fmt: skip
    allowed = permitted_sources(request.app.state.meta, user)
    mine = hooks if allowed is None else [s for s in hooks if s in set(allowed)]
    return for_alerts(
        request.app.state.engine, mine, request.app.state.identities.load(),
        user.role == "admin", asked,
    )  # fmt: skip


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _review_target_of(i: AlertItem) -> str | None:
    if i.kind != "ai_watch":
        return None
    return next((k for k in ("service", "mcp") if i.subject.startswith(f"{k}:")), None)


def _out(
    request: Request,
    i: AlertItem,
    mutes: list[Mute],
    people: dict[str, list[DevicePerson]] | None = None,
    named_ok: bool = True,
) -> ItemOut:
    until = next((m.until for m in mutes if m.kind == i.kind and m.subject == i.subject), None)
    review = _review_status(request, i)  # from the stored subject
    masked = not named_ok and i.kind == "ai_watch"
    # Older items keep their names only in the text: at least one is hidden, so the
    # People row still says names are hidden (D242).
    hidden = (len(i.people) or int(has_names(i))) if masked else 0
    if masked:
        i = mask_item(i)
    return ItemOut(
        item_id=i.item_id,
        kind=i.kind,
        subject=i.subject,
        ref_id=i.ref_id,
        title=i.title,
        detail=i.detail,
        why=i.why,
        count=i.count,
        sources=i.sources,
        range_start=i.range_start,
        range_end=i.range_end,
        created_at=i.created_at,
        state=i.state,
        closed_at=i.closed_at,
        closed_by=_name(request, i.closed_by),
        close_reason=i.close_reason,
        close_reason_label=label(i.close_reason),
        note=i.note,
        resolved=i.resolved,
        schedule_id=i.schedule_id,
        severity=i.severity,
        people=i.people,
        devices=i.devices,
        masked=masked,
        people_hidden=hidden,
        muted_until=until,
        entity=i.entity,
        rule=i.rule,
        day=i.day,
        last_seen=i.last_seen,
        changes=i.changes,
        more_changes=i.more,
        follows=i.follows,
        late=i.late,
        late_start=i.late_start,
        late_end=i.late_end,
        review_status=review,
        device_people=[
            DevicePersonOut(
                device=d.device,
                level=d.level,
                people=d.people if named_ok else [],
                count=d.count,
                how=d.how,
            )
            for d in (people or {}).get(i.item_id, [])
        ],
        history=[
            EventOut(
                at=h.at,
                user=_name(request, h.user_id),
                action=h.action,
                reason=h.reason,
                reason_label=label(h.reason),
                note=h.note,
            )
            for h in i.history
        ],
    )


def _unreviewed(request: Request, item: AlertItem) -> bool:
    """An AI Watch item whose service or MCP server is still not reviewed."""
    if item.kind != "ai_watch":
        return False
    catalog = request.app.state.ai_catalog
    if item.subject.startswith("service:"):
        sid = item.subject.removeprefix("service:")
        svc = next((s for s in catalog.services() if s.id == sid), None)
        return svc is None or svc.status == "unreviewed"
    if item.subject.startswith("mcp:"):
        name = item.subject.removeprefix("mcp:")
        return bool(catalog.mcp_status(name, catalog.mcp_rules()) == "unreviewed")
    return False


def _list(
    request: Request,
    user: User,
    state: str,
    unreviewed: bool = False,
    person: str | None = None,
) -> ListOut:
    store = _store(request)
    readable = _readable(request, user)
    found = store.items(user, state)
    if unreviewed:
        found = [i for i in found if _unreviewed(request, i)]
    if person and not can_view_people(user):
        # AI Watch items name people in AI usage: left out before any name is matched, so
        # they can neither be listed nor link a form of the name (D242, amended 2026-11-11).
        found = [i for i in found if i.kind != "ai_watch"]
    if person:
        # One person under every form of the name (ADR-0018), as the person page shows it:
        # the whole map for an administrator (D223), otherwise only the links the names on
        # the caller's own alerts show (T70, D219), never a form typed in `person`.
        ident = request.app.state.identities.load()
        if user.role != "admin":
            ident = ident.seen_in(n for i in found if readable(i) for n in i.people)
        keys = set(ident.keys_for(person))
        found = [i for i in found if any(ident.key(p) in keys for p in i.people)]
    opened = found if state == "open" else store.items(user, "open")
    mutes = store.mutes()
    tally = _tally(opened, readable)
    if person:
        # Whether any open alert is in a source the caller cannot read, never whether one
        # names this person: the flag comes from every open alert, not the filtered ones
        # (D243; the person filter also matches alerts the caller cannot read).
        every = _tally(store.items(user, "open"), readable)
        tally = tally.model_copy(update={"restricted": every.restricted})
    shown = [i for i in found if readable(i)]
    people = _device_people(request, user, shown)
    named_ok = can_view_people(user)
    _audit_view(request, user, "alerts", shown, people, named_ok, state=state)
    return ListOut(
        items=[_out(request, i, mutes, people, named_ok) for i in shown],
        open=tally.open,
        restricted=tally.restricted,
        muted=len(mutes),
        reasons=dict(REASONS),
        by_severity=tally.by_severity,
    )


def _tally(opened: list[AlertItem], readable: Callable[[AlertItem], bool]) -> CountOut:
    sev = {"high": 0, "medium": 0, "other": 0}
    for i in opened:
        if readable(i):
            sev[i.severity if i.severity in ("high", "medium") else "other"] += 1
    n = sum(sev.values())
    return CountOut(open=n, restricted=len(opened) > n, by_severity=sev)


@router.get("/alerts")
async def list_alerts(
    request: Request,
    user: CurrentUser,
    state: Annotated[State, Query()] = "open",
    unreviewed: Annotated[bool, Query()] = False,
    person: Annotated[str | None, Query(max_length=256)] = None,
) -> ListOut:
    """The viewer's alerts, newest first: open by default, or closed, or all. With
    `unreviewed`, only AI Watch items whose service or MCP server is still not reviewed,
    closed ones included: what AI Watch's "not reviewed" line links to. With `person`, only
    items about that person under any form of the name (ADR-0038 row 27); without View
    people in AI usage, AI Watch items are left out of it (D242). Without it, AI Watch
    items name no one: "a person" stands in place of each name."""
    return await run_in_threadpool(_list, request, user, state, unreviewed, person)


@router.get("/alerts/count")
async def count_alerts(request: Request, user: CurrentUser) -> CountOut:
    """Open alerts as numbers only, for the alert badge and the Dashboard's count. It
    returns no item, so it is not an AI view and writes no audit row (D242); every answer
    with an item's text is audited."""

    def run() -> CountOut:
        return _tally(_store(request).items(user, "open"), _readable(request, user))

    return await run_in_threadpool(run)


_RANK = {"high": 0, "medium": 1}


def _lines(request: Request, user: User, limit: int, by: str) -> LinesOut:
    store = _store(request)
    readable = _readable(request, user)
    opened = store.items(user, "open")
    shown = [i for i in opened if readable(i)]  # newest first
    groups: dict[tuple[str, str], tuple[AlertItem, int]] = {}
    for i in shown:
        first, runs = groups.get((i.kind, i.subject), (i, 0))
        groups[(i.kind, i.subject)] = (first, runs + 1)
    top = list(groups.values())
    if by == "severity":  # stable: newest first within a severity, as the banner sorts
        top.sort(key=lambda g: _RANK.get(g[0].severity or "", 2))
    top = top[:limit]
    named_ok = can_view_people(user)
    # Access, not page loads (owner, 2026-11-11): a row only when a line shows a name.
    if named_ok and any(has_names(i) for i, _ in top):
        audit_ai_view(
            request.app.state.auth.audit, user, client_ip(request), "alert_lines", None, None,
            permitted_sources(request.app.state.meta, user), True,
        )  # fmt: skip
    mutes = store.mutes()
    tally = _tally(opened, readable)
    return LinesOut(
        items=[_out(request, i, mutes, {}, named_ok) for i, _ in top],
        runs={i.item_id: n for i, n in top},
        groups=len(groups),
        gap_sources=sorted({i.subject for i in shown if i.kind == "gap"}),
        open=tally.open,
        restricted=tally.restricted,
        by_severity=tally.by_severity,
    )


@router.get("/alerts/lines")
async def alert_lines(
    request: Request,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
    by: Annotated[Literal["severity", "newest"], Query()] = "severity",
) -> LinesOut:
    """The first `limit` open alerts a summary shows, one per kind and subject: most
    severe first (the Dashboard's "Needs you"), or newest first (Health). Only those lines,
    so the audit log records what was shown: `ai.view_people` when a line names someone to
    a viewer with View people in AI usage, else no row (owner, 2026-11-11; D242). Without
    the permission AI Watch lines name no one, as on Alerts."""
    return await run_in_threadpool(_lines, request, user, limit, by)


def _readable_item(request: Request, user: User, item_id: str) -> AlertItem:
    item = _store(request).get(item_id, user)
    if not _readable(request, user)(item):
        raise ForbiddenError("This alert read a source you cannot read")
    return item


def _ids(request: Request, item: AlertItem, offset: int, limit: int) -> AlertIdsOut | None:
    if not is_external(item):
        return None
    n, page = alert_ids(request.app.state.meta, item.item_id, offset, limit)
    return AlertIdsOut(count=n, ids=[AlertIdOut(product=p, alert_id=a) for p, a in page])


def _one(request: Request, user: User, item_id: str) -> ItemOut:
    """One item as this caller sees it, audited as an AI view when it is an AI Watch item:
    every answer with one (read, close, reopen, mute) is a view (ADR-0029 G3)."""
    store = _store(request)
    item = _readable_item(request, user, item_id)
    found = _device_people(request, user, [item])
    named_ok = can_view_people(user)
    _audit_view(request, user, "alert", [item], found, named_ok, item_id=item_id)
    out = _out(request, item, store.mutes(), found, named_ok)
    out.alert_ids = _ids(request, item, 0, SHOWN_IDS)
    return out


def _audit_view(
    request: Request,
    user: User,
    surface: str,
    shown: list[AlertItem],
    people: dict[str, list[DevicePerson]],
    named_ok: bool,
    **extra: Any,
) -> None:
    """One audit row per answer with AI Watch items (ADR-0029 G3): `ai.view_people` when
    it named someone, else `ai.view`. Answers without them are not AI views."""
    ai = [i for i in shown if i.kind == "ai_watch"]
    if not ai:
        return
    named = named_ok and (
        any(has_names(i) for i in ai) or any(d.people for ds in people.values() for d in ds)
    )
    audit_ai_view(
        request.app.state.auth.audit, user, client_ip(request), surface, None, None,
        permitted_sources(request.app.state.meta, user), named, **extra,
    )  # fmt: skip


@router.get("/alerts/mutes")
async def list_mutes(request: Request, user: CurrentUser) -> list[MuteOut]:
    """Active mutes, soonest to expire first. Everyone may see what is muted."""
    mutes = await run_in_threadpool(_store(request).mutes)
    if not can_view_people(user):
        mutes = [mask_mute(m) for m in mutes]
    return [
        MuteOut(
            mute_id=m.mute_id,
            kind=m.kind,
            subject=m.subject,
            title=m.title,
            until=m.until,
            created_by=_name(request, m.created_by),
            created_at=m.created_at,
        )
        for m in mutes
    ]


@router.get("/alerts/{item_id}")
async def get_alert(item_id: str, request: Request, user: CurrentUser) -> ItemOut:
    """One alert. Without View people in AI usage, an AI Watch alert names no one (D242)."""
    return await run_in_threadpool(_one, request, user, item_id)


@router.get("/alerts/{item_id}/alert-ids")
async def get_alert_ids(
    item_id: str,
    request: Request,
    user: CurrentUser,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = SHOWN_IDS,
) -> AlertIdsOut:
    """A page of an external alert item's vendor alert IDs, oldest first (Show all)."""

    def run() -> AlertIdsOut:
        item = _readable_item(request, user, item_id)
        return _ids(request, item, offset, limit) or AlertIdsOut(count=0, ids=[])

    return await run_in_threadpool(run)


@router.get("/alerts/{item_id}/events")
async def get_alert_events(
    item_id: str,
    request: Request,
    user: CurrentUser,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 100,
) -> AlertEventsOut:
    """An external alert item's own events, newest first: a server-built query over the
    item's stored keys, on the item's sources only, which the viewer must be able to read
    (rule 13). Audited like any query (rule 14)."""

    def run() -> AlertEventsOut:
        item = _readable_item(request, user, item_id)
        if not is_external(item):
            raise NotFoundError("This alert has no vendor alerts")
        res = item_events(
            request.app.state.engine, request.app.state.meta, item.item_id, item.sources,
            item.range_start, item.range_end, offset, limit,
        )  # fmt: skip
        request.app.state.auth.audit.write(
            "alert.events", "success", user.user_id, client_ip(request),
            {"item_id": item.item_id, "sources_in_scope": item.sources, "rows": len(res.rows)},
        )  # fmt: skip
        return AlertEventsOut(columns=res.columns, rows=res.rows, elapsed_ms=res.elapsed_ms)

    return await run_in_threadpool(run)


@router.post("/alerts/close")
async def close_alerts(body: BulkCloseIn, request: Request, user: Decider) -> BulkOut:
    """Close several alerts with one reason (ADR-0043 row 19). Each is closed and audited on
    its own (alert.close with bulk true); one that cannot be closed is skipped and named."""
    closed: list[str] = []
    skipped: dict[str, str] = {}
    for item_id in dict.fromkeys(body.item_ids):
        try:
            await _close_one(request, user, item_id, body.reason, body.note, None, bulk=True)
            closed.append(item_id)
        except (ForbiddenError, ParamInvalidError, NotFoundError, ConflictError) as exc:
            skipped[item_id] = str(exc)
    return BulkOut(closed=closed, skipped=skipped)


@router.post("/alerts/{item_id}/close")
async def close_alert(item_id: str, body: CloseIn, request: Request, user: Decider) -> ItemOut:
    """Close with a reason: Expected, Approved, False positive (note required), or Resolved.
    Audited as alert.close. Approved also marks what the alert is about as reviewed: the AI
    service or MCP server (admins), or the agent, whose open alerts all close (ADR-0043 row
    17), audited ai.review. With `review_status` (admins, service and MCP server items),
    the service or server is approved or not approved as on AI usage."""
    await _close_one(request, user, item_id, body.reason, body.note, body.review_status)
    return await run_in_threadpool(_one, request, user, item_id)


async def _close_one(
    request: Request,
    user: User,
    item_id: str,
    reason: str,
    note: str | None,
    review_status: str | None,
    bulk: bool = False,
) -> None:
    # The stored item: its subject decides the review, whatever the caller is shown.
    item = await run_in_threadpool(_readable_item, request, user, item_id)
    review = "approved" if reason == "approved" else review_status
    target = _review_target(item) if review else None
    if review and target is not None and user.role != "admin":
        raise ForbiddenError("Only an administrator approves an AI service or MCP server")
    if review_status and target is None:
        raise ParamInvalidError("This alert has no service or MCP server to review")
    await run_in_threadpool(
        _store(request).close, item_id, user, reason, note, client_ip(request), bulk
    )
    if target is not None and review:
        await run_in_threadpool(_set_review, request, user, target, review)
    elif reason == "approved" and item.subject.startswith("agent:"):
        await run_in_threadpool(_approve_agent, request, user, item)


def _approve_agent(request: Request, user: User, item: AlertItem) -> None:
    """Approved on an agent's alert marks the agent reviewed: its other open alerts (the
    standing review item among them) close as Approved, audited, and ai.review records it."""
    store = _store(request)
    n = store.close_subject(  # the subject as stored, which names no one (D242)
        "ai_watch", store.subject_of(item.item_id), user, "approved",
        f"Approved with alert {item.item_id}", client_ip(request),
    )  # fmt: skip
    request.app.state.auth.audit.write(
        "ai.review", "success", user.user_id, client_ip(request),
        {"agent": item.subject.removeprefix("agent:"), "to": "approved",
         "via": "alert.close", "closed": n},
    )  # fmt: skip


def _review_target(item: AlertItem) -> tuple[str, str] | None:
    if item.kind != "ai_watch":
        return None
    for kind in ("service", "mcp"):
        if item.subject.startswith(f"{kind}:"):
            return kind, item.subject.removeprefix(f"{kind}:")
    return None


def _set_review(request: Request, user: User, target: tuple[str, str], status: str) -> None:
    kind, name = target
    catalog = request.app.state.ai_catalog
    audit = request.app.state.auth.audit
    if kind == "service":
        before = catalog.set_status(name, status, "Set when closing its alert", user.user_id)
        audit.write(
            "ai.service_change",
            "success",
            user.user_id,
            client_ip(request),
            {"service_id": name, "from": before, "to": status, "via": "alert.close"},
        )
    else:
        catalog.set_mcp_rule(name, status, "Set when closing its alert", user.user_id)
        audit.write("ai.mcp_change", "success", user.user_id, client_ip(request),
                    {"pattern": name, "to": status, "via": "alert.close"})  # fmt: skip


@router.post("/alerts/{item_id}/reopen")
async def reopen_alert(item_id: str, request: Request, user: Decider) -> ItemOut:
    """Audited as alert.reopen."""
    await run_in_threadpool(_readable_item, request, user, item_id)
    await run_in_threadpool(_store(request).reopen, item_id, user, client_ip(request))
    return await run_in_threadpool(_one, request, user, item_id)


@router.post("/alerts/{item_id}/mute")
async def mute_alert(item_id: str, body: MuteIn, request: Request, user: AdminUser) -> ItemOut:
    """Close new alerts like this one (same kind and subject) for 7 or 30 days; the mute
    expires on its own. Admins only; audited as alert.mute."""
    await run_in_threadpool(_readable_item, request, user, item_id)
    await run_in_threadpool(_store(request).mute, item_id, body.days, user, client_ip(request))
    return await run_in_threadpool(_one, request, user, item_id)


@router.delete("/alerts/mutes/{mute_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unmute(mute_id: str, request: Request, user: AdminUser) -> Response:
    """End a mute early. Audited as alert.unmute."""
    await run_in_threadpool(_store(request).unmute, mute_id, user, client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
