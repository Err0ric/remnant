"""/api/handoff: send selected events to an alert target (ADR-0024). Admins and analysts;
the events are read again from the caller's own view. Router only."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.api.access import client_ip, require_role
from app.auth.users import User
from app.engine.duckdb import QueryScope
from app.engine.views import permitted_sources
from app.search.handoff import MAX_EVENTS, HandoffService

router = APIRouter(tags=["handoff"])
Sender = Annotated[User, Depends(require_role("admin", "analyst"))]


class HandoffIn(BaseModel):
    target_id: str = Field(min_length=1, max_length=64)
    event_ids: list[str] = Field(min_length=1, max_length=MAX_EVENTS)
    note: str = Field(default="", max_length=2000)


class HandoffOut(BaseModel):
    target_id: str
    sent: int
    withheld_local_only: int
    not_found: int


@router.post("/handoff")
async def handoff(body: HandoffIn, request: Request, user: Sender) -> HandoffOut:
    """Queue the chosen events for one alert target, with a note. Events from local-only
    sources go only to targets on private addresses. Audited as handoff.send."""
    allowed = await run_in_threadpool(permitted_sources, request.app.state.meta, user)
    svc: HandoffService = request.app.state.handoff
    result = await run_in_threadpool(
        svc.send,
        user.user_id,
        user.username,
        QueryScope(sources=allowed),
        body.event_ids,
        body.target_id,
        body.note,
        client_ip(request),
    )
    return HandoffOut(
        target_id=result.target_id,
        sent=result.sent,
        withheld_local_only=result.withheld_local_only,
        not_found=result.not_found,
    )
