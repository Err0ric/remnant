"""Who is calling, and may they? (ADR-0001, CLAUDE.md rules 13 and 14)

Modes: `open` (loopback, no accounts yet: implicit local admin), `setup` (network
bind, no accounts: everything but setup is closed), `login` (accounts exist:
a session cookie or a CLI bearer token is required on every protected route).
Cookie-authenticated writes also need the session's CSRF token in X-CSRF-Token.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated

import anyio
from fastapi import Depends, Request

from app.auth.service import AuthService
from app.auth.sessions import SessionInfo, csrf_matches
from app.auth.users import LOCAL_USER, Role, User
from app.core.errors import (
    AuthRequiredError,
    CsrfError,
    ForbiddenError,
    InteractiveRequiredError,
    SetupRequiredError,
)

SESSION_COOKIE = "session"
CSRF_HEADER = "X-CSRF-Token"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def presented_token(request: Request) -> tuple[str | None, bool]:
    """The session token and whether it came from a cookie (as opposed to a bearer header)."""
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and value:
        return value.strip(), False
    return request.cookies.get(SESSION_COOKIE), True


def resolve_session(request: Request) -> tuple[SessionInfo, User, bool] | None:
    """The caller's live session, or None. Browser sessions are accepted only from the
    cookie and CLI tokens only from the Authorization header, so a stolen CLI token
    cannot pose as a browser session (and gain its CSRF token) or the reverse."""
    auth: AuthService = request.app.state.auth
    token, from_cookie = presented_token(request)
    info = auth.sessions.resolve(token, auth.clock()) if token else None
    if info is None or (info.kind == "browser") != from_cookie:
        return None
    user = auth.users.get(info.user_id)
    if user is None or user.disabled:
        return None
    return info, user, from_cookie


# Sign-in checks run on their own few threads, never the shared request pool (owner,
# 2026-11-03: at the UTC day rollover every pool thread was waiting on a query slot, and a
# request that only needed its session checked waited 13 s; D193). The work is a SQLite
# read or two, so a handful of threads is plenty.
AUTH_THREADS = 8
_auth_limiter: anyio.CapacityLimiter | None = None


def _limiter() -> anyio.CapacityLimiter:
    global _auth_limiter
    if _auth_limiter is None:
        _auth_limiter = anyio.CapacityLimiter(AUTH_THREADS)
    return _auth_limiter


async def _off_pool(fn: Callable[[Request], User], request: Request) -> User:
    return await anyio.to_thread.run_sync(fn, request, limiter=_limiter())


def _current_user(request: Request) -> User:
    auth: AuthService = request.app.state.auth
    mode = auth.mode()
    if mode == "open":
        request.state.user = LOCAL_USER
        request.state.via = "open"
        return LOCAL_USER
    if mode == "setup":
        raise SetupRequiredError("Finish setup first: open the one-time link from the server log")

    resolved = resolve_session(request)
    if resolved is None:
        token, from_cookie = presented_token(request)
        if token and not from_cookie:
            # A bearer token that is not a live API token (ADR-0040): never the token.
            request.app.state.server_events.refused(
                "api_token", client_ip(request), token_prefix=token[:8]
            )
        raise AuthRequiredError("Sign in to continue")
    info, user, from_cookie = resolved
    if from_cookie and request.method not in _SAFE_METHODS:
        if not csrf_matches(info.csrf_token, request.headers.get(CSRF_HEADER)):
            auth.audit.write(
                "auth.csrf_failed",
                "denied",
                user.user_id,
                client_ip(request),
                {"method": request.method, "path": request.url.path},
            )
            raise CsrfError("Missing or wrong CSRF token")
    request.state.user = user
    request.state.via = "cookie" if from_cookie else "bearer"
    request.state.token_id = info.token_id
    return user


async def current_user(request: Request) -> User:
    """Who is calling (see the module docstring), checked on the sign-in threads."""
    return await _off_pool(_current_user, request)


def _interactive_user(request: Request) -> User:
    user = _current_user(request)
    if getattr(request.state, "via", None) == "bearer":
        raise InteractiveRequiredError("Sign in to the web interface to manage tokens")
    return user


async def interactive_user(request: Request) -> User:
    """A person at a browser, not an API token: a stolen token cannot mint new tokens."""
    return await _off_pool(_interactive_user, request)


def require_role(*roles: Role) -> Callable[[Request], Awaitable[User]]:
    def _check(request: Request) -> User:
        user = _current_user(request)
        if user.role not in roles:
            auth: AuthService = request.app.state.auth
            auth.audit.write(
                "access.denied",
                "denied",
                user.user_id,
                client_ip(request),
                {"method": request.method, "path": request.url.path, "role": user.role},
            )
            raise ForbiddenError("Your role does not allow this action")
        return user

    async def check(request: Request) -> User:
        return await _off_pool(_check, request)

    return check


def now(request: Request) -> datetime:
    """The app's "now" for read endpoints (`app.state.clock`), so a test can pin it next to
    its event dates and give the same result on any day."""
    clock: Callable[[], datetime] | None = getattr(request.app.state, "clock", None)
    return clock() if clock else datetime.now(UTC)


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


CurrentUser = Annotated[User, Depends(current_user)]
InteractiveUser = Annotated[User, Depends(interactive_user)]
AdminUser = Annotated[User, Depends(require_role("admin"))]
