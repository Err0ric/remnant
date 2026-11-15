"""/api/pins: the caller's own pins of saved searches and dashboards for the rail's
Pinned region (D259). Router only.

A pin is listed, and can be made, only while its target exists and the caller may see it:
a saved search they own or that is shared, a dashboard they own, a shared one, or any for
an admin. Nothing is taken from the client but the one target named. Pin and unpin are
audited; listing names only what the caller already sees, like `/searches`, and is not.
"""

from typing import Any

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.access import CurrentUser, client_ip
from app.auth.users import User
from app.core.errors import NotFoundError
from app.search.dashboards import DashboardStore
from app.search.pins import PinKind, PinStore
from app.search.saved import SavedSearchStore

router = APIRouter(tags=["pins"])


class PinOut(BaseModel):
    kind: PinKind
    id: str
    name: str


def _targets(request: Request, user: User) -> dict[tuple[str, str], str]:
    """Every target the caller may see, with its name."""
    searches: SavedSearchStore = request.app.state.searches
    boards: DashboardStore = request.app.state.dashboards
    out: dict[tuple[str, str], str] = {("search", s.id): s.name for s in searches.visible(user)}
    out.update({("dashboard", d.dashboard_id): d.name for d in boards.visible(user)})
    return out


def _listed(request: Request, user: User) -> list[PinOut]:
    store: PinStore = request.app.state.pins
    names = _targets(request, user)
    return [
        PinOut(kind=kind, id=target, name=names[(kind, target)])
        for kind, target in store.list(user.user_id)
        if (kind, target) in names
    ]


def _audit(request: Request, action: str, user: User, detail: dict[str, Any]) -> None:
    request.app.state.auth.audit.write(action, "success", user.user_id, client_ip(request), detail)


def _pin(request: Request, user: User, kind: PinKind, target_id: str) -> list[PinOut]:
    names = _targets(request, user)
    if (kind, target_id) not in names:
        raise NotFoundError(f"No such {'saved search' if kind == 'search' else 'dashboard'}")
    store: PinStore = request.app.state.pins
    if store.add(user.user_id, kind, target_id, names.keys()):
        _audit(request, "pin.add", user, {"kind": kind, "id": target_id})
    return _listed(request, user)


@router.get("/pins")
async def list_pins(request: Request, user: CurrentUser) -> list[PinOut]:
    """The caller's pins, oldest first, that they may still open."""
    return await run_in_threadpool(_listed, request, user)


@router.put("/pins/{kind}/{target_id}")
async def pin(kind: PinKind, target_id: str, request: Request, user: CurrentUser) -> list[PinOut]:
    """Pins a saved search or dashboard the caller may see, last; pinning it again changes
    nothing. At most five: 409 `conflict` until one is unpinned."""
    return await run_in_threadpool(_pin, request, user, kind, target_id)


@router.delete("/pins/{kind}/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unpin(kind: PinKind, target_id: str, request: Request, user: CurrentUser) -> Response:
    store: PinStore = request.app.state.pins
    if not await run_in_threadpool(store.remove, user.user_id, kind, target_id):
        raise NotFoundError("Not pinned")
    await run_in_threadpool(_audit, request, "pin.remove", user, {"kind": kind, "id": target_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
