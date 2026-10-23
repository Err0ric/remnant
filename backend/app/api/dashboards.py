"""/api/dashboards: named, personal or shared dashboards of schedule panels (ADR-0034).
Router only.

A viewer sees dashboards they own, shared ones, and (admins) all. The owner or an admin
changes one. A panel can be added only for a schedule the user can see; its numbers are
still shown per viewer through /api/schedules, Restricted when the viewer may not read
every source the run read. Every change and acknowledgement is audited.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field, StringConstraints
from starlette.concurrency import run_in_threadpool

from app.api.access import CurrentUser, client_ip, require_role
from app.api.schedules import _get_visible, _visible_to
from app.auth.users import User
from app.core.errors import ConflictError
from app.search.dashboards import (
    Dashboard,
    DashboardStore,
    Panel,
    PanelSize,
    PanelView,
    can_edit,
)
from app.search.schedules import ScheduleService

router = APIRouter(tags=["dashboards"])
Author = Annotated[User, Depends(require_role("admin", "analyst"))]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Section = Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)]


class PanelOut(BaseModel):
    schedule_id: str
    section: str
    position: int
    size: str
    view: str


class DashboardOut(BaseModel):
    dashboard_id: str
    name: str
    owner_id: str
    mine: bool
    shared: bool
    can_edit: bool
    panels: list[PanelOut]
    acks: dict[str, str]  # schedule id -> acknowledged run id
    sections: list[str]  # in their stored order; panels name theirs ("" is none)
    updated_at: str


class DashboardIn(BaseModel):
    name: Name
    shared: bool = False


class DashboardUpdate(BaseModel):
    name: Name | None = None
    shared: bool | None = None


class PanelIn(BaseModel):
    section: Section | None = None
    position: int | None = Field(default=None, ge=0, le=100_000)
    size: PanelSize | None = None
    view: PanelView | None = None


class OrderIn(BaseModel):
    schedule_ids: list[str] = Field(max_length=200)


class LayoutSection(BaseModel):
    name: Section  # "" is no section
    schedule_ids: list[str] = Field(max_length=200)


class LayoutIn(BaseModel):
    sections: list[LayoutSection] = Field(max_length=100)


class SectionRename(BaseModel):
    old: Section
    new: Section


class AckIn(BaseModel):
    schedule_id: str = Field(min_length=1, max_length=64)
    run_id: str = Field(min_length=1, max_length=64)


def _store(request: Request) -> DashboardStore:
    store: DashboardStore = request.app.state.dashboards
    return store


def _out(d: Dashboard, user: User) -> DashboardOut:
    return DashboardOut(
        dashboard_id=d.dashboard_id,
        name=d.name,
        owner_id=d.owner_id,
        mine=d.owner_id == user.user_id,
        shared=d.shared,
        can_edit=can_edit(d, user),
        panels=[_panel(p) for p in d.panels],
        acks=d.acks,
        sections=d.sections,
        updated_at=d.updated_at,
    )


def _panel(p: Panel) -> PanelOut:
    return PanelOut(
        schedule_id=p.schedule_id,
        section=p.section,
        position=p.position,
        size=p.size,
        view=p.view,
    )


def _audit(request: Request, action: str, user: User, detail: dict[str, Any]) -> None:
    request.app.state.auth.audit.write(action, "success", user.user_id, client_ip(request), detail)


@router.get("/dashboards")
async def list_dashboards(request: Request, user: CurrentUser) -> list[DashboardOut]:
    """Dashboards the viewer sees, their own first. A user with none yet gets an empty
    "My dashboard" the first time they create a panel, not on reading."""
    found = await run_in_threadpool(_store(request).visible, user)
    return [_out(d, user) for d in found]


@router.post("/dashboards", status_code=status.HTTP_201_CREATED)
async def create_dashboard(body: DashboardIn, request: Request, user: Author) -> DashboardOut:
    d = await run_in_threadpool(_store(request).create, user, body.name, body.shared)
    await run_in_threadpool(
        _audit,
        request,
        "dashboard.create",
        user,
        {"dashboard_id": d.dashboard_id, "name": d.name, "shared": d.shared},
    )
    return _out(d, user)


@router.patch("/dashboards/{dashboard_id}")
async def update_dashboard(
    dashboard_id: str, body: DashboardUpdate, request: Request, user: CurrentUser
) -> DashboardOut:
    before, after = await run_in_threadpool(
        _store(request).update, dashboard_id, user, body.name, body.shared
    )
    await run_in_threadpool(
        _audit,
        request,
        "dashboard.update",
        user,
        {
            "dashboard_id": dashboard_id,
            "from": {"name": before.name, "shared": before.shared},
            "to": {"name": after.name, "shared": after.shared},
        },
    )
    return _out(after, user)


@router.delete("/dashboards/{dashboard_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dashboard(dashboard_id: str, request: Request, user: CurrentUser) -> Response:
    """Deletes the dashboard and its panel layout; the schedules keep running."""
    d = await run_in_threadpool(_store(request).delete, dashboard_id, user)
    await run_in_threadpool(
        _audit,
        request,
        "dashboard.delete",
        user,
        {"dashboard_id": dashboard_id, "name": d.name, "panels": len(d.panels)},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/dashboards/{dashboard_id}/panels/{schedule_id}")
async def set_panel(
    dashboard_id: str, schedule_id: str, body: PanelIn, request: Request, user: CurrentUser
) -> DashboardOut:
    """Add a schedule's panel, or change its section, position, size, or view."""
    svc: ScheduleService = request.app.state.schedules
    await run_in_threadpool(_get_visible, svc, schedule_id, user)
    changes = body.model_dump(exclude_none=True)
    added, d = await run_in_threadpool(
        lambda: _store(request).set_panel(dashboard_id, user, schedule_id, **changes)
    )
    await run_in_threadpool(
        _audit,
        request,
        "dashboard.panel_add" if added else "dashboard.panel_update",
        user,
        {"dashboard_id": dashboard_id, "schedule_id": schedule_id, **changes},
    )
    return _out(d, user)


