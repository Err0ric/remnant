"""Configured model providers (SPEC 6.1). Admin-managed; keys encrypted at rest."""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from app.core.errors import ConflictError, NotFoundError, SearchInvalidError
from app.core.ids import new_id
from app.meta.db import MetaDB
from app.meta.secrets import SecretBox


@dataclass(frozen=True, slots=True)
class ProviderRecord:
    provider_id: str
    name: str
    kind: str
    base_url: str
    model: str
    enabled: bool
    has_api_key: bool
    redact: bool = False  # ADR-0010: opt-in token redaction for cloud calls
    # reasoning_effort to send (none, low, medium, high); None: the model's default.
    reasoning: str | None = None
    # ADR-0028: slots (None: 1 for local, no queue for cloud) and wait budget (None: 120 s).
    max_concurrent: int | None = None
    wait_budget_s: int | None = None


class ProviderStore:
    def __init__(self, meta: MetaDB, secrets: SecretBox, clock: Callable[[], datetime]) -> None:
        self._meta = meta
        self._secrets = secrets
        self._clock = clock

    def all(self) -> list[ProviderRecord]:
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT * FROM llm_providers ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [_record(r) for r in rows]

    def get(self, provider_id: str) -> ProviderRecord:
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT * FROM llm_providers WHERE provider_id = ?", (provider_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError("No such provider")
        return _record(row)

    def api_key(self, provider_id: str) -> str | None:
        """Decrypted key, for llm/gate.py only."""
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT api_key_enc FROM llm_providers WHERE provider_id = ?", (provider_id,)
            ).fetchone()
        if row is None or row["api_key_enc"] is None:
            return None
        return self._secrets.decrypt(row["api_key_enc"])

    def add(
        self,
        name: str,
        base_url: str,
        model: str,
        api_key: str | None,
        kind: str = "openai_compat",
    ) -> ProviderRecord:
        pid = new_id()
        now = self._clock().isoformat()
        enc = self._secrets.encrypt(api_key) if api_key else None
        with self._meta.connect() as con:
            try:
                con.execute(
                    "INSERT INTO llm_providers (provider_id, name, kind, base_url, model,"
                    " api_key_enc, enabled, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)",
                    (pid, name, kind, base_url, model, enc, now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError(f"A provider named {name} already exists") from exc
        return self.get(pid)

    def update(
        self,
        provider_id: str,
        name: str | None,
        base_url: str | None,
        model: str | None,
        enabled: bool | None,
        api_key: str | None,
        clear_api_key: bool,
        redact: bool | None = None,
        reasoning: str | None = None,
        max_concurrent: int | None = None,
        wait_budget_s: int | None = None,
    ) -> ProviderRecord:
        """For max_concurrent and wait_budget_s, None keeps the value and 0 clears it."""
        current = self.get(provider_id)
        new_model = current.model if model is None else model
        if enabled and not new_model:
            raise SearchInvalidError("Choose a model before enabling this provider")
        enc: str | None
        if clear_api_key:
            enc = None
        elif api_key:
            enc = self._secrets.encrypt(api_key)
        else:
            enc = "__keep__"
        with self._meta.connect() as con:
            try:
                con.execute(
                    "UPDATE llm_providers SET name = ?, base_url = ?, model = ?, enabled = ?,"
                    " api_key_enc = CASE WHEN ? = '__keep__' THEN api_key_enc ELSE ? END,"
                    " redact = ?, reasoning = ?, max_concurrent = ?, wait_budget_s = ?,"
                    " updated_at = ? WHERE provider_id = ?",
                    (
                        current.name if name is None else name,
                        current.base_url if base_url is None else base_url,
                        new_model,
                        int(current.enabled if enabled is None else enabled),
                        enc,
                        enc,
                        int(current.redact if redact is None else redact),
                        current.reasoning if reasoning is None else (reasoning or None),
                        current.max_concurrent
                        if max_concurrent is None
                        else (max_concurrent or None),
                        current.wait_budget_s if wait_budget_s is None else (wait_budget_s or None),
                        self._clock().isoformat(),
                        provider_id,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError(f"A provider named {name} already exists") from exc
        return self.get(provider_id)

    def delete(self, provider_id: str) -> None:
        with self._meta.connect() as con:
            if (
                con.execute(
                    "DELETE FROM llm_providers WHERE provider_id = ?", (provider_id,)
                ).rowcount
                == 0
            ):
                raise NotFoundError("No such provider")


def _record(r: sqlite3.Row) -> ProviderRecord:
    return ProviderRecord(
        provider_id=r["provider_id"],
        name=r["name"],
        kind=r["kind"],
        base_url=r["base_url"],
        model=r["model"],
        enabled=bool(r["enabled"]),
        has_api_key=r["api_key_enc"] is not None,
        redact=bool(r["redact"]),
        reasoning=r["reasoning"],
        max_concurrent=r["max_concurrent"],
        wait_budget_s=r["wait_budget_s"],
    )
