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

from app.alerts.items import MAX_MUTE_DAYS, MAX_NOTE, REASONS, AlertItem, AlertItems, Mute
from app.api.access import AdminUser, CurrentUser, client_ip, require_role
from app.auth.users import User
from app.core.errors import ForbiddenError, ParamInvalidError
from app.engine.views import permitted_sources

router = APIRouter(tags=["alerts"])
Decider = Annotated[User, Depends(require_role("admin", "analyst"))]
State = Literal["open", "closed", "all"]


class EventOut(BaseModel):
    at: str
    user: str | None
    action: str
    reason: str | None
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
    severity: str | None  # high | medium for AI Watch items (ADR-0035 row 11)
    muted_until: str | None
    history: list[EventOut]


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


class CloseIn(BaseModel):
    reason: Literal["true_positive", "benign", "false_positive", "follow_up"]
    note: str | None = Field(default=None, max_length=MAX_NOTE)
    # AI Watch items for a service or MCP server: closing may also decide its review
    # status (owner, 2026-10-29). Admins only; None leaves it unreviewed.
    review_status: Literal["approved", "not_approved"] | None = None


class MuteIn(BaseModel):
    days: int = Field(ge=1, le=MAX_MUTE_DAYS)


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
        close_reason_label=REASONS.get(i.close_reason or ""),
        note=i.note,
        resolved=i.resolved,
        schedule_id=i.schedule_id,
        severity=i.severity,
        muted_until=until,
        history=[
            EventOut(
                at=h.at,
                user=_name(request, h.user_id),
                action=h.action,
                reason=h.reason,
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


def _list(request: Request, user: User, state: str, unreviewed: bool = False) -> ListOut:
    store = _store(request)
    readable = _readable(request, user)
    found = store.items(user, state)
    if unreviewed:
        found = [i for i in found if _unreviewed(request, i)]
    opened = found if state == "open" else store.items(user, "open")
    mutes = store.mutes()
    return ListOut(
        items=[_out(request, i, mutes) for i in found if readable(i)],
        open=sum(1 for i in opened if readable(i)),
        restricted=sum(1 for i in opened if not readable(i)),
        muted=len(mutes),
        reasons={k: v for k, v in REASONS.items() if k != "muted"},
    )


@router.get("/alerts")
async def list_alerts(
    request: Request,
    user: CurrentUser,
    state: Annotated[State, Query()] = "open",
    unreviewed: Annotated[bool, Query()] = False,
) -> ListOut:
    """The viewer's alerts, newest first: open by default, or closed, or all. With
    `unreviewed`, only AI Watch items whose service or MCP server is still not reviewed,
    closed ones included: what AI Watch's "not reviewed" line links to."""
    return await run_in_threadpool(_list, request, user, state, unreviewed)


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


@router.post("/alerts/{item_id}/close")
async def close_alert(item_id: str, body: CloseIn, request: Request, user: Decider) -> ItemOut:
    """Close with a reason; a note is required for False positive and Needs follow-up.
    Audited as alert.close. With `review_status` (admins, AI Watch service and MCP server
    items), the service or server is approved or not approved as on AI usage, audited
    as ai.service_change or ai.mcp_change."""
    item = await run_in_threadpool(_one, request, user, item_id)
    target = _review_target(item) if body.review_status else None
    if body.review_status:
        if user.role != "admin":
            raise ForbiddenError("Only an administrator sets the review status")
        if target is None:
            raise ParamInvalidError("This alert has no service or MCP server to review")
    await run_in_threadpool(
        _store(request).close, item_id, user, body.reason, body.note, client_ip(request)
    )
    if target is not None and body.review_status:
        await run_in_threadpool(_set_review, request, user, target, body.review_status)
    return await run_in_threadpool(_one, request, user, item_id)


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
    """Close new alerts like this one (same kind and subject) for 1 to 30 days; the mute
    expires on its own. Admins only; audited as alert.mute."""
    await run_in_threadpool(_one, request, user, item_id)
    await run_in_threadpool(_store(request).mute, item_id, body.days, user, client_ip(request))
    return await run_in_threadpool(_one, request, user, item_id)


@router.delete("/alerts/mutes/{mute_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unmute(mute_id: str, request: Request, user: AdminUser) -> Response:
    """End a mute early. Audited as alert.unmute."""
    await run_in_threadpool(_store(request).unmute, mute_id, user, client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
