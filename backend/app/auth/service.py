"""Account flows: install mode, first-run setup, login, logout (ADR-0001)."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal

from app.auth.admin import UserAdmin
from app.auth.oidc import OidcClient
from app.auth.ratelimit import LoginLimiter
from app.auth.sessions import SessionKind, SessionStore
from app.auth.setup import SetupLink
from app.auth.sso import SsoAccounts
from app.auth.users import Role, User, UserStore
from app.core.config import AppConfig, is_loopback_host
from app.core.errors import (
    LoginFailedError,
    RateLimitedError,
    SetupClosedError,
    SetupInvalidError,
)
from app.meta.audit import AuditLog
from app.meta.db import MetaDB

Mode = Literal["open", "setup", "login"]


class AuthService:
    def __init__(self, config: AppConfig, meta: MetaDB, oidc: OidcClient | None = None) -> None:
        self.users = UserStore(meta)
        self.sessions = SessionStore(meta)
        self.audit = AuditLog(meta)
        self.clock: Callable[[], datetime] = lambda: datetime.now(UTC)
        self.loopback = is_loopback_host(config.server.host)
        self._auth = config.auth
        self._limiter = LoginLimiter(config.auth.login_max_failures, config.auth.login_window_s)
        self._setup = SetupLink()
        # Own limiter for link redemption, so link guessing and login guessing are counted apart.
        self.admin = UserAdmin(
            meta,
            self.audit,
            LoginLimiter(config.auth.login_max_failures, config.auth.login_window_s),
            lambda: self.clock(),
            password_allowed=self.password_allowed,
        )
        self._has_users = False
        # Optional single sign-on (ADR-0013); None when it is off.
        self.sso = (
            SsoAccounts(config.sso, oidc, meta, self.audit, lambda: self.clock())
            if oidc is not None and config.sso.enabled
            else None
        )
        limited = config.sso.password_login == "admins"  # noqa: S105  # a policy name
        self.passwords_admins_only = self.sso is not None and limited
        if self.passwords_admins_only:
            self._end_password_sessions(meta)

    def _end_password_sessions(self, meta: MetaDB) -> None:
        """Passwords just stopped working for non-admins: end the browser sessions and CLI
        tokens they got with one. Accounts never bound to SSO can only have those."""
        with meta.connect() as con:
            ended = con.execute(
                "DELETE FROM sessions WHERE user_id IN (SELECT user_id FROM users"
                " WHERE role != 'admin' AND sso_subject IS NULL)"
            ).rowcount
        if ended:
            self.audit.write(
                "auth.sessions_ended", "success", None, None, {"reason": "sso_on", "count": ended}
            )

    def password_allowed(self, role: Role) -> bool:
        """With SSO on and passwords limited, only administrators keep one (break-glass)."""
        return not self.passwords_admins_only or role == "admin"

    def mode(self) -> Mode:
        if not self._has_users:
            # Users are never deleted, so once one exists this stays true.
            self._has_users = self.users.count() > 0
        if self._has_users:
            return "login"
        return "open" if self.loopback else "setup"

    def setup_url(self, public_host: str, port: int) -> str:
        """Issue a fresh one-time link. The token sits in the fragment, never in a request line."""
        token = self._setup.issue(self.clock())
        scheme = "http" if self.loopback else "https"
        return f"{scheme}://{public_host}:{port}/setup#{token}"

    def complete_setup(
        self, token: str, username: str, password: str, ip: str | None
    ) -> tuple[User, str, str]:
        if self.mode() == "login":
            raise SetupClosedError("Setup is closed: an administrator already exists")
        # Per address only: a global key would let anyone on the network lock setup out (S7).
        keys = [f"setup-ip:{ip}"]
        self._reserve(keys)
        if not self._setup.consume(token, self.clock()):
            self.audit.write("setup.admin_created", "failure", None, ip, {"reason": "bad_link"})
            raise SetupInvalidError("This setup link is invalid, expired, or already used")
        user = self.users.create_first_admin(username, password)
        self._limiter.success(keys)
        self._has_users = True
        self.audit.write("setup.admin_created", "success", user.user_id, ip, {"username": username})
        token_, csrf = self._start(user, "browser")
        return user, token_, csrf

    def login(
        self,
        username: str,
        password: str,
        kind: SessionKind,
        ip: str | None,
        label: str | None = None,
    ) -> tuple[User, str, str]:
        keys = [f"ip:{ip}", f"user:{username.lower()}"]
        self._reserve(keys)  # counted before the slow check, so parallel attempts cannot race it
        user = self.users.authenticate(username, password, allowed=self.password_allowed)
        if user is None:
            self.audit.write("auth.login", "failure", None, ip, {"username": username[:100]})
            raise LoginFailedError(self._login_failed_message())
        if not self.password_allowed(user.role):
            # Same answer as a wrong password, and the attempt stays counted, so this path
            # cannot confirm a guessed password (review, 2026-10-12).
            self.audit.write(
                "auth.login",
                "failure",
                user.user_id,
                ip,
                {"reason": "sso_required", "client": kind},
            )
            raise LoginFailedError(self._login_failed_message())
        self._limiter.success(keys)
        self.audit.write("auth.login", "success", user.user_id, ip, {"client": kind})
        token, csrf = self._start(user, kind, label)
        return user, token, csrf

    def _login_failed_message(self) -> str:
        if not self.passwords_admins_only:
            return "Wrong username or password"
        label = self.sso.label if self.sso else "single sign-on"
        return (
            "Wrong username or password. Only administrators sign in with a password here;"
            f" everyone else uses {label}"
        )

    def start_sso_session(self, user: User, ip: str | None) -> tuple[str, str]:
        """A browser session after a verified SSO sign-in, same as a password sign-in's."""
        self._has_users = True
        self.audit.write(
            "auth.login", "success", user.user_id, ip, {"client": "browser", "method": "sso"}
        )
        return self._start(user, "browser")

    def logout(self, token: str, user: User, ip: str | None) -> None:
        self.sessions.revoke(token)
        self.audit.write("auth.logout", "success", user.user_id, ip)

    def _start(self, user: User, kind: SessionKind, label: str | None = None) -> tuple[str, str]:
        ttl = (
            timedelta(days=self._auth.cli_token_days)
            if kind == "cli"
            else timedelta(hours=self._auth.session_hours)
        )
        token, csrf, _ = self.sessions.issue(
            user.user_id, kind, ttl, self.clock(), label=(label or "CLI") if kind == "cli" else None
        )
        return token, csrf

    def session_ttl(self) -> timedelta:
        return timedelta(hours=self._auth.session_hours)

    def _reserve(self, keys: list[str]) -> None:
        wait = self._limiter.reserve(keys, self._now_s())
        if wait:
            raise RateLimitedError("Too many failed attempts. Try again later.", wait)

    def _now_s(self) -> float:
        return self.clock().timestamp()
