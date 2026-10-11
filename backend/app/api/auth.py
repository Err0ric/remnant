"""/api/auth/* and /api/setup: sign-in state, first-run setup, login, logout. Router only."""

from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.api.access import (
    SESSION_COOKIE,
    CurrentUser,
    client_ip,
    presented_token,
    resolve_session,
)
from app.auth.passwords import MAX_LENGTH, MIN_LENGTH
from app.auth.service import AuthService, Mode
from app.auth.users import User

router = APIRouter(tags=["auth"])

USERNAME = r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,63}$"


class UserOut(BaseModel):
    user_id: str
    username: str
    role: str


class AuthState(BaseModel):
    mode: Mode
    user: UserOut | None
    csrf_token: str | None


class SetupRequest(BaseModel):
    token: str = Field(min_length=1, max_length=200)
    username: str = Field(pattern=USERNAME)
    password: str = Field(min_length=MIN_LENGTH, max_length=MAX_LENGTH)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=MAX_LENGTH)
    client: Literal["browser", "cli"] = "browser"
    label: str | None = Field(default=None, max_length=100)  # CLI token name, e.g. host


class SignedIn(BaseModel):
    user: UserOut
    csrf_token: str | None = None
    token: str | None = None  # CLI only; browsers get an HttpOnly cookie instead


def _out(user: User) -> UserOut:
    return UserOut(user_id=user.user_id, username=user.username, role=user.role)


def _auth(request: Request) -> AuthService:
    auth: AuthService = request.app.state.auth
    return auth


def _set_cookie(response: Response, auth: AuthService, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(auth.session_ttl().total_seconds()),
        httponly=True,
        secure=not auth.loopback,
        samesite="strict",
        path="/",
    )


@router.get("/auth/state")
async def state(request: Request) -> AuthState:
    auth = _auth(request)
    mode = await run_in_threadpool(auth.mode)
    if mode != "login":
        return AuthState(mode=mode, user=None, csrf_token=None)
    resolved = await run_in_threadpool(resolve_session, request)
    if resolved is None:
        return AuthState(mode=mode, user=None, csrf_token=None)
    info, user, _ = resolved
    return AuthState(mode=mode, user=_out(user), csrf_token=info.csrf_token)


@router.post("/setup", status_code=status.HTTP_201_CREATED, response_model_exclude_none=True)
async def setup(body: SetupRequest, request: Request, response: Response) -> SignedIn:
    auth = _auth(request)
    user, token, csrf = await run_in_threadpool(
        auth.complete_setup, body.token, body.username, body.password, client_ip(request)
    )
    _set_cookie(response, auth, token)
    return SignedIn(user=_out(user), csrf_token=csrf)


@router.post("/auth/login", response_model_exclude_none=True)
async def login(body: LoginRequest, request: Request, response: Response) -> SignedIn:
    auth = _auth(request)
    user, token, csrf = await run_in_threadpool(
        auth.login, body.username, body.password, body.client, client_ip(request), body.label
    )
    if body.client == "cli":
        return SignedIn(user=_out(user), token=token)
    _set_cookie(response, auth, token)
    return SignedIn(user=_out(user), csrf_token=csrf)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, user: CurrentUser) -> Response:
    auth = _auth(request)
    token, _ = presented_token(request)
    if token:
        await run_in_threadpool(auth.logout, token, user, client_ip(request))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        SESSION_COOKIE, path="/", secure=not auth.loopback, httponly=True, samesite="strict"
    )
    return response
