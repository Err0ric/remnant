"""Single sign-on accounts (ADR-0013): bind through an invite, then find by issuer + subject.

The protocol checks live in `auth.oidc`; this module decides which account, if any, a
verified identity signs in as, and audits every refusal.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable
from datetime import datetime

from app.auth.oidc import Identity, OidcClient
from app.auth.ratelimit import LoginLimiter
from app.auth.users import User
from app.core.config import SsoConfig
from app.core.errors import LinkInvalidError, RateLimitedError, SsoRefusedError
from app.meta.audit import AuditLog
from app.meta.db import MetaDB

# Per client address. Generous enough for an office behind one NAT signing in at 9 am,
# tight enough that a script cannot fill the flow store or the audit log (review, 2026-10-12).
STARTS_PER_WINDOW = 60
REFUSALS_AUDITED_PER_WINDOW = 30
WINDOW_S = 300


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class SsoAccounts:
    def __init__(
        self,
        config: SsoConfig,
        oidc: OidcClient,
        meta: MetaDB,
        audit: AuditLog,
        clock: Callable[[], datetime],
    ) -> None:
        self.label = config.label
        self.oidc = oidc
        self._required = frozenset(config.required_groups)
        self._meta = meta
        self._audit = audit
        self._clock = clock
        self._starts = LoginLimiter(STARTS_PER_WINDOW, WINDOW_S)
        self._refusals = LoginLimiter(REFUSALS_AUDITED_PER_WINDOW, WINDOW_S)

    def begin(self, link_token: str | None, ip: str | None) -> tuple[str, str]:
        """Provider URL and flow cookie. A link is checked now so a dead one fails early."""
        wait = self._starts.reserve([f"sso-start:{ip}"], self._clock().timestamp())
        if wait:
            raise RateLimitedError("Too many sign-in attempts. Try again later.", wait)
        if link_token is not None and self._link_user(link_token) is None:
            self._audit_refusal({"reason": "bad_link"}, ip)
            raise LinkInvalidError(
                "This link is invalid, expired, or already used. Ask an administrator for a new one"
            )
        return self.oidc.begin(link_token)

    def complete(self, state: str, code: str, cookie: str | None, ip: str | None) -> User:
        """Verify the sign-in and return the account it maps to, or raise SsoRefusedError."""
        identity: Identity | None = None
        try:
            identity, link = self.oidc.finish(state, code, cookie)
            self._check_groups(identity)
            user = self._bind(identity, link) if link else self._find(identity)
        except SsoRefusedError as exc:
            detail = {"reason": exc.code, "detail": exc.reason[:200]}
            if identity is not None:
                detail["name"] = identity.name
            self._audit_refusal(detail, ip)
            raise
        if link:
            self._audit.write(
                "user.sso_linked", "success", user.user_id, ip, {"name": identity.name}
            )
        with self._meta.connect() as con:
            con.execute(
                "UPDATE users SET last_login_at = ? WHERE user_id = ?",
                (self._clock().isoformat(), user.user_id),
            )
        return user

    def refuse(self, code: str, reason: str, ip: str | None) -> None:
        """Audit a refusal that happened before any flow was found (provider error, bad call)."""
        self._audit_refusal({"reason": code, "detail": reason[:200]}, ip)

    def _audit_refusal(self, detail: dict[str, str], ip: str | None) -> None:
        """One audit row per refusal, up to a limit per address; a flood is not recorded row
        by row, since the audit table can never be trimmed."""
        if self._refusals.reserve([f"sso-refused:{ip}"], self._clock().timestamp()):
            return
        self._audit.write("auth.sso_refused", "failure", None, ip, detail)

    # --- helpers -------------------------------------------------------------------------

    def _check_groups(self, identity: Identity) -> None:
        if not self._required:
            return
        if identity.groups is None:
            raise SsoRefusedError("too_many_groups", "groups claim replaced by an overage pointer")
        if not self._required.intersection(identity.groups):
            raise SsoRefusedError("not_in_group", "not a member of a required group")

    def _find(self, identity: Identity) -> User:
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT user_id, username, role, disabled FROM users"
                " WHERE sso_issuer = ? AND sso_subject = ?",
                (identity.issuer, identity.subject),
            ).fetchone()
        if row is None:
            raise SsoRefusedError("not_invited", "no account is bound to this identity")
        if row["disabled"]:
            raise SsoRefusedError("disabled", f"account {row['user_id']} is disabled")
        return User(row["user_id"], row["username"], row["role"])

    def _link_user(self, token: str) -> str | None:
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT t.user_id, t.expires_at, u.disabled FROM user_tokens t"
                " JOIN users u ON u.user_id = t.user_id WHERE t.token_hash = ?",
                (_digest(token),),
            ).fetchone()
        if row is None or row["disabled"]:
            return None
        if datetime.fromisoformat(row["expires_at"]) <= self._clock():
            return None
        return str(row["user_id"])

    def _bind(self, identity: Identity, token: str) -> User:
        """Finish an invite or reset link: this identity becomes the account's sign-in.

        The link is checked and used up in the same transaction as the bind, so two
        callbacks racing on one link cannot both succeed (review, 2026-10-12).
        """
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT t.user_id, t.expires_at, u.disabled FROM user_tokens t"
                " JOIN users u ON u.user_id = t.user_id WHERE t.token_hash = ?",
                (_digest(token),),
            ).fetchone()
            live = (
                row is not None
                and not row["disabled"]
                and datetime.fromisoformat(row["expires_at"]) > self._clock()
            )
            if not live or row is None:
                raise SsoRefusedError("expired", "invite or reset link no longer valid")
            user_id = str(row["user_id"])
            used = con.execute(
                "DELETE FROM user_tokens WHERE token_hash = ?", (_digest(token),)
            ).rowcount
            if used != 1:
                raise SsoRefusedError("expired", "invite or reset link used concurrently")
            other = con.execute(
                "SELECT user_id FROM users WHERE sso_issuer = ? AND sso_subject = ?",
                (identity.issuer, identity.subject),
            ).fetchone()
            if other is not None and other["user_id"] != user_id:
                raise SsoRefusedError(
                    "already_linked", f"identity already signs in as {other['user_id']}"
                )
            try:
                con.execute(
                    "UPDATE users SET sso_issuer = ?, sso_subject = ? WHERE user_id = ?",
                    (identity.issuer, identity.subject, user_id),
                )
            except sqlite3.IntegrityError as exc:  # a parallel bind won the race
                raise SsoRefusedError("already_linked", "identity bound concurrently") from exc
            # Any other link for this account goes too, and sessions from before the reset end.
            con.execute("DELETE FROM user_tokens WHERE user_id = ?", (user_id,))
            con.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            row = con.execute(
                "SELECT user_id, username, role FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        return User(row["user_id"], row["username"], row["role"])
