"""Around this event (ADR-0038 section 8). Router only."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.access import CurrentUser, client_ip
from app.auth.service import AuthService
from app.engine.views import permitted_sources
from app.search.around import around

router = APIRouter(tags=["search"])


class AroundOut(BaseModel):
    event_id: str
    at: str
    person: list[str]
    devices: list[str]
    addresses: list[str]
    joined_by_address: bool
    columns: list[str]
    rows: list[list[Any]]
    more: bool
    likely_cause: str | None
    likely_rule: str
    sql: str
    start: str
    end: str


@router.get("/events/{event_id}/around")
async def event_around(
    event_id: str,
    request: Request,
    user: CurrentUser,
    at: datetime,
) -> AroundOut:
    """Rows within 5 minutes of the event by the same person or device, from every source
    the caller may read; at most 50, newest last, with a Likely cause hint. Audited
    `search.around`."""
    when = at if at.tzinfo else at.replace(tzinfo=UTC)
    allowed = await run_in_threadpool(permitted_sources, request.app.state.meta, user)
    out = await run_in_threadpool(around, request.app.state.engine, allowed, event_id[:64], when)
    auth: AuthService = request.app.state.auth
    await run_in_threadpool(
        auth.audit.write, "search.around", "success", user.user_id, client_ip(request),
        {"event_id": event_id[:64], "rows": len(out.rows), "sources_in_scope": out.sources},
    )  # fmt: skip
    return AroundOut(
        **{f: getattr(out, f) for f in AroundOut.model_fields},
    )
