"""Alert targets: where alerts go (ADR-0007 rows 1, 4, 5, 6).

Admins create and change targets; analysts only pick them. A target's URL (which carries
its token), SMTP password, and webhook signing key are encrypted with the install key and
are never returned: listings show the kind, a host for recognition, and delivery health.
The webhook signing key is shown once, when the target is made.

Every send re-checks the destination address (`alerts/net.py`), so a target saved while a
host resolved privately cannot later be used to reach a public address over plain http or
a metadata address.
"""

import json
import secrets as pysecrets
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator

from app.alerts.net import check_smtp_host, destination
from app.alerts.render import Alert, email_parts, signed_webhook, slack_payload, teams_payload
from app.alerts.send import SendError, check_address, message, post, send_mail
from app.core.errors import ConflictError, NotFoundError, ParamInvalidError
from app.core.ids import new_id
from app.meta.db import MetaDB
from app.meta.secrets import SecretBox

TargetKind = Literal["email", "slack", "teams", "webhook"]
Security = Literal["starttls", "tls", "none"]
FAILING_AFTER = 10
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class EmailSettings(BaseModel):
    host: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=253)]
    port: int = Field(default=587, ge=1, le=65535)
    security: Security = "starttls"
    username: str | None = Field(default=None, max_length=200)
    from_addr: str = Field(max_length=320)
    to_addrs: list[str] = Field(min_length=1, max_length=20)

    @field_validator("from_addr")
    @classmethod
    def _from(cls, value: str) -> str:
        return check_address(value)

    @field_validator("to_addrs")
    @classmethod
    def _to(cls, value: list[str]) -> list[str]:
        return [check_address(v) for v in value]


@dataclass(frozen=True, slots=True)
class Target:
    target_id: str
    name: str
    kind: TargetKind
    display: str  # host only, for recognition; never the URL path or token
    settings: dict[str, Any]  # email settings (no password); empty for URL targets
    created_by: str
    created_at: str
    updated_at: str
    consecutive_failures: int
    last_error: str | None
    last_sent_at: str | None

    @property
    def failing(self) -> bool:
        return self.consecutive_failures >= FAILING_AFTER


