"""User lifecycle for administrators: invite, role, disable, reset (ADR-0004).

Passwords are only ever set by the user, through a one-time link. Links are
single use, expire after 24 hours, and are stored as SHA-256 digests.
"""

import hashlib
import secrets
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from app.auth.passwords import hash_password
from app.auth.ratelimit import LoginLimiter
from app.auth.users import Role, User
from app.core.errors import (
    ConflictError,
    FirstUserAdminError,
    ForbiddenError,
    LastAdminError,
    LinkInvalidError,
    NotFoundError,
    RateLimitedError,
)
from app.core.ids import new_id
from app.meta.audit import AuditLog
from app.meta.db import MetaDB

LINK_TTL = timedelta(hours=24)
PENDING_HASH = "!"  # not a valid Argon2 hash, so no password matches it
Purpose = Literal["invite", "reset"]


@dataclass(frozen=True, slots=True)
class UserRecord:
    user_id: str
    username: str
    role: Role
    disabled: bool
    pending: bool
    created_at: str
    last_login_at: str | None


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class UserAdmin:
    def __init__(
        self,
        meta: MetaDB,
        audit: AuditLog,
        limiter: LoginLimiter,
        clock: Callable[[], datetime],
    ) -> None:
        self._meta = meta
        self._audit = audit
        self._limiter = limiter
        self._clock = clock

    # --- reads -----------------------------------------------------------------------

    def all(self) -> list[UserRecord]:
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT user_id, username, role, disabled, password_hash, created_at,"
                " last_login_at FROM users ORDER BY username COLLATE NOCASE"
            ).fetchall()
        return [
            UserRecord(
                r["user_id"],
                r["username"],
                r["role"],
                bool(r["disabled"]),
                r["password_hash"] == PENDING_HASH,
                r["created_at"],
                r["last_login_at"],
            )
            for r in rows
        ]

    # --- changes ---------------------------------------------------------------------

    def invite(self, username: str, role: Role, actor: User, ip: str | None) -> tuple[User, str]:
        now = self._clock()
        user = User(new_id(), username, role)
        token = secrets.token_urlsafe(32)
        with self._meta.connect() as con:
            self._assert_admin(con, actor)
            if role != "admin" and con.execute("SELECT 1 FROM users LIMIT 1").fetchone() is None:
                raise FirstUserAdminError(
                    "The first account must be an administrator, "
                    "or nobody could manage this install"
                )
            try:
                con.execute(
                    "INSERT INTO users (user_id, username, password_hash, role, created_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (user.user_id, username, PENDING_HASH, role, now.isoformat()),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError(f"A user named {username} already exists") from exc
            self._store_link(con, user.user_id, "invite", token, actor.user_id, now)
        self._audit.write(
            "user.invite",
            "success",
            actor.user_id,
            ip,
            {"target": user.user_id, "username": username, "role": role},
        )
        return user, token

    def update(
        self,
        user_id: str,
        actor: User,
        ip: str | None,
        role: Role | None = None,
        disabled: bool | None = None,
    ) -> UserRecord:
        try:
            return self._update(user_id, actor, ip, role, disabled)
        except LastAdminError:
            self._audit.write(
                "user.update",
                "failure",
                actor.user_id,
                ip,
                {"target": user_id, "reason": "last_admin", "role": role, "disabled": disabled},
            )
            raise

    def _update(
        self,
        user_id: str,
        actor: User,
        ip: str | None,
        role: Role | None,
        disabled: bool | None,
    ) -> UserRecord:
        with self._meta.connect() as con:
            con.execute("BEGIN IMMEDIATE")  # serialise the last-admin check with the write
            self._assert_admin(con, actor)
            row = con.execute(
                "SELECT role, disabled, password_hash FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("No such user")
            was_active_admin = (
                row["role"] == "admin"
                and not row["disabled"]
                and row["password_hash"] != PENDING_HASH
            )
            loses_admin = (role is not None and role != "admin") or disabled is True
            if was_active_admin and loses_admin and self._active_admins(con) <= 1:
                raise LastAdminError(
                    "This is the last active administrator. Add another admin first"
                )
            if role is not None and role != row["role"]:
                con.execute("UPDATE users SET role = ? WHERE user_id = ?", (role, user_id))
            if disabled is not None and disabled != bool(row["disabled"]):
                con.execute(
                    "UPDATE users SET disabled = ? WHERE user_id = ?", (int(disabled), user_id)
                )
                if disabled:
                    # Access removal is immediate: end every session and CLI token.
                    con.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
                    con.execute("DELETE FROM user_tokens WHERE user_id = ?", (user_id,))
        if role is not None and role != row["role"]:
            self._audit.write(
                "user.role_change",
                "success",
                actor.user_id,
                ip,
                {"target": user_id, "from": row["role"], "to": role},
            )
        if disabled is not None and disabled != bool(row["disabled"]):
            action = "user.disable" if disabled else "user.enable"
            self._audit.write(action, "success", actor.user_id, ip, {"target": user_id})
        return next(u for u in self.all() if u.user_id == user_id)

    def issue_reset(self, user_id: str, actor: User, ip: str | None) -> str:
        token = secrets.token_urlsafe(32)
        with self._meta.connect() as con:
            self._assert_admin(con, actor)
            row = con.execute("SELECT disabled FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if row is None:
                raise NotFoundError("No such user")
            self._store_link(con, user_id, "reset", token, actor.user_id, self._clock())
        self._audit.write("user.reset_issued", "success", actor.user_id, ip, {"target": user_id})
        return token

    def redeem(self, token: str, password: str, ip: str | None) -> None:
        """Set a password from an invite or reset link. Ends every session of that user."""
        keys = [f"link-ip:{ip}"]
        now = self._clock()
        wait = self._limiter.reserve(keys, now.timestamp())
        if wait:
            raise RateLimitedError("Too many attempts. Try again later.", wait)
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT t.user_id, t.purpose, t.expires_at, u.disabled FROM user_tokens t"
                " JOIN users u ON u.user_id = t.user_id WHERE t.token_hash = ?",
                (_digest(token),),
            ).fetchone()
            valid = (
                row is not None
                and datetime.fromisoformat(row["expires_at"]) > now
                and not row["disabled"]
            )
            if valid:
                con.execute(
                    "UPDATE users SET password_hash = ? WHERE user_id = ?",
                    (hash_password(password), row["user_id"]),
                )
                con.execute("DELETE FROM user_tokens WHERE user_id = ?", (row["user_id"],))
                con.execute("DELETE FROM sessions WHERE user_id = ?", (row["user_id"],))
        # Audit after the connection is released: MetaDB's lock is not re-entrant.
        if not valid or row is None:
            self._audit.write("user.password_set", "failure", None, ip, {"reason": "bad_link"})
            raise LinkInvalidError(
                "This link is invalid, expired, or already used. Ask an administrator for a new one"
            )
        self._limiter.success(keys)
        self._audit.write(
            "user.password_set", "success", row["user_id"], ip, {"via": row["purpose"]}
        )

    # --- helpers ---------------------------------------------------------------------

    def _store_link(
        self,
        con: sqlite3.Connection,
        user_id: str,
        purpose: Purpose,
        token: str,
        created_by: str,
        now: datetime,
    ) -> None:
        # One live link per user: a new link invalidates any older one.
        con.execute("DELETE FROM user_tokens WHERE user_id = ?", (user_id,))
        con.execute(
            "INSERT INTO user_tokens"
            " (token_hash, user_id, purpose, created_by, created_at, expires_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                _digest(token),
                user_id,
                purpose,
                created_by,
                now.isoformat(),
                (now + LINK_TTL).isoformat(),
            ),
        )

    @staticmethod
    def _assert_admin(con: sqlite3.Connection, actor: User) -> None:
        """Re-read the actor in this transaction: a request that started before its actor
        was demoted or disabled must not complete an admin change."""
        row = con.execute(
            "SELECT role, disabled FROM users WHERE user_id = ?", (actor.user_id,)
        ).fetchone()
        if row is None:
            no_accounts = con.execute("SELECT 1 FROM users LIMIT 1").fetchone() is None
            if actor.user_id == "local" and no_accounts:
                return  # open local mode: the implicit local admin
            raise ForbiddenError("Your role does not allow this action")
        if row["role"] != "admin" or row["disabled"]:
            raise ForbiddenError("Your role does not allow this action")

    @staticmethod
    def _active_admins(con: sqlite3.Connection) -> int:
        return int(
            con.execute(
                "SELECT count(*) FROM users"
                " WHERE role = 'admin' AND disabled = 0 AND password_hash != ?",
                (PENDING_HASH,),
            ).fetchone()[0]
        )
