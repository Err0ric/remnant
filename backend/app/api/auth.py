"""/api/auth/* and /api/setup: sign-in state, first-run setup, login, logout, and optional
single sign-on (ADR-0013). Router only."""

from typing import Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import RedirectResponse
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
from app.core.errors import SsoRefusedError

router = APIRouter(tags=["auth"])

USERNAME = r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,63}$"


class UserOut(BaseModel):
    user_id: str
    username: str
    role: str


class SsoState(BaseModel):
    label: str  # button text, e.g. "Microsoft"
    passwords_admins_only: bool


class AuthState(BaseModel):
    mode: Mode
    user: UserOut | None
    csrf_token: str | None
    sso: SsoState | None = None


class SsoStart(BaseModel):
    # Finishing an invite or reset link with SSO binds the identity to that account.
    link_token: str | None = Field(default=None, min_length=1, max_length=200)


class SsoRedirect(BaseModel):
    url: str


SSO_FLOW_COOKIE = "sso_flow"
SSO_CALLBACK = "/api/auth/sso/callback"


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


def _sso_state(auth: AuthService) -> SsoState | None:
    if auth.sso is None:
        return None
    return SsoState(label=auth.sso.label, passwords_admins_only=auth.passwords_admins_only)


@router.get("/auth/state")
async def state(request: Request) -> AuthState:
    auth = _auth(request)
    mode = await run_in_threadpool(auth.mode)
    if mode != "login":
        return AuthState(mode=mode, user=None, csrf_token=None)
    sso = _sso_state(auth)
    resolved = await run_in_threadpool(resolve_session, request)
    if resolved is None:
        return AuthState(mode=mode, user=None, csrf_token=None, sso=sso)
    info, user, _ = resolved
    return AuthState(mode=mode, user=_out(user), csrf_token=info.csrf_token, sso=sso)


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


@router.post("/auth/sso/start")
async def sso_start(body: SsoStart, request: Request, response: Response) -> SsoRedirect:
    """Where to send the browser to sign in; binds the flow to this browser with a cookie."""
    auth = _auth(request)
    if auth.sso is None or await run_in_threadpool(auth.mode) != "login":
        raise SsoRefusedError("off", "single sign-on is not turned on")
    url, cookie = await run_in_threadpool(auth.sso.begin, body.link_token, client_ip(request))
    response.set_cookie(
        SSO_FLOW_COOKIE,
        cookie,
        max_age=600,
        httponly=True,
        secure=not auth.loopback,
        samesite="lax",  # must survive the top-level redirect back from the provider
        path=SSO_CALLBACK,
    )
    return SsoRedirect(url=url)


def _back_to_sign_in(code: str) -> RedirectResponse:
    response = RedirectResponse(f"/login?{urlencode({'sso': code})}", status_code=303)
    response.delete_cookie(SSO_FLOW_COOKIE, path=SSO_CALLBACK)
    return response


@router.get("/auth/sso/callback", include_in_schema=False)
async def sso_callback(request: Request) -> Response:
    """The provider's redirect. Never reflects provider text; errors become fixed codes."""
    auth = _auth(request)
    ip = client_ip(request)
    if auth.sso is None:
        return _back_to_sign_in("off")
    params = request.query_params
    state_, code = params.get("state"), params.get("code")
    if params.get("error") or not state_ or not code:
        reason = str(params.get("error") or "missing code or state")[:100]
        await run_in_threadpool(auth.sso.refuse, "denied", f"provider: {reason}", ip)
        if state_:  # use the flow up so it cannot be replayed
            try:
                auth.sso.oidc.take_flow(state_, request.cookies.get(SSO_FLOW_COOKIE))
            except SsoRefusedError:
                pass
        return _back_to_sign_in("denied")
    try:
        user = await run_in_threadpool(
            auth.sso.complete, state_, code, request.cookies.get(SSO_FLOW_COOKIE), ip
        )
    except SsoRefusedError as exc:
        return _back_to_sign_in(exc.code)
    token, _ = await run_in_threadpool(auth.start_sso_session, user, ip)
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(SSO_FLOW_COOKIE, path=SSO_CALLBACK)
    _set_cookie(response, auth, token)
    return response
