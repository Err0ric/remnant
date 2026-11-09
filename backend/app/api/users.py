"""/api/users (admin), /api/account/password (link holders), and the setting that grants
Auditors SQL (D220). Router only."""

from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.api.access import AdminUser, CurrentUser, client_ip
from app.api.auth import USERNAME
from app.auth import auditor_sql
from app.auth.admin import UserAdmin, UserRecord
from app.auth.passwords import MAX_LENGTH, MIN_LENGTH
from app.auth.service import AuthService

router = APIRouter(tags=["users"])

RoleName = Literal["admin", "analyst", "auditor"]


class UserOut(BaseModel):
    user_id: str
    username: str
    role: RoleName
    disabled: bool
    pending: bool
    created_at: str
    last_login_at: str | None
    sso: bool = False


class InviteRequest(BaseModel):
    username: str = Field(pattern=USERNAME)
    role: RoleName


class InviteResponse(BaseModel):
    user: UserOut
    invite_token: str  # shown once; the UI builds /account#<token>


class UserUpdate(BaseModel):
    role: RoleName | None = None
    disabled: bool | None = None


class ResetResponse(BaseModel):
    reset_token: str


class PasswordFromLink(BaseModel):
    token: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=MIN_LENGTH, max_length=MAX_LENGTH)


def _admin(request: Request) -> UserAdmin:
    auth: AuthService = request.app.state.auth
    return auth.admin


def _out(r: UserRecord) -> UserOut:
    return UserOut(
        user_id=r.user_id,
        username=r.username,
        role=r.role,
        disabled=r.disabled,
        pending=r.pending,
        created_at=r.created_at,
        last_login_at=r.last_login_at,
        sso=r.sso,
    )


@router.get("/users")
async def list_users(request: Request, _: AdminUser) -> list[UserOut]:
    return [_out(r) for r in await run_in_threadpool(_admin(request).all)]


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def invite_user(body: InviteRequest, request: Request, actor: AdminUser) -> InviteResponse:
    admin = _admin(request)
    user, token = await run_in_threadpool(
        admin.invite, body.username, body.role, actor, client_ip(request)
    )
    record = next(r for r in await run_in_threadpool(admin.all) if r.user_id == user.user_id)
    return InviteResponse(user=_out(record), invite_token=token)


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str, body: UserUpdate, request: Request, actor: AdminUser
) -> UserOut:
    record = await run_in_threadpool(
        lambda: _admin(request).update(
            user_id, actor, client_ip(request), role=body.role, disabled=body.disabled
        )
    )
    return _out(record)


@router.post("/users/{user_id}/reset")
async def reset_user(user_id: str, request: Request, actor: AdminUser) -> ResetResponse:
    token = await run_in_threadpool(_admin(request).issue_reset, user_id, actor, client_ip(request))
    return ResetResponse(reset_token=token)


@router.post("/account/password", status_code=status.HTTP_204_NO_CONTENT)
async def set_password_from_link(body: PasswordFromLink, request: Request) -> Response:
    await run_in_threadpool(_admin(request).redeem, body.token, body.password, client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class AuditorSql(BaseModel):
    enabled: bool


@router.get("/settings/auditor-sql")
async def get_auditor_sql(request: Request, _: CurrentUser) -> AuditorSql:
    """Whether Auditors may run SQL (D220). Anyone signed in may read it, for the UI."""
    return AuditorSql(enabled=await run_in_threadpool(auditor_sql.enabled, request.app.state.meta))


@router.put("/settings/auditor-sql")
async def put_auditor_sql(body: AuditorSql, request: Request, user: AdminUser) -> AuditorSql:
    """Grant or take back SQL for Auditors (off by default). Audited `settings.auditor_sql`."""
    meta = request.app.state.meta
    before = await run_in_threadpool(auditor_sql.enabled, meta)
    after = await run_in_threadpool(auditor_sql.save, meta, body.enabled, user.user_id)
    auth: AuthService = request.app.state.auth
    await run_in_threadpool(
        auth.audit.write,
        "settings.auditor_sql",
        "success",
        user.user_id,
        client_ip(request),
        {"from": before, "to": after},
    )
    return AuditorSql(enabled=after)