@router.delete(
    "/dashboards/{dashboard_id}/panels/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_panel(
    dashboard_id: str, schedule_id: str, request: Request, user: CurrentUser
) -> Response:
    """Takes the panel off this dashboard; the schedule keeps running."""
    await run_in_threadpool(_store(request).remove_panel, dashboard_id, user, schedule_id)
    await run_in_threadpool(
        _audit,
        request,
        "dashboard.panel_remove",
        user,
        {"dashboard_id": dashboard_id, "schedule_id": schedule_id},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/dashboards/{dashboard_id}/order")
async def reorder(
    dashboard_id: str, body: OrderIn, request: Request, user: CurrentUser
) -> DashboardOut:
    d = await run_in_threadpool(_store(request).reorder, dashboard_id, user, body.schedule_ids)
    await run_in_threadpool(
        _audit,
        request,
        "dashboard.panel_update",
        user,
        {"dashboard_id": dashboard_id, "order": body.schedule_ids},
    )
    return _out(d, user)


@router.put("/dashboards/{dashboard_id}/layout")
async def set_layout(
    dashboard_id: str, body: LayoutIn, request: Request, user: CurrentUser
) -> DashboardOut:
    """The whole arrangement: sections in order, each with its panels in order. Drag and
    drop, keyboard moves, section order, adding an empty section, and deleting one (its
    panels move to no section) all send this. Audited dashboard.layout with before and
    after."""
    layout = [(s.name, s.schedule_ids) for s in body.sections]
    before, after = await run_in_threadpool(_store(request).set_layout, dashboard_id, user, layout)

    def shape(d: Dashboard) -> list[dict[str, Any]]:
        order = sorted(d.panels, key=lambda p: p.position)
        names = ["", *d.sections]
        return [
            {"section": n, "panels": [p.schedule_id for p in order if p.section == n]}
            for n in names
        ]

    await run_in_threadpool(
        _audit,
        request,
        "dashboard.layout",
        user,
        {"dashboard_id": dashboard_id, "from": shape(before), "to": shape(after)},
    )
    return _out(after, user)


@router.patch("/dashboards/{dashboard_id}/sections")
async def rename_section(
    dashboard_id: str, body: SectionRename, request: Request, user: CurrentUser
) -> DashboardOut:
    d = await run_in_threadpool(
        _store(request).rename_section, dashboard_id, user, body.old, body.new
    )
    await run_in_threadpool(
        _audit,
        request,
        "dashboard.section_rename",
        user,
        {"dashboard_id": dashboard_id, "from": body.old, "to": body.new},
    )
    return _out(d, user)


@router.post("/dashboards/{dashboard_id}/acknowledge", status_code=status.HTTP_204_NO_CONTENT)
async def acknowledge(
    dashboard_id: str, body: AckIn, request: Request, user: CurrentUser
) -> Response:
    """Clear a flagged run from Needs attention until the next flagged run. Only the
    schedule's latest run, only when flagged, and only for a viewer who may read it."""
    svc: ScheduleService = request.app.state.schedules
    await run_in_threadpool(_get_visible, svc, body.schedule_id, user)
    runs = await run_in_threadpool(svc.runs, body.schedule_id, 1)
    latest = runs[0] if runs else None
    if latest is None or latest.run_id != body.run_id or not latest.flagged:
        raise ConflictError("Only the latest flagged run can be acknowledged")
    can_read = _visible_to(request.app.state.meta, user)
    if not can_read(latest.sources_in_scope):
        raise ConflictError("This run is restricted for you")
    await run_in_threadpool(
        _store(request).acknowledge, dashboard_id, user, body.schedule_id, body.run_id
    )
    await run_in_threadpool(
        _audit,
        request,
        "dashboard.acknowledge",
        user,
        {
            "dashboard_id": dashboard_id,
            "schedule_id": body.schedule_id,
            "run_id": body.run_id,
            "reason": latest.flag_reason,
        },
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
