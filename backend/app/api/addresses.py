"""Who had an address at a time (ADR-0020 row 1), from logon, User-ID, and GlobalProtect
events in the caller's sources. Audited as address.lookup. Router only."""

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.access import CurrentUser, client_ip
from app.auth.service import AuthService
from app.core.errors import AppError
from app.engine.duckdb import QueryEngine, QueryScope
from app.engine.views import permitted_sources
from app.search.addresses import MAX_AGE_HOURS, lookup

router = APIRouter(tags=["addresses"])


class HolderOut(BaseModel):
    kind: str
    name: str
    last_seen: str
    events: int


class AddressOut(BaseModel):
    ip: str
    at: str
    max_age_hours: int
    holders: list[HolderOut]


@router.get("/addresses/{ip}")
async def address(
    ip: str, request: Request, user: CurrentUser, at: datetime | None = None
) -> AddressOut:
    """People and machines seen with this address in the 12 hours up to `at` (default
    now), newest first."""
    # A time without a zone is UTC, like every other time in the API.
    when = (at or datetime.now(UTC)) if (at is None or at.tzinfo) else at.replace(tzinfo=UTC)
    when = when.astimezone(UTC)
    allowed = await run_in_threadpool(permitted_sources, request.app.state.meta, user)
    engine: QueryEngine = request.app.state.engine
    auth: AuthService = request.app.state.auth
    detail: dict[str, object] = {"ip": ip[:64], "at": when.isoformat(), "sources_in_scope": allowed}
    try:
        holders = await run_in_threadpool(lookup, engine, QueryScope(allowed), ip, when)
    except AppError as exc:
        detail["error"] = type(exc).__name__
        await run_in_threadpool(
            auth.audit.write, "address.lookup", "failure", user.user_id, client_ip(request), detail
        )
        raise
    await run_in_threadpool(
        auth.audit.write, "address.lookup", "success", user.user_id, client_ip(request), detail
    )
    return AddressOut(
        ip=ip,
        at=when.isoformat(),
        max_age_hours=MAX_AGE_HOURS,
        holders=[
            HolderOut(kind=h.kind, name=h.name, last_seen=h.last_seen, events=h.events)
            for h in holders
        ],
    )
