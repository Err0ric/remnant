"""/api/schedules: scheduled saved searches and rules (SPEC 5.5). Router only.

Admins and analysts create schedules; a schedule runs as its owner. The owner or an admin
may change, pause, resume, run now, or delete it. Everyone sees their own schedules and
shared ones (admins see all), but a run's numbers and rows are shown only to a viewer
who may read every source that run read; otherwise it is marked restricted.
"""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field, StringConstraints
from starlette.concurrency import run_in_threadpool

from app.alerts.dispatch import AlertDispatcher
from app.api.access import CurrentUser, client_ip, require_role
from app.auth.users import User
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.engine.views import permitted_sources
from app.meta.db import MetaDB
from app.search.dashboards import DashboardStore, can_edit
from app.search.schedules import (
    HeadlineKind,
    PanelView,
    PanelWidth,
    Schedule,
    ScheduleRun,
    ScheduleService,
    ThresholdKind,
)

router = APIRouter(tags=["schedules"])
Author = Annotated[User, Depends(require_role("admin", "analyst"))]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class ScheduleIn(BaseModel):
    kind: Literal["search", "rule"]
    target_id: str = Field(min_length=1, max_length=300)
    name: Name | None = None
    cron: str = Field(min_length=1, max_length=100)  # five fields, or hourly, daily, weekdays
    lookback_minutes: int | None = Field(default=None, ge=1, le=527_040)
    params: dict[str, Any] = Field(default_factory=dict, max_length=20)
    shared: bool = False
    threshold_kind: ThresholdKind | None = None
    threshold_value: float | None = Field(default=None, ge=0, le=1e12)
    # Alert targets (ADR-0007): chosen by the owner from those an admin set up.
    target_ids: list[str] = Field(default_factory=list, max_length=10)
    # The dashboard its panel goes on (ADR-0034): one the creator can change; by default
    # their own first dashboard, made when they have none.
    dashboard_id: str | None = Field(default=None, max_length=64)
    panel_size: Literal["tile", "third", "half", "full"] | None = None
    panel_view: PanelView | None = None


class ScheduleUpdate(BaseModel):
    name: Name | None = None
    cron: str | None = Field(default=None, min_length=1, max_length=100)
    lookback_minutes: int | None = Field(default=None, ge=0, le=527_040)  # 0: last interval
    shared: bool | None = None
    threshold_kind: ThresholdKind | Literal["none"] | None = None
    threshold_value: float | None = Field(default=None, ge=0, le=1e12)
    paused: bool | None = None
    target_ids: list[str] | None = Field(default=None, max_length=10)  # replaces the list
    panel_width: PanelWidth | None = None
    panel_view: PanelView | None = None
    # The panel's number (ADR-0034): row count, or sum, count distinct, or first value of a
    # result column, with a label. "" clears the column or label.
    headline_kind: HeadlineKind | None = None
    headline_column: str | None = Field(default=None, max_length=120)
    headline_label: str | None = Field(default=None, max_length=60)
    # A new definition (F37): run history is kept and the next run notes the change.
    kind: Literal["search", "rule"] | None = None
    target_id: str | None = Field(default=None, min_length=1, max_length=300)
    params: dict[str, Any] | None = Field(default=None, max_length=20)


class RunOut(BaseModel):
    run_id: str
    started_at: str
    range_start: str | None
    range_end: str | None
    status: str
    restricted: bool  # the viewer may not read every source this run read
    row_count: int | None
    elapsed_ms: int | None
    sources_in_scope: list[str]
    flagged: bool
    flag_reason: str | None
    error: str | None
    rule_run_id: str | None
    # A drop to zero right after a source this run read changed parser (F36).
    parser_change: str | None = None
    # The first run after the schedule's definition changed says what changed (F37).
    definition_change: str | None = None
    headline: str | None = None  # the panel's number for this run (ADR-0034)


class RunDetail(RunOut):
    columns: list[str]
    sample: list[list[Any]]
    truncated: bool


class ScheduleOut(BaseModel):
    schedule_id: str
    kind: str
    target_id: str
    name: str
    owner_id: str
    mine: bool
    shared: bool
    cron: str
    lookback_minutes: int | None
    params: dict[str, Any]
    threshold_kind: str | None
    threshold_value: float | None
    paused: bool
    paused_reason: str | None
    next_run_at: str | None
    last_run_at: str | None
    created_at: str
    recent: list[RunOut]  # newest first, up to 30: last run and sparkline
    target_ids: list[str]
    panel_width: str
    panel_view: str
    headline_kind: str = "rows"
    headline_column: str | None = None
    headline_label: str | None = None


def _svc(request: Request) -> ScheduleService:
    svc: ScheduleService = request.app.state.schedules
    return svc


