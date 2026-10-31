"""The built-in refused-credentials detection's settings (ADR-0040). Admin only; changes
are audited `detect.refusals` with the before and after."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.api.access import AdminUser, CurrentUser, client_ip
from app.auth.service import AuthService
from app.search import refusals

router = APIRouter(tags=["detection rules"])


class RefusalSettingsOut(BaseModel):
    enabled: bool
    threshold: int
    window_minutes: int = 10


class RefusalSettingsIn(BaseModel):
    enabled: bool
    threshold: int = Field(ge=3, le=1000)


@router.get("/rules/builtin/refusals")
async def get_refusals(request: Request, _: CurrentUser) -> RefusalSettingsOut:
    s = await run_in_threadpool(refusals.load, request.app.state.meta)
    return RefusalSettingsOut(enabled=s.enabled, threshold=s.threshold)


@router.put("/rules/builtin/refusals")
async def put_refusals(
    body: RefusalSettingsIn, request: Request, user: AdminUser
) -> RefusalSettingsOut:
    meta = request.app.state.meta
    before = await run_in_threadpool(refusals.load, meta)
    after = await run_in_threadpool(refusals.save, meta, body.enabled, body.threshold, user.user_id)
    auth: AuthService = request.app.state.auth
    await run_in_threadpool(
        auth.audit.write,
        "detect.refusals",
        "success",
        user.user_id,
        client_ip(request),
        {
            "from": {"enabled": before.enabled, "threshold": before.threshold},
            "to": {"enabled": after.enabled, "threshold": after.threshold},
        },
    )
    return RefusalSettingsOut(enabled=after.enabled, threshold=after.threshold)
