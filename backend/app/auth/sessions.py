"""Server-side sessions and CLI/API tokens. Only a SHA-256 of each secret is stored.

Browser sessions and CLI tokens share one table; `kind` tells them apart. Each row has
a public `token_id` so tokens can be listed and revoked without ever showing the secret
again.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from app.meta.db import MetaDB

SessionKind = Literal["browser", "cli"]
LAST_USED_RESOLUTION = timedelta(seconds=60)  # avoid a database write on every request


@dataclass(frozen=True, slots=True)
class SessionInfo:
    user_id: str
    csrf_token: str
    kind: SessionKind
    token_id: str = ""


@dataclass(frozen=True, slots=True)
class TokenInfo:
    token_id: str
    label: str
    created_at: str
    expires_at: str
    last_used_at: str | None


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class SessionStore:
    def __init__(self, meta: MetaDB) -> None:
        self._meta = meta

    def issue(
        self,
        user_id: str,
        kind: SessionKind,
        ttl: timedelta,
        now: datetime,
        label: str | None = None,
    ) -> tuple[str, str, str]:
        """Returns (secret, csrf token, public token id)."""
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        token_id = secrets.token_hex(16)
        with self._meta.connect() as con:
            con.execute("DELETE FROM sessions WHERE expires_at <= ?", (now.isoformat(),))
            con.execute(
                "INSERT INTO sessions"
                " (token_hash, user_id, csrf_token, kind, created_at, expires_at, token_id, label)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _digest(token),
                    user_id,
                    csrf,
                    kind,
                    now.isoformat(),
                    (now + ttl).isoformat(),
                    token_id,
                    label,
                ),
            )
        return token, csrf, token_id

    def create(
        self, user_id: str, kind: SessionKind, ttl: timedelta, now: datetime
    ) -> tuple[str, str]:
        token, csrf, _ = self.issue(user_id, kind, ttl, now)
        return token, csrf

    def resolve(self, token: str, now: datetime) -> SessionInfo | None:
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT user_id, csrf_token, kind, expires_at, token_id, last_used_at"
                " FROM sessions WHERE token_hash = ?",
                (_digest(token),),
            ).fetchone()
            if row is None or datetime.fromisoformat(row["expires_at"]) <= now:
                return None
            last = row["last_used_at"]
            if last is None or now - datetime.fromisoformat(last) >= LAST_USED_RESOLUTION:
                con.execute(
                    "UPDATE sessions SET last_used_at = ? WHERE token_hash = ?",
                    (now.isoformat(), _digest(token)),
                )
        return SessionInfo(row["user_id"], row["csrf_token"], row["kind"], row["token_id"] or "")

    def revoke(self, token: str) -> None:
        with self._meta.connect() as con:
            con.execute("DELETE FROM sessions WHERE token_hash = ?", (_digest(token),))

    def list_tokens(self, user_id: str, now: datetime) -> list[TokenInfo]:
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT token_id, label, created_at, expires_at, last_used_at FROM sessions"
                " WHERE user_id = ? AND kind = 'cli' AND expires_at > ? ORDER BY created_at",
                (user_id, now.isoformat()),
            ).fetchall()
        return [
            TokenInfo(
                r["token_id"],
                r["label"] or "CLI",
                r["created_at"],
                r["expires_at"],
                r["last_used_at"],
            )
            for r in rows
        ]

    def revoke_token(self, user_id: str, token_id: str) -> bool:
        """Revoke one of this user's tokens. Another user's token id is simply not found."""
        with self._meta.connect() as con:
            cur = con.execute(
                "DELETE FROM sessions WHERE user_id = ? AND token_id = ? AND kind = 'cli'",
                (user_id, token_id),
            )
            return cur.rowcount > 0

    def revoke_user(self, user_id: str) -> int:
        with self._meta.connect() as con:
            return con.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,)).rowcount


def csrf_matches(expected: str, presented: str | None) -> bool:
    return presented is not None and hmac.compare_digest(expected, presented)
