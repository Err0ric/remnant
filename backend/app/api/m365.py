"""/api/m365/overview: the Microsoft 365 area's Overview numbers and tab lists for one page
window (ADR-0038 section 5). Router only; `app.search.m365` reads the caller's own view.
Audited as `m365.overview` with the sources read."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.access import CurrentUser, client_ip
from app.api.cache import STALE_MAX_S, PageCache, scope_key
from app.auth.service import AuthService
from app.auth.users import User
from app.engine import signin_classes
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
) -> Response:
    """KPIs, the counts row, the outcome per hour or day, the tops, and each tab's list as
    a Search query template (`{from}` and `{to}`). `has_source` is false when the caller
    reads no Microsoft 365 source."""
    app = request.app
    allowed = await run_in_threadpool(permitted_sources, app.state.meta, user)
    cache: PageCache = app.state.page_cache
    # A hit reads nothing else and sends the stored bytes; changes empty the cache, so
    # settings and sources need not be in the key (owner, 2026-11-01).
    key = ("m365", scope_key(allowed), window, tz)
    default = window == "7d"  # refreshed in the background, served at once (D147)

    def compute(_viewer: User, scope: list[str] | None) -> tuple[bytes, list[str]]:
        places = networks.load(app.state.meta)
        srcs = [(s.source_id, s.kind or "file", s.template_id) for s in app.state.sources.list()]
        out = overview(
            app.state.engine, scope, srcs, places, window, app.state.ai_watch.now(),
            app.state.m365_rollup, tz,
        )  # fmt: skip
        data = to_dict(out)
        data["updated_at"] = datetime.now(UTC)  # "updated N s ago" on the page (D147)
        return bytes(JSONResponse(jsonable_encoder(data)).body), list(out.read)

    hit = cache.peek(key, STALE_MAX_S) if default else cache.get(key)
    if hit is not None:
        body, read = hit[0] if default else hit
        await run_in_threadpool(
            app.state.auth.audit.write, "m365.overview", "success", user.user_id,
            client_ip(request), {"window": window, "cached": True, "sources_in_scope": read},
        )  # fmt: skip
        if default:  # seen now: refreshed while viewed, again after a lapse (D147)
            app.state.refresher.watch(key, user.user_id, scope_key(allowed), compute)
        return Response(body, media_type="application/json")

    body, read = await run_in_threadpool(compute, user, allowed)
    auth: AuthService = app.state.auth
    await run_in_threadpool(
        auth.audit.write,
        "m365.overview",
        "success",
        user.user_id,
        client_ip(request),
        {"window": window, "sources_in_scope": read},
    )
    cache.put(key, (body, read))
    if default:
        app.state.refresher.watch(key, user.user_id, scope_key(allowed), compute)
    return Response(body, media_type="application/json")


class SignInCode(BaseModel):
    code: int
    cls: str
    label: str
    shipped: str | None  # the class in the shipped file; None if added on this install


class SignInClassesOut(BaseModel):
    """How failed Entra sign-ins are counted on this install (D158)."""

    classes: list[str]
    blocked_code: int
    codes: list[SignInCode]
    adjusted: list[SignInCode]  # codes this install moved from their shipped class


@router.get("/m365/signin-classes")
async def m365_signin_classes(user: CurrentUser) -> SignInClassesOut:
    """The classes in force: the shipped codes with this install's `m365.signin_classes`
    on top. Codes in no class are "other"."""
    codes = [
        SignInCode(code=c.code, cls=c.cls, label=c.label, shipped=c.shipped)
        for c in signin_classes.ACTIVE.codes()
    ]
    return SignInClassesOut(
        classes=list(signin_classes.CLASSES),
        blocked_code=signin_classes.BLOCKED_CODE,
        codes=codes,
        adjusted=[c for c in codes if c.cls != c.shipped],
    )