class TargetStore:
    def __init__(self, meta: MetaDB, box: SecretBox, clock: Callable[[], datetime]) -> None:
        self._meta = meta
        self._box = box
        self._clock = clock

    # --- changes --------------------------------------------------------------------------

    def create(
        self,
        name: str,
        kind: TargetKind,
        url: str | None,
        email: EmailSettings | None,
        password: str | None,
        actor_id: str,
    ) -> tuple[Target, str | None]:
        """The new target and, for a webhook, its signing key (shown this once)."""
        display, settings, secret = self._validate(kind, url, email, password)
        signing_key: str | None = None
        if kind == "webhook":
            signing_key = pysecrets.token_urlsafe(32)
            secret["signing_key"] = signing_key
        now = self._clock().isoformat()
        tid = new_id()
        with self._meta.connect() as con:
            try:
                con.execute(
                    "INSERT INTO alert_targets (target_id, name, kind, display, settings,"
                    " secret_enc, created_by, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        tid,
                        name,
                        kind,
                        display,
                        json.dumps(settings),
                        self._box.encrypt(json.dumps(secret)),
                        actor_id,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError(f"An alert target named {name!r} already exists") from exc
        return self.get(tid), signing_key

    def update(
        self,
        target_id: str,
        name: str | None,
        url: str | None,
        email: EmailSettings | None,
        password: str | None,
    ) -> Target:
        current = self.get(target_id)
        secret = self._secret(target_id)
        display, settings = current.display, current.settings
        if current.kind == "email":
            if email is not None or password is not None:
                merged = email or EmailSettings(**current.settings)
                display, settings, fresh = self._validate(
                    "email",
                    None,
                    merged,
                    password if password is not None else secret.get("password"),
                )
                secret = {**secret, **fresh}
        elif url is not None:
            display, settings, fresh = self._validate(current.kind, url, None, None)
            secret = {**secret, **fresh}
        with self._meta.connect() as con:
            try:
                con.execute(
                    "UPDATE alert_targets SET name = ?, display = ?, settings = ?, secret_enc = ?,"
                    " updated_at = ? WHERE target_id = ?",
                    (
                        current.name if name is None else name,
                        display,
                        json.dumps(settings),
                        self._box.encrypt(json.dumps(secret)),
                        self._clock().isoformat(),
                        target_id,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError(f"An alert target named {name!r} already exists") from exc
        return self.get(target_id)

    def delete(self, target_id: str) -> None:
        self.get(target_id)
        with self._meta.connect() as con:
            con.execute("DELETE FROM alert_targets WHERE target_id = ?", (target_id,))

    # --- reading --------------------------------------------------------------------------

    def get(self, target_id: str) -> Target:
        with self._meta.connect() as con:
            r = con.execute(
                "SELECT * FROM alert_targets WHERE target_id = ?", (target_id,)
            ).fetchone()
        if r is None:
            raise NotFoundError("No such alert target")
        return _target(r)

    def all(self) -> list[Target]:
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT * FROM alert_targets ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [_target(r) for r in rows]

    # --- sending --------------------------------------------------------------------------

    def send(self, target_id: str, alert: Alert) -> None:
        """Deliver one alert now; raises SendError. Health is recorded either way."""
        target = self.get(target_id)
        secret = self._secret(target_id)
        try:
            self._send(target, secret, alert)
        except (SendError, ParamInvalidError) as exc:
            self._record(target_id, str(exc)[:300])
            raise SendError(str(exc)) from None
        self._record(target_id, None)

    def _send(self, target: Target, secret: dict[str, str], alert: Alert) -> None:
        if target.kind == "email":
            s = EmailSettings(**target.settings)
            dest = check_smtp_host(s.host, s.port, s.security)
            subject, text, html = email_parts(alert)
            send_mail(
                dest,
                s.security,
                s.username,
                secret.get("password"),
                message(s.from_addr, s.to_addrs, subject, text, html),
            )
            return
        dest = destination(target.kind, secret["url"])
        if target.kind == "webhook":
            body, headers = signed_webhook(alert, secret["signing_key"], int(time.time()))
        else:
            payload = slack_payload(alert) if target.kind == "slack" else teams_payload(alert)
            body, headers = json.dumps(payload).encode(), {"Content-Type": "application/json"}
        post(dest, body, headers)

    def _record(self, target_id: str, error: str | None) -> None:
        now = self._clock().isoformat()
        with self._meta.connect() as con:
            if error is None:
                con.execute(
                    "UPDATE alert_targets SET consecutive_failures = 0, last_error = NULL,"
                    " last_sent_at = ? WHERE target_id = ?",
                    (now, target_id),
                )
            else:
                con.execute(
                    "UPDATE alert_targets SET consecutive_failures = consecutive_failures + 1,"
                    " last_error = ? WHERE target_id = ?",
                    (error, target_id),
                )

    def _secret(self, target_id: str) -> dict[str, str]:
        with self._meta.connect() as con:
            r = con.execute(
                "SELECT secret_enc FROM alert_targets WHERE target_id = ?", (target_id,)
            ).fetchone()
        if r is None:
            raise NotFoundError("No such alert target")
        value = json.loads(self._box.decrypt(r["secret_enc"]))
        return {str(k): str(v) for k, v in value.items()}

    @staticmethod
    def _validate(
        kind: TargetKind, url: str | None, email: EmailSettings | None, password: str | None
    ) -> tuple[str, dict[str, Any], dict[str, str]]:
        """(display, settings, secret) after the address checks; raises ParamInvalidError."""
        if kind == "email":
            if email is None:
                raise ParamInvalidError("An email target needs its SMTP settings")
            dest = check_smtp_host(email.host, email.port, email.security)
            if password and len(password) > 500:
                raise ParamInvalidError("The password is too long")
            return dest.host, email.model_dump(), ({"password": password} if password else {})
        if not url:
            raise ParamInvalidError("This target needs its webhook URL")
        dest = destination(kind, url)
        return dest.host, {}, {"url": dest.url}


def _target(r: sqlite3.Row) -> Target:
    return Target(
        target_id=r["target_id"],
        name=r["name"],
        kind=r["kind"],
        display=r["display"],
        settings=json.loads(r["settings"]),
        created_by=r["created_by"],
        created_at=r["created_at"],
        updated_at=r["updated_at"],
        consecutive_failures=r["consecutive_failures"],
        last_error=r["last_error"],
        last_sent_at=r["last_sent_at"],
    )
