"""/api/m365/overview: the Microsoft 365 area's Overview numbers and tab lists for one page
window (ADR-0038 section 5). Router only; `app.search.m365` reads the caller's own view.
Audited as `m365.overview` with the sources read."""

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from starlette.concurrency import run_in_threadpool

from app.api.access import CurrentUser, client_ip
from app.api.cache import PageCache, scope_key
from app.auth.service import AuthService
from app.engine.views import permitted_sources
from app.enrich import networks
from app.search.dashboard import Window
from app.search.m365 import overview, to_dict

router = APIRouter(tags=["microsoft 365"])


@router.get("/m365/overview")
async def m365_overview(
    request: Request,
    user: CurrentUser,
    window: Window = "7d",
    tz: Annotated[str, Query(max_length=64)] = "UTC",
) -> dict[str, Any]:
    """KPIs, the counts row, the outcome per hour or day, the tops, and each tab's list as
    a Search query template (`{from}` and `{to}`). `has_source` is false when the caller
    reads no Microsoft 365 source."""
    meta = request.app.state.meta
    allowed = await run_in_threadpool(permitted_sources, meta, user)
    places = await run_in_threadpool(networks.load, meta)
    srcs = [
        (s.source_id, s.kind or "file", s.template_id) for s in request.app.state.sources.list()
    ]
    cache: PageCache = request.app.state.page_cache
    key = ("m365", scope_key(allowed), window, tz, places, tuple(srcs))
    hit = cache.get(key)
    if hit is not None:
        data, read = hit
        await run_in_threadpool(
            request.app.state.auth.audit.write, "m365.overview", "success", user.user_id,
            client_ip(request), {"window": window, "cached": True, "sources_in_scope": read},
        )  # fmt: skip
        return dict(data)
    now = request.app.state.ai_watch.now()
    out = await run_in_threadpool(
        overview,
        request.app.state.engine,
        allowed,
        srcs,
        places,
        window,
        now,
        request.app.state.m365_rollup,
        tz,
    )
    auth: AuthService = request.app.state.auth
    await run_in_threadpool(
        auth.audit.write,
        "m365.overview",
        "success",
        user.user_id,
        client_ip(request),
        {"window": window, "sources_in_scope": out.read},
    )
    data = to_dict(out)
    cache.put(key, (data, out.read))
    return data
