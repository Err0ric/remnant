"""Account flows: install mode, first-run setup, login, logout (ADR-0001)."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal

from app.auth.admin import UserAdmin
from app.auth.ratelimit import LoginLimiter
from app.auth.sessions import SessionKind, SessionStore
from app.auth.setup import SetupLink
from app.auth.users import User, UserStore
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
    def __init__(self, config: AppConfig, meta: MetaDB) -> None:
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
        )
        self._has_users = False

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
        user = self.users.authenticate(username, password)
        if user is None:
            self.audit.write("auth.login", "failure", None, ip, {"username": username[:100]})
            raise LoginFailedError("Wrong username or password")
        self._limiter.success(keys)
        self.audit.write("auth.login", "success", user.user_id, ip, {"client": kind})
        token, csrf = self._start(user, kind, label)
        return user, token, csrf

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
