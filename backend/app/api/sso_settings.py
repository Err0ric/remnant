"""Settings > Single sign-on (F64): what the server's OIDC setup is, read only. The setup
stays server-side (ADR-0013: the secret lives in the environment), so this page shows the
status, the issuer and client id in use (never the secret), the exact redirect URI to give
the identity provider, the variables to set, a check that reaches the provider, and who is
bound to an identity. Admin only; the check is audited `sso.test`."""

from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.access import AdminUser, client_ip
from app.auth.service import AuthService
from app.core.errors import ConfigError, SsoRefusedError

router = APIRouter(tags=["single sign-on"])

ENV = [
    ("APP__SSO__ENABLED", "true to turn single sign-on on"),
    ("APP__SSO__ISSUER", "https://login.microsoftonline.com/<tenant id>/v2.0 (one tenant)"),
    ("APP__SSO__CLIENT_ID", "the app registration's Application (client) ID"),
    ("APP__SSO__CLIENT_SECRET", "the client secret; environment only, never in a file"),
    ("APP__SSO__REQUIRED_GROUPS", "optional: group object ids, comma separated"),
    ("APP__SSO__LABEL", "the button text, default Microsoft"),
    ("APP__SSO__PASSWORD_LOGIN", "admins (default, break-glass) or everyone"),
    ("APP__SERVER__PUBLIC_URL", "the address people open; the redirect URI is built from it"),
]


class SsoBound(BaseModel):
    user_id: str
    username: str
    role: str
    disabled: bool
    last_login_at: str | None


class SsoSettings(BaseModel):
    status: Literal["off", "on", "misconfigured"]
    problem: str | None
    issuer: str | None
    client_id: str | None
    label: str
    required_groups: list[str]
    password_login: str
    redirect_uri: str | None
    env: list[dict[str, str]]
    bound: list[SsoBound]


class SsoTest(BaseModel):
    ok: bool
    message: str


def _redirect(request: Request) -> tuple[str | None, str | None]:
    from app.main import sso_redirect_uri

    try:
        return sso_redirect_uri(request.app.state.config), None
    except ConfigError as exc:
        return None, str(exc)


def _bound(request: Request) -> list[SsoBound]:
    with request.app.state.meta.connect() as con:
        rows = con.execute(
            "SELECT user_id, username, role, disabled, last_login_at FROM users"
            " WHERE sso_subject IS NOT NULL ORDER BY username"
        ).fetchall()
    return [
        SsoBound(
            user_id=str(r["user_id"]),
            username=str(r["username"]),
            role=str(r["role"]),
            disabled=bool(r["disabled"]),
            last_login_at=r["last_login_at"],
        )
        for r in rows
    ]


@router.get("/settings/sso")
async def sso_settings(request: Request, _: AdminUser) -> SsoSettings:
    cfg = request.app.state.config.sso
    auth: AuthService = request.app.state.auth
    redirect, problem = _redirect(request)
    status: Literal["off", "on", "misconfigured"] = "off"
    if cfg.enabled:
        status = "on" if auth.sso is not None and problem is None else "misconfigured"
        if auth.sso is None and problem is None:
            problem = "Single sign-on is turned on but did not start; see the server log"
    return SsoSettings(
        status=status,
        problem=problem if cfg.enabled else None,
        issuer=cfg.issuer,
        client_id=cfg.client_id,
        label=cfg.label,
        required_groups=list(cfg.required_groups),
        password_login=cfg.password_login,
        redirect_uri=redirect,
        env=[{"name": n, "value": v} for n, v in ENV],
        bound=await run_in_threadpool(_bound, request),
    )


@router.post("/settings/sso/test")
async def sso_test(request: Request, user: AdminUser) -> SsoTest:
    """Reach the provider's discovery document and check its issuer, as a sign-in would.
    It signs nobody in."""
    auth: AuthService = request.app.state.auth
    if auth.sso is None:
        result = SsoTest(ok=False, message="Single sign-on is off on this server")
    else:
        try:
            await run_in_threadpool(auth.sso.oidc.check)
            result = SsoTest(
                ok=True,
                message="Reached the provider; its issuer matches. Sign in with "
                f"{auth.sso.label} from a private window to finish the check.",
            )
        except SsoRefusedError as exc:
            result = SsoTest(ok=False, message=f"Could not use the provider: {exc.reason}")
    detail: dict[str, Any] = {"ok": result.ok}
    await run_in_threadpool(
        auth.audit.write,
        "sso.test",
        "success" if result.ok else "failure",
        user.user_id,
        client_ip(request),
        detail,
    )
    return result
