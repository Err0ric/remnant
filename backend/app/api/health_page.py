"""The Health page (ADR-0019): per-machine agents and watched devices. Sources,
connectors, alert targets, and schedules come from their own endpoints. Reading is for
everyone signed in, in their own scope; changing watched devices is for administrators.
Router only."""

from dataclasses import asdict

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.api.access import AdminUser, CurrentUser, client_ip
from app.auth.service import AuthService
from app.engine.views import permitted_sources
from app.ingest.durable import quarantined_count
from app.search.health import HealthService

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


class HealthOut(BaseModel):
    devices: list[DeviceOut]
    agents: list[AgentOut]
    # Damaged lake files moved out of the way (SPEC D51); kept for an administrator.
    quarantined_files: int = 0


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
