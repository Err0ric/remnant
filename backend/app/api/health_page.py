"""The Health page (ADR-0019): per-machine agents and watched devices. Sources,
connectors, alert targets, and schedules come from their own endpoints. Reading is for
everyone signed in, in their own scope; changing watched devices is for administrators.
Router only."""

from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.api.access import AdminUser, CurrentUser, client_ip
from app.auth.service import AuthService
from app.core.client_errors import ClientErrors
from app.engine.views import permitted_sources
from app.ingest.durable import quarantined_count
from app.search.health import HealthService
from app.search.rollup_status import status as rollup_status

router = APIRouter(tags=["health"])


class DeviceOut(BaseModel):
    device_id: str
    name: str
    match: str
    silence_s: int
    target_ids: list[str]  # empty for non-admins
    state: str  # healthy | attention | unhealthy | unknown
    reason: str | None
    last_seen: str | None
    hourly: list[int]


class AgentOut(BaseModel):
    kind: str
    source_id: str
    machine: str
    last_seen: str | None
    events_24h: int
    state: str
    reason: str | None
    dropped_24h: int = 0  # records the hooks plugin lost (queue full or over 7 days old)
    queued: int = 0  # records waiting on the machine at its last check-in
    late_24h: int = 0  # delivered more than 5 minutes after they happened
    missing: int = 0  # sequence numbers that never arrived, over 8 days
    gaps: list[str] = []


class RollupOut(BaseModel):
    name: str
    label: str
    days_built: int
    pending: int | None  # null: not checked since the server started
    last_run: str | None
    last_built: str | None
    today_built: str | None
    today_cutoff: str | None
    state: str
    reason: str | None


class ClientErrorOut(BaseModel):
    at: str
    error_id: str
    kind: str  # render | panel | chunk | unhandled
    name: str
    message: str
    route: str
    build: str
    stale: bool  # the tab ran an older build than the server serves


class HealthOut(BaseModel):
    devices: list[DeviceOut]
    agents: list[AgentOut]
    # Daily and today-so-far page rollups: counts and times only, no source names.
    rollups: list[RollupOut] = []
    # Damaged lake files moved out of the way (SPEC D51); kept for an administrator.
    quarantined_files: int = 0
    # Pages and panels that failed in browsers, the last 24 hours (owner 2026-11-02); for
    # administrators only.
    client_errors: list[ClientErrorOut] = []


class DeviceIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    match: str = Field(min_length=1, max_length=253)
    silence_s: int
    target_ids: list[str] = Field(default_factory=list, max_length=10)


def _svc(request: Request) -> HealthService:
    svc: HealthService = request.app.state.health
    return svc


@router.get("/health-checks")
async def health_checks(request: Request, user: CurrentUser) -> HealthOut:
    """Watched devices and per-machine agents, from the sources the caller may read.
    Audited as health.view."""
    allowed = await run_in_threadpool(permitted_sources, request.app.state.meta, user)
    svc = _svc(request)
    devices = await run_in_threadpool(svc.device_status, allowed)
    agents = await run_in_threadpool(svc.agents, allowed)
    auth: AuthService = request.app.state.auth
    await run_in_threadpool(
        auth.audit.write,
        "health.view",
        "success",
        user.user_id,
        client_ip(request),
        {"sources_in_scope": allowed},
    )
    admin = allowed is None or user.role == "admin"
    return HealthOut(
        devices=[
            DeviceOut(
                device_id=s.device.device_id,
                name=s.device.name,
                match=s.device.match,
                silence_s=s.device.silence_s,
                target_ids=s.device.target_ids if admin else [],
                state=s.state,
                reason=s.reason,
                last_seen=s.last_seen,
                hourly=s.hourly,
            )
            for s in devices
        ],
        agents=[AgentOut(**asdict(a)) for a in agents],
        quarantined_files=await run_in_threadpool(quarantined_count, request.app.state.lake_dir),
        rollups=await run_in_threadpool(_rollups, request),
        client_errors=_client_errors(request) if admin else [],
    )


def _client_errors(request: Request) -> list[ClientErrorOut]:
    store: ClientErrors = request.app.state.client_errors
    return [
        ClientErrorOut(
            at=e.at.isoformat(), error_id=e.error_id, kind=e.kind, name=e.name,
            message=e.message, route=e.route, build=e.build, stale=e.stale,
        )
        for e in store.recent(datetime.now(UTC))
    ]  # fmt: skip


def _rollups(request: Request) -> list[RollupOut]:
    state = request.app.state
    now = datetime.now(UTC)
    return [
        RollupOut(**asdict(rollup_status(name, getattr(state, name), state.rollup_runs, now)))
        for name in ("auth_rollup", "m365_rollup", "ai_rollup")
    ]


class SpeedOut(BaseModel):
    route: str
    requests: int
    p50_ms: float
    p95_ms: float
    max_ms: float
    db_p50_ms: float
    wait_p95_ms: float
    cache_hits: int
    cached: int


@router.get("/health-checks/speed")
async def speed(request: Request, _: AdminUser) -> list[SpeedOut]:
    """Page speed per route over the last 24 hours (since the server started, if later),
    from the Server-Timing of each request: requests, p50 and p95 total, DuckDB p50, slot
    wait p95, and page cache hits. Routes only, never values or callers. Administrators."""
    return [SpeedOut(**asdict(r)) for r in request.app.state.speed.stats()]


class RefreshHourOut(BaseModel):
    hour: datetime
    refreshes: int
    failed: int


class RefreshesOut(BaseModel):
    views: int  # default views kept fresh now (loaded in the last 10 minutes)
    hours: list[RefreshHourOut]


@router.get("/health-checks/refreshes")
async def refreshes(request: Request, _: AdminUser) -> RefreshesOut:
    """Background refreshes of the default views (D147) per hour over the last 24 hours,
    and how many views are kept fresh now. A view stops refreshing 10 minutes after its
    last load. Administrators."""
    views, hours = request.app.state.refresher.per_hour()
    return RefreshesOut(
        views=views,
        hours=[
            RefreshHourOut(hour=datetime.fromtimestamp(h, UTC), refreshes=n, failed=f)
            for h, n, f in hours
        ],
    )


@router.post("/health-checks/devices", status_code=201)
async def add_device(body: DeviceIn, request: Request, user: AdminUser) -> dict[str, str]:
    """Watch a device by IP address or host name; `silence_s` 300 to 86400. Audited as
    device_watch.change."""
    d = await run_in_threadpool(
        _svc(request).save_device,
        None,
        body.name,
        body.match,
        body.silence_s,
        body.target_ids,
        user.user_id,
        client_ip(request),
    )
    return {"device_id": d.device_id}


@router.put("/health-checks/devices/{device_id}")
async def change_device(
    device_id: str, body: DeviceIn, request: Request, user: AdminUser
) -> dict[str, str]:
    """Change a watched device. Audited as device_watch.change."""
    d = await run_in_threadpool(
        _svc(request).save_device,
        device_id,
        body.name,
        body.match,
        body.silence_s,
        body.target_ids,
        user.user_id,
        client_ip(request),
    )
    return {"device_id": d.device_id}


@router.delete("/health-checks/devices/{device_id}", status_code=204)
async def delete_device(device_id: str, request: Request, user: AdminUser) -> None:
    """Stop watching a device. Audited as device_watch.change."""
    await run_in_threadpool(
        _svc(request).delete_device, device_id, user.user_id, client_ip(request)
    )
