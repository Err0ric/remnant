"""/api/dashboard/sections: Identity, Attacks and access, and Detections for one page
window (ADR-0038 edit 10). Router only; the numbers come from `app.search.dashboard` on the
caller's own view. Audited as `dashboard.sections` with the sources read."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.access import CurrentUser, client_ip
from app.api.cache import PageCache, scope_key
from app.auth.service import AuthService
from app.engine.views import permitted_sources
from app.enrich import networks
from app.enrich.geoip import GeoInfo, GeoIP
from app.search.dashboard import PARTS, Window, sections
from app.search.entities import to_json

router = APIRouter(tags=["dashboards"])


class KpiOut(BaseModel):
    value: int
    before: int | None
    extra: int | None
    # Search query templates with `{from}` and `{to}` for the window (ADR-0039).
    drill: str | None = None
    drill_before: str | None = None
    extra_drill: str | None = None


class SeriesOut(BaseModel):
    label: str
    counts: list[int]
    level: str | None
    drill: str | None = None


class RowOut(BaseModel):
    label: str
    count: int
    kind: str
    detail: str
    last: str | None
    drill: str | None = None


class HistoryOut(BaseModel):
    compared: bool
    since: datetime | None


class TrendOut(BaseModel):
    points: list[datetime]
    counts: list[int]
    before: list[int]


class IdentityOut(BaseModel):
    failed: KpiOut
    outside: KpiOut | None
    inbox_rules: KpiOut
    consents: KpiOut
    role_grants: KpiOut
    ca_edits: KpiOut
    sign_ins: int
    failed_trend: TrendOut
    top_failing: list[RowOut]
    history: HistoryOut


class AttacksOut(BaseModel):
    failures: KpiOut
    addresses: KpiOut
    countries: KpiOut | None
    vpn_outside: KpiOut | None
    has_vpn: bool
    by_host: list[SeriesOut]
    top_sources: list[RowOut]
    history: HistoryOut


class DetectionsOut(BaseModel):
    matches: KpiOut
    rules_matched: KpiOut
    hosts: KpiOut
    users: KpiOut
    by_rule: list[SeriesOut]
    involved: list[RowOut]
    history: HistoryOut


class SectionsOut(BaseModel):
    window: Literal["24h", "7d", "30d"]
    start: datetime
    end: datetime
    before: datetime
    buckets: list[datetime]
    approved_set: bool
    has_public: bool
    geoip_date: str | None
    identity: IdentityOut | None
    attacks: AttacksOut | None
    detections: DetectionsOut | None


Part = Literal["identity", "attacks", "detections"]


@router.get("/dashboard/sections")
async def dashboard_sections(
    request: Request,
    user: CurrentUser,
    window: Window = "7d",
    part: Part | None = None,
    tz: Annotated[str, Query(max_length=64)] = "UTC",
) -> SectionsOut:
    """The Dashboard's default sections for the caller, against the window before. A
    section is null when the caller has no source for it, or when `part` asks for another
    one (the page loads each section on its own, so a slow one holds up only itself).
    Days are the viewer's (`tz`, an IANA name; UTC otherwise).
    Numbers are kept for 60 s per caller's sources, window, and part (`app.api.cache`)."""
    meta = request.app.state.meta
    allowed = await run_in_threadpool(permitted_sources, meta, user)
    places = await run_in_threadpool(networks.load, meta)
    srcs = [
        (s.source_id, s.kind or "file", s.template_id) for s in request.app.state.sources.list()
    ]
    cache: PageCache = request.app.state.page_cache
    # A settings or source change is a new key: only the clock makes an answer old.
    key = ("sections", scope_key(allowed), window, part, tz, places, tuple(srcs))
    hit = cache.get(key)
    if hit is not None:
        data, read = hit
        await run_in_threadpool(
            request.app.state.auth.audit.write, "dashboard.sections", "success", user.user_id,
            client_ip(request),
            {"window": window, "part": part, "cached": True, "sources_in_scope": read},
        )  # fmt: skip
        return SectionsOut(**data)
    geoip: GeoIP = request.app.state.geoip

    def geo(ips: list[str]) -> dict[str, GeoInfo]:
        # Every address the card counts (at most MAX_IPS), not the page lookup cap.
        return geoip.enrich(ips, limit=len(ips))

    now = request.app.state.ai_watch.now()
    out = await run_in_threadpool(
        sections,
        request.app.state.engine,
        meta,
        allowed,
        srcs,
        places,
        geo,
        window,
        now,
        request.app.state.m365_rollup,
        PARTS if part is None else (part,),
        tz,
    )
    auth: AuthService = request.app.state.auth
    await run_in_threadpool(
        auth.audit.write,
        "dashboard.sections",
        "success",
        user.user_id,
        client_ip(request),
        {"window": window, "part": part, "sources_in_scope": out.read},
    )
    data = to_json(out)
    data["geoip_date"] = request.app.state.feeds.state("geoip_country").installed_at
    cache.put(key, (data, data.pop("read", None)))
    return SectionsOut(**data)
