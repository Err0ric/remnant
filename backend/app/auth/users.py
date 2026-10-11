"""User accounts in the metadata database."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.auth.passwords import hash_password, needs_rehash, verify_password
from app.core.errors import ConflictError, NotFoundError, SetupClosedError
from app.core.ids import new_id
from app.meta.db import MetaDB

Role = Literal["admin", "analyst", "auditor"]


@dataclass(frozen=True, slots=True)
class User:
    user_id: str
    username: str
    role: Role
    disabled: bool = False


# Loopback install with no accounts: one implicit local admin (ADR-0001 item 1).
LOCAL_USER = User(user_id="local", username="local", role="admin")


class UserStore:
    def __init__(self, meta: MetaDB) -> None:
        self._meta = meta

    def count(self) -> int:
        with self._meta.connect() as con:
            return int(con.execute("SELECT count(*) FROM users").fetchone()[0])

    def create(self, username: str, password: str, role: Role, disabled: bool = False) -> User:
        user = User(new_id(), username, role, disabled)
        with self._meta.connect() as con:
            try:
                con.execute(
                    "INSERT INTO users"
                    " (user_id, username, password_hash, role, disabled, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        user.user_id,
                        username,
                        hash_password(password),
                        role,
                        int(disabled),
                        datetime.now(UTC).isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError(f"A user named {username} already exists") from exc
        return user

    def create_first_admin(self, username: str, password: str) -> User:
        """Create the admin only if no user exists, atomically."""
        user = User(new_id(), username, "admin")
        with self._meta.connect() as con:
            cur = con.execute(
                # Setup signs the admin in, so it counts as their first sign-in.
                "INSERT INTO users"
                " (user_id, username, password_hash, role, created_at, last_login_at)"
                " SELECT ?, ?, ?, 'admin', ?, ? WHERE NOT EXISTS (SELECT 1 FROM users)",
                (
                    user.user_id,
                    username,
                    hash_password(password),
                    datetime.now(UTC).isoformat(),
                    datetime.now(UTC).isoformat(),
                ),
            )
            if cur.rowcount != 1:
                raise SetupClosedError("Setup is closed: an administrator already exists")
        return user

    def get(self, user_id: str) -> User | None:
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT user_id, username, role, disabled FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        return _user(row) if row else None

    def authenticate(self, username: str, password: str) -> User | None:
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT user_id, username, role, disabled, password_hash FROM users"
                " WHERE username = ?",
                (username,),
            ).fetchone()
        if not verify_password(row["password_hash"] if row else None, password) or row is None:
            return None
        user = _user(row)
        if user.disabled:
            return None
        with self._meta.connect() as con:
            con.execute(
                "UPDATE users SET last_login_at = ? WHERE user_id = ?",
                (datetime.now(UTC).isoformat(), user.user_id),
            )
            if needs_rehash(row["password_hash"]):
                con.execute(
                    "UPDATE users SET password_hash = ? WHERE user_id = ?",
                    (hash_password(password), user.user_id),
                )
        return user

    def set_password(self, username: str, password: str) -> None:
        """Local recovery path (`app-admin reset-password`). Signs the user out everywhere."""
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT user_id FROM users WHERE username = ?", (username,)
            ).fetchone()
            if row is None:
                raise NotFoundError(f"No user named {username}")
            con.execute(
                "UPDATE users SET password_hash = ?, disabled = 0 WHERE user_id = ?",
                (hash_password(password), row["user_id"]),
            )
            con.execute("DELETE FROM sessions WHERE user_id = ?", (row["user_id"],))


def _user(row: sqlite3.Row) -> User:
    return User(row["user_id"], row["username"], row["role"], bool(row["disabled"]))
