"""GET /api/overview: the home page's numbers (ADR-0008). Router only."""

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.access import CurrentUser, client_ip
from app.search.overview import OverviewService

router = APIRouter(tags=["overview"])


class GapOut(BaseModel):
    start: str
    end: str | None
    hours: int
    ongoing: bool
    others_flowing: bool


class SourceVolumeOut(BaseModel):
    source_id: str
    counts: list[int]
    typical: list[float | None]
    marks: list[str]
    total: int
    gaps: list[GapOut]


class SourceHealthOut(BaseModel):
    source_id: str
    state: str
    last_event_at: str | None
    files_waiting: int
    records_skipped: int
    error: str | None
    rate_per_min: float
    # Set while a quiet-source alert (ADR-0014) says nothing has arrived for too long.
    quiet_since: str | None = None
    # The open source gap alert on this source, if any (review item 3): the footer and
    # Health count the same gaps the Alerts page lists. Not set once the source has sent
    # again after the alert last fired, even when no watch is left to mark it resolved.
    gap_alert: str | None = None


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
    events_24h: int
    history_days: int
    events_compared_24h: int
    events_usual_24h: float | None
    new_sources: list[str]


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
    gaps = await run_in_threadpool(request.app.state.alert_items.open_gaps)
    for s in data["sources"]:
        s["quiet_since"] = quiet.get(s["source_id"])
        gap = gaps.get(s["source_id"])
        last = s.get("last_event_at")
        if gap is not None and (last is None or _instant(last) <= _instant(gap[1])):
            s["gap_alert"] = gap[0]
    return OverviewOut(**data)


def _instant(iso: str) -> datetime:
    when = datetime.fromisoformat(iso)
    return when if when.tzinfo else when.replace(tzinfo=UTC)
