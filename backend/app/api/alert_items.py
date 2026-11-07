"""/api/alerts: the one queue of things that fired, with Close, reopen, and mutes (ADR-0037).
Router only; the rules live in `app.alerts.items`.

Everyone may read the alerts they can see; Admins and Analysts close and reopen; only Admins
mute. Items whose run read a source the viewer may not read are counted as restricted and
never described.
"""

from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.alerts.items import MAX_NOTE, REASONS, AlertItem, AlertItems, Mute, label
from app.api.access import AdminUser, CurrentUser, client_ip, require_role
from app.auth.users import User
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ParamInvalidError
from app.engine.views import permitted_sources

router = APIRouter(tags=["alerts"])
Decider = Annotated[User, Depends(require_role("admin", "analyst"))]
State = Literal["open", "closed", "all"]


class EventOut(BaseModel):
    at: str
    user: str | None
    action: str
    reason: str | None
    reason_label: str | None = None
    note: str | None


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
    muted_until: str | None
    history: list[EventOut]
    # The group (ADR-0043): one open item per entity, rule, and day, with its repeats.
    entity: str | None = None
    rule: str | None = None
    day: str | None = None
    last_seen: str | None = None
    changes: list[str] = []
    more_changes: int = 0


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
    restricted: int  # open items the viewer may not read: counted, not described
    muted: int  # active mutes
    reasons: dict[str, str]
    # Open items the viewer may read, by their stored severity ("other" when none): the
    # Alerts strip shows these, so it can never disagree with the badges in the list.
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


def _out(request: Request, i: AlertItem, mutes: list[Mute]) -> ItemOut:
    until = next((m.until for m in mutes if m.kind == i.kind and m.subject == i.subject), None)
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
        muted_until=until,
        entity=i.entity,
        rule=i.rule,
        day=i.day,
        last_seen=i.last_seen,
        changes=i.changes,
        more_changes=i.more,
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
    if person:
        # One person under every form of the name (ADR-0018), as the person page shows it.
        ident = request.app.state.identities.load()
        keys = set(ident.keys_for(person))
        found = [i for i in found if any(ident.key(p) in keys for p in i.people)]
    opened = found if state == "open" else store.items(user, "open")
    mutes = store.mutes()
    sev = {"high": 0, "medium": 0, "other": 0}
    for i in opened:
        if readable(i):
            key = i.severity if i.severity in ("high", "medium") else "other"
            sev[key] += 1
    return ListOut(
        items=[_out(request, i, mutes) for i in found if readable(i)],
        open=sum(1 for i in opened if readable(i)),
        restricted=sum(1 for i in opened if not readable(i)),
        muted=len(mutes),
        reasons=dict(REASONS),
        by_severity=sev,
    )


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
    items about that person under any form of the name (ADR-0038 row 27)."""
    return await run_in_threadpool(_list, request, user, state, unreviewed, person)


def _one(request: Request, user: User, item_id: str) -> ItemOut:
    store = _store(request)
    item = store.get(item_id, user)
    if not _readable(request, user)(item):
        raise ForbiddenError("This alert read a source you cannot read")
    return _out(request, item, store.mutes())


@router.get("/alerts/mutes")
async def list_mutes(request: Request, user: CurrentUser) -> list[MuteOut]:
    """Active mutes, soonest to expire first. Everyone may see what is muted."""
    mutes = await run_in_threadpool(_store(request).mutes)
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
    return await run_in_threadpool(_one, request, user, item_id)


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
    item = await run_in_threadpool(_one, request, user, item_id)
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


def _approve_agent(request: Request, user: User, item: ItemOut) -> None:
    """Approved on an agent's alert marks the agent reviewed: its other open alerts (the
    standing review item among them) close as Approved, audited, and ai.review records it."""
    n = _store(request).close_subject(
        "ai_watch", item.subject, user, "approved", f"Approved with alert {item.item_id}",
        client_ip(request),
    )  # fmt: skip
    request.app.state.auth.audit.write(
        "ai.review", "success", user.user_id, client_ip(request),
        {"agent": item.subject.removeprefix("agent:"), "to": "approved",
         "via": "alert.close", "closed": n},
    )  # fmt: skip


def _review_target(item: ItemOut) -> tuple[str, str] | None:
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
    await run_in_threadpool(_one, request, user, item_id)
    await run_in_threadpool(_store(request).reopen, item_id, user, client_ip(request))
    return await run_in_threadpool(_one, request, user, item_id)


@router.post("/alerts/{item_id}/mute")
async def mute_alert(item_id: str, body: MuteIn, request: Request, user: AdminUser) -> ItemOut:
    """Close new alerts like this one (same kind and subject) for 7 or 30 days; the mute
    expires on its own. Admins only; audited as alert.mute."""
    await run_in_threadpool(_one, request, user, item_id)
    await run_in_threadpool(_store(request).mute, item_id, body.days, user, client_ip(request))
    return await run_in_threadpool(_one, request, user, item_id)


@router.delete("/alerts/mutes/{mute_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unmute(mute_id: str, request: Request, user: AdminUser) -> Response:
    """End a mute early. Audited as alert.unmute."""
    await run_in_threadpool(_store(request).unmute, mute_id, user, client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