def _visible_to(meta: MetaDB, viewer: User) -> Any:
    allowed = permitted_sources(meta, viewer)
    return lambda sources: allowed is None or set(sources) <= set(allowed)


def _run_out(r: ScheduleRun, can_read: Any, detail: bool = False) -> RunOut:
    restricted = not can_read(r.sources_in_scope)
    base: dict[str, Any] = {
        "run_id": r.run_id,
        "started_at": r.started_at,
        "range_start": r.range_start,
        "range_end": r.range_end,
        "status": r.status,
        "restricted": restricted,
        "row_count": None if restricted else r.row_count,
        "elapsed_ms": r.elapsed_ms,
        "sources_in_scope": [] if restricted else r.sources_in_scope,
        "flagged": False if restricted else r.flagged,
        "flag_reason": None if restricted else r.flag_reason,
        "error": None if restricted else r.error,
        "rule_run_id": None if restricted else r.rule_run_id,
        "parser_change": None if restricted else r.parser_change,
        "definition_change": r.definition_change,
        "headline": None if restricted else r.headline,
    }
    if not detail:
        return RunOut(**base)
    return RunDetail(
        **base,
        columns=[] if restricted else r.columns,
        sample=[] if restricted else r.sample,
        truncated=r.truncated,
    )


def _out(
    s: Schedule, viewer: User, runs: list[ScheduleRun], can_read: Any, targets: list[str]
) -> ScheduleOut:
    return ScheduleOut(
        schedule_id=s.schedule_id,
        kind=s.kind,
        target_id=s.target_id,
        name=s.name,
        owner_id=s.owner_id,
        mine=s.owner_id == viewer.user_id,
        shared=s.shared,
        cron=s.cron,
        lookback_minutes=s.lookback_minutes,
        params=s.params,
        threshold_kind=s.threshold_kind,
        threshold_value=s.threshold_value,
        paused=s.paused,
        paused_reason=s.paused_reason,
        next_run_at=s.next_run_at,
        last_run_at=s.last_run_at,
        created_at=s.created_at,
        recent=[_run_out(r, can_read) for r in runs],
        target_ids=targets,
        panel_width=s.panel_width,
        panel_view=s.panel_view,
        headline_kind=s.headline_kind,
        headline_column=s.headline_column,
        headline_label=s.headline_label,
    )


def _sees(s: Schedule, user: User) -> bool:
    return user.role == "admin" or s.owner_id == user.user_id or s.shared


def _manages(s: Schedule, user: User) -> None:
    if not (user.role == "admin" or s.owner_id == user.user_id):
        raise ForbiddenError("Only the owner or an administrator can change this schedule")


def _get_visible(svc: ScheduleService, schedule_id: str, user: User) -> Schedule:
    s = svc.get(schedule_id)
    if not _sees(s, user):
        raise NotFoundError("No such schedule")
    return s


def _audit(request: Request, action: str, user: User, detail: dict[str, Any]) -> None:
    request.app.state.auth.audit.write(action, "success", user.user_id, client_ip(request), detail)


def _list(svc: ScheduleService, meta: MetaDB, user: User) -> list[ScheduleOut]:
    can_read = _visible_to(meta, user)
    return [
        _out(s, user, svc.runs(s.schedule_id), can_read, svc.targets_of(s.schedule_id))
        for s in svc.all()
        if _sees(s, user)
    ]


@router.get("/schedules")
async def list_schedules(request: Request, user: CurrentUser) -> list[ScheduleOut]:
    return await run_in_threadpool(_list, _svc(request), request.app.state.meta, user)


@router.post("/schedules", status_code=status.HTTP_201_CREATED)
async def create_schedule(body: ScheduleIn, request: Request, user: Author) -> ScheduleOut:
    meta: MetaDB = request.app.state.meta
    svc = _svc(request)
    await run_in_threadpool(svc.check_targets, body.target_ids)
    s = await run_in_threadpool(
        svc.create,
        user,
        body.kind,
        body.target_id,
        body.name,
        body.cron,
        body.lookback_minutes,
        body.params,
        body.shared,
        body.threshold_kind,
        body.threshold_value,
    )
    await run_in_threadpool(svc.set_targets, s.schedule_id, body.target_ids)
    detail: dict[str, Any] = {
        "schedule_id": s.schedule_id,
        "kind": s.kind,
        "target_id": s.target_id,
    }
    detail |= {"cron": s.cron, "alert_targets": body.target_ids}
    await run_in_threadpool(_audit, request, "schedule.create", user, detail)
    dashboards: DashboardStore = request.app.state.dashboards

    def place() -> str:
        # The dashboard asked for when the user may change it (a browser can remember one
        # since deleted or unshared), else their own first dashboard.
        board = None
        if body.dashboard_id:
            try:
                board = dashboards.get(body.dashboard_id, user)
            except NotFoundError:
                board = None
            if board is not None and not can_edit(board, user):
                board = None
        if board is None:
            board = dashboards.default_for(user)
        dashboards.set_panel(
            board.dashboard_id,
            user,
            s.schedule_id,
            size=body.panel_size,
            view=body.panel_view,
        )
        return board.dashboard_id

    board_id = await run_in_threadpool(place)
    await run_in_threadpool(
        _audit,
        request,
        "dashboard.panel_add",
        user,
        {"dashboard_id": board_id, "schedule_id": s.schedule_id},
    )
    return _out(s, user, [], _visible_to(meta, user), sorted(set(body.target_ids)))


