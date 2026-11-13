"""GET /api/overview: the home page's numbers (ADR-0008). Router only."""

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.access import CurrentUser, client_ip
from app.engine.views import permitted_sources
from app.meta.page_loads import PageLoadAudit, declared
from app.search.overview import OverviewService
from app.search.source_state import Condition, SourceInput, assess, needing_attention

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
    # server_events has events only when someone uses or probes the server: quiet is fine.
    quiet_expected: bool = False
    # One state for Health and the Dashboard footer (handoff item 4, app.search.source_state):
    # healthy, quiet, gap, attention, error, or paused.
    condition: Condition = "healthy"


class WaitOut(BaseModel):
    source_id: str
    last_event_at: str | None


class SourceSummaryOut(BaseModel):
    """ "N of M healthy", the quiet sources, gaps, and the longest wait, counted once."""

    total: int
    healthy: int
    quiet: list[WaitOut]
    gaps: int
    longest_wait: WaitOut | None


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
    by_person: bool = False


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
    source_summary: SourceSummaryOut


@router.get("/overview")
async def overview(request: Request, user: CurrentUser) -> OverviewOut:
    svc: OverviewService = request.app.state.overview
    result, computed = await run_in_threadpool(svc.get, user)
    visit = declared(request.headers)
    detail: dict[str, Any] = {"sources_in_scope": result.sources_in_scope}
    if visit is not None:
        # On the Dashboard (its page-load headers) the visit's `dashboard.view` row covers
        # it, also when cached; a new row is written at once when none covers it yet.
        loads: PageLoadAudit = request.app.state.page_loads
        scope = await run_in_threadpool(permitted_sources, request.app.state.meta, user)
        await run_in_threadpool(
            loads.record, visit, user.user_id, client_ip(request), ["overview"], None, scope,
            ("overview.view", detail),
        )  # fmt: skip
    elif computed:  # a cached answer read nothing new, so it is not audited again
        await run_in_threadpool(
            request.app.state.auth.audit.write,
            "overview.view",
            "success",
            user.user_id,
            client_ip(request),
            detail,
        )
    data, summary = await _assessed(request, result)
    return OverviewOut(**data, source_summary=SourceSummaryOut(**asdict(summary)))


async def _assessed(request: Request, result: Any) -> tuple[dict[str, Any], Any]:
    """The Overview as sent, each source with its condition, and the "N of M healthy" summary."""
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
    volume = {v["source_id"]: v for v in data["volume"]}
    conditions, summary = assess([_input(s, volume.get(s["source_id"])) for s in data["sources"]])
    for s in data["sources"]:
        s["condition"] = conditions[s["source_id"]]
        s.pop("reading_issue", None)
    return data, summary


class HealthCountOut(BaseModel):
    total: int
    not_healthy: int


@router.get("/health/count")
async def health_count(request: Request, user: CurrentUser) -> HealthCountOut:
    """How many of the viewer's sources need attention, for the rail's Health dot (ADR-0052
    section 3.2). The same assessment as the Health page, on the viewer's own sources; a
    source paused on purpose is not counted. Numbers only: it names no source, so like
    `/alerts/count` it writes no audit row (owner, 2026-11-11: the audit log records access,
    not page loads). It never fills the cache `/overview` reads, so the next Overview read
    is still computed and recorded."""
    svc: OverviewService = request.app.state.overview
    result = await run_in_threadpool(svc.for_count, user)
    data, summary = await _assessed(request, result)
    wrong = needing_attention(s["condition"] for s in data["sources"])
    return HealthCountOut(total=summary.total, not_healthy=wrong)


def _input(s: dict[str, Any], v: dict[str, Any] | None) -> SourceInput:
    gaps = (v or {}).get("gaps") or []
    return SourceInput(
        source_id=s["source_id"],
        state=s["state"],
        last_event_at=s.get("last_event_at"),
        total_24h=int((v or {}).get("total") or 0),
        gaps=len(gaps),
        ongoing_gap=any(g.get("ongoing") for g in gaps),
        quiet_since=s.get("quiet_since"),
        gap_alert=s.get("gap_alert"),
        quiet_expected=bool(s.get("quiet_expected")),
        reading_issue=bool(s.get("reading_issue")),
        records_skipped=int(s.get("records_skipped") or 0),
        files_waiting=int(s.get("files_waiting") or 0),
    )


def _instant(iso: str) -> datetime:
    when = datetime.fromisoformat(iso)
    return when if when.tzinfo else when.replace(tzinfo=UTC)
