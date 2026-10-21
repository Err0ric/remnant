"""/api/alert-targets: where alerts go (ADR-0007). Router only.

Admins create, change, delete, and test targets. Analysts may list them (name, kind, host,
health) to choose targets for their schedules. Secrets are never returned; a webhook's
signing key is returned once, when it is created.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.alerts.render import Alert
from app.alerts.send import SendError
from app.alerts.targets import EmailSettings, Name, Target, TargetKind, TargetStore
from app.api.access import AdminUser, client_ip, require_role
from app.auth.users import User
from app.core.branding import PRODUCT_NAME

router = APIRouter(tags=["alerts"])
Picker = Annotated[User, Depends(require_role("admin", "analyst"))]


class TargetIn(BaseModel):
    name: Name
    kind: TargetKind
    url: str | None = Field(default=None, max_length=2_048)  # slack, teams, webhook
    email: EmailSettings | None = None
    password: str | None = Field(default=None, max_length=500)  # SMTP, write-only


class TargetUpdate(BaseModel):
    name: Name | None = None
    url: str | None = Field(default=None, max_length=2_048)  # replaces the stored URL
    email: EmailSettings | None = None
    password: str | None = Field(default=None, max_length=500)


class TargetOut(BaseModel):
    target_id: str
    name: str
    kind: str
    display: str
    recipients: list[str]
    failing: bool
    consecutive_failures: int
    last_error: str | None
    last_sent_at: str | None


class TargetCreated(TargetOut):
    # Webhook only: for the receiver to check X-Signature-256. Shown this once.
    signing_key: str | None


class TestResult(BaseModel):
    ok: bool
    detail: str


def _store(request: Request) -> TargetStore:
    store: TargetStore = request.app.state.alert_targets
    return store


def _out(t: Target) -> TargetOut:
    return TargetOut(
        target_id=t.target_id,
        name=t.name,
        kind=t.kind,
        display=t.display,
        recipients=list(t.settings.get("to_addrs", [])),
        failing=t.failing,
        consecutive_failures=t.consecutive_failures,
        last_error=t.last_error,
        last_sent_at=t.last_sent_at,
    )


def _audit(request: Request, action: str, user: User, detail: dict[str, object]) -> None:
    request.app.state.auth.audit.write(action, "success", user.user_id, client_ip(request), detail)


@router.get("/alert-targets")
async def list_targets(request: Request, _: Picker) -> list[TargetOut]:
    return [_out(t) for t in await run_in_threadpool(_store(request).all)]


@router.post("/alert-targets", status_code=status.HTTP_201_CREATED)
async def create_target(body: TargetIn, request: Request, user: AdminUser) -> TargetCreated:
    target, key = await run_in_threadpool(
        _store(request).create,
        body.name,
        body.kind,
        body.url,
        body.email,
        body.password,
        user.user_id,
    )
    await run_in_threadpool(
        _audit,
        request,
        "alert_target.create",
        user,
        {"target_id": target.target_id, "kind": target.kind, "host": target.display},
    )
    return TargetCreated(**_out(target).model_dump(), signing_key=key)


@router.patch("/alert-targets/{target_id}")
async def update_target(
    target_id: str, body: TargetUpdate, request: Request, user: AdminUser
) -> TargetOut:
    target = await run_in_threadpool(
        _store(request).update, target_id, body.name, body.url, body.email, body.password
    )
    changed = [k for k, v in body.model_dump().items() if v is not None]
    await run_in_threadpool(
        _audit, request, "alert_target.update", user, {"target_id": target_id, "changed": changed}
    )
    return _out(target)


@router.delete("/alert-targets/{target_id}")
async def delete_target(target_id: str, request: Request, user: AdminUser) -> Response:
    await run_in_threadpool(_store(request).delete, target_id)
    await run_in_threadpool(_audit, request, "alert_target.delete", user, {"target_id": target_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/alert-targets/{target_id}/test")
async def test_target(target_id: str, request: Request, user: AdminUser) -> TestResult:
    alert = Alert(
        kind="test",
        title="Test alert",
        detail=f"Sent by {user.username} to check this destination.",
        count=None,
        reason=None,
        range_start=None,
        range_end=None,
        link=request.app.state.public_url,
        product=PRODUCT_NAME,
    )
    outcome: Literal["success", "failure"] = "success"
    try:
        await run_in_threadpool(_store(request).send, target_id, alert)
        result = TestResult(ok=True, detail="Delivered")
    except SendError as exc:
        outcome, result = "failure", TestResult(ok=False, detail=str(exc))
    request.app.state.auth.audit.write(
        "alert_target.test", outcome, user.user_id, client_ip(request), {"target_id": target_id}
    )
    return result
