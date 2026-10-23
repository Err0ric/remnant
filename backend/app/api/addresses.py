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
from app.search.addresses import MAX_AGE_HOURS, Span, spans

router = APIRouter(tags=["addresses"])


class HolderOut(BaseModel):
    kind: str
    name: str
    last_seen: str
    events: int


class SpanOut(BaseModel):
    """One match that held the address at the time (D107 C1): what it was, when it
    started and ended, whether the end was assumed (capped), and the source."""

    kind: str  # vpn | userid | logon | dhcp | signin
    start: str
    end: str | None
    capped: bool
    person: str | None
    machine: str | None
    mac: str | None
    source: str


class AddressOut(BaseModel):
    ip: str
    at: str
    max_age_hours: int
    holders: list[HolderOut]
    spans: list[SpanOut]


@router.get("/addresses/{ip}")
async def address(
    ip: str, request: Request, user: CurrentUser, at: datetime | None = None
) -> AddressOut:
    """The spans that held this address at `at` (default now), newest first: logons,
    User-ID, GlobalProtect, DHCP leases, and the sign-ins that name a machine's person
    (ADR-0029)."""
    # A time without a zone is UTC, like every other time in the API.
    when = (at or datetime.now(UTC)) if (at is None or at.tzinfo) else at.replace(tzinfo=UTC)
    when = when.astimezone(UTC)
    allowed = await run_in_threadpool(permitted_sources, request.app.state.meta, user)
    engine: QueryEngine = request.app.state.engine
    auth: AuthService = request.app.state.auth
    detail: dict[str, object] = {"ip": ip[:64], "at": when.isoformat(), "sources_in_scope": allowed}
    try:
        found = await run_in_threadpool(spans, engine, QueryScope(allowed), ip, when)
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
        holders=_holders(found),
        spans=[SpanOut(**{f: getattr(x, f) for f in SpanOut.model_fields}) for x in found],
    )


def _holders(found: list[Span]) -> list[HolderOut]:
    """People and machines from the spans, newest first; DHCP never names a person."""
    out: dict[tuple[str, str], HolderOut] = {}
    for x in found:
        for kind, name in (("user", x.person), ("host", x.machine)):
            if name and (kind, name) not in out and not (kind == "user" and x.kind == "dhcp"):
                out[(kind, name)] = HolderOut(kind=kind, name=name, last_seen=x.start, events=1)
    return list(out.values())