@router.patch("/schedules/{schedule_id}")
async def update_schedule(
    schedule_id: str, body: ScheduleUpdate, request: Request, user: CurrentUser
) -> ScheduleOut:
    svc, meta = _svc(request), request.app.state.meta
    s = await run_in_threadpool(_get_visible, svc, schedule_id, user)
    _manages(s, user)
    if body.target_ids is not None:
        await run_in_threadpool(svc.check_targets, body.target_ids)
    changes = body.model_dump(exclude={"target_ids"})
    updated = await run_in_threadpool(lambda: svc.update(s, **changes))
    if body.target_ids is not None:
        await run_in_threadpool(svc.set_targets, schedule_id, body.target_ids)
    action = (
        "schedule.pause"
        if body.paused is True
        else "schedule.resume"
        if body.paused is False and s.paused
        else "schedule.update"
    )
    await run_in_threadpool(
        _audit,
        request,
        action,
        user,
        {"schedule_id": schedule_id, **body.model_dump(exclude_none=True)},
    )
    runs = await run_in_threadpool(svc.runs, schedule_id)
    targets = await run_in_threadpool(svc.targets_of, schedule_id)
    return _out(updated, user, runs, _visible_to(meta, user), targets)


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str, request: Request, user: CurrentUser) -> Response:
    svc = _svc(request)
    s = await run_in_threadpool(_get_visible, svc, schedule_id, user)
    _manages(s, user)

    await run_in_threadpool(svc.delete, s)
    await run_in_threadpool(
        _audit,
        request,
        "schedule.delete",
        user,
        {"schedule_id": schedule_id, "owner_id": s.owner_id},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/schedules/{schedule_id}/run")
async def run_now(schedule_id: str, request: Request, user: CurrentUser) -> RunDetail:
    svc, meta = _svc(request), request.app.state.meta
    s = await run_in_threadpool(_get_visible, svc, schedule_id, user)
    _manages(s, user)
    if s.paused:
        raise ConflictError("This schedule is paused; resume it first")
    await run_in_threadpool(
        _audit,
        request,
        "schedule.run_now",
        user,
        {"schedule_id": schedule_id, "owner_id": s.owner_id},
    )
    run = await run_in_threadpool(svc.run, s)
    out = _run_out(run, _visible_to(meta, user), detail=True)
    assert isinstance(out, RunDetail)
    return out


@router.get("/schedules/{schedule_id}/runs/{run_id}")
async def get_run(schedule_id: str, run_id: str, request: Request, user: CurrentUser) -> RunDetail:
    svc, meta = _svc(request), request.app.state.meta
    await run_in_threadpool(_get_visible, svc, schedule_id, user)
    runs = await run_in_threadpool(svc.runs, schedule_id, 1000)
    for r in runs:
        if r.run_id == run_id:
            out = _run_out(r, _visible_to(meta, user), detail=True)
            assert isinstance(out, RunDetail)
            return out
    raise NotFoundError("No such run")


class DeliveryOut(BaseModel):
    delivery_id: str
    target_name: str | None
    kind: str
    status: str
    attempts: int
    next_attempt_at: str | None
    last_error: str | None
    created_at: str
    sent_at: str | None


@router.get("/schedules/{schedule_id}/deliveries")
async def deliveries(schedule_id: str, request: Request, user: CurrentUser) -> list[DeliveryOut]:
    """Alert delivery status for a schedule the viewer can see (no message content)."""
    svc = _svc(request)
    await run_in_threadpool(_get_visible, svc, schedule_id, user)
    dispatcher: AlertDispatcher = request.app.state.alert_dispatcher
    rows = await run_in_threadpool(dispatcher.deliveries, schedule_id)
    return [
        DeliveryOut(
            delivery_id=d.delivery_id,
            target_name=d.target_name,
            kind=d.kind,
            status=d.status,
            attempts=d.attempts,
            next_attempt_at=d.next_attempt_at,
            last_error=d.last_error,
            created_at=d.created_at,
            sent_at=d.sent_at,
        )
        for d in rows
    ]
