"""GET /api/overview: the home page's numbers (ADR-0008). Router only."""

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.access import CurrentUser, client_ip
from app.search.overview import OverviewService

router = APIRouter(tags=["overview"])


class SourceVolumeOut(BaseModel):
    source_id: str
    counts: list[int]
    typical: list[float | None]
    marks: list[str]


class SourceHealthOut(BaseModel):
    source_id: str
    state: str
    last_event_at: str | None
    files_waiting: int
    records_skipped: int
    error: str | None
    # Set while a quiet-source alert (ADR-0014) says nothing has arrived for too long.
    quiet_since: str | None = None


class DetectionOut(BaseModel):
    kind: str
    name: str
    level: str | None
    count: int
    reason: str | None
    started_at: str
    run_id: str
    schedule_id: str | None


class PausedOut(BaseModel):
    schedule_id: str
    name: str
    kind: str
    reason: str | None


class TargetHealthOut(BaseModel):
    target_id: str
    name: str
    kind: str
    consecutive_failures: int
    failing: bool
    last_error: str | None


class AlertHealthOut(BaseModel):
    targets: list[TargetHealthOut]
    failed_deliveries: int


class OverviewOut(BaseModel):
    generated_at: str
    hours: list[str]
    volume: list[SourceVolumeOut]
    sources: list[SourceHealthOut]
    detections: list[DetectionOut]
    paused: list[PausedOut]
    alerts: AlertHealthOut | None


@router.get("/overview")
async def overview(request: Request, user: CurrentUser) -> OverviewOut:
    svc: OverviewService = request.app.state.overview
    result, computed = await run_in_threadpool(svc.get, user)
    if computed:  # a cached answer read nothing new, so it is not audited again
        detail: dict[str, Any] = {"sources_in_scope": result.sources_in_scope}
        await run_in_threadpool(
            request.app.state.auth.audit.write,
            "overview.view",
            "success",
            user.user_id,
            client_ip(request),
            detail,
        )
    data = asdict(result)
    data.pop("sources_in_scope")
    # Quiet state is read fresh on every call, not cached with the numbers above.
    watches = await run_in_threadpool(request.app.state.quiet.all)
    quiet = {w.source_id: w.quiet_since for w in watches if w.state == "quiet"}
    for s in data["sources"]:
        s["quiet_since"] = quiet.get(s["source_id"])
    return OverviewOut(**data)
