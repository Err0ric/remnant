"""Append-only audit log (CLAUDE.md rule 14, security rule 10).

Rows are never updated or deleted; SQLite triggers enforce that. Detail never
holds secrets, passwords, tokens, or raw event content.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from app.core.chain import GENESIS, audit_hash
from app.meta.db import MetaDB

Outcome = Literal["success", "failure", "denied"]


class AuditLog:
    def __init__(self, meta: MetaDB) -> None:
        self._meta = meta

    def write(
        self,
        action: str,
        outcome: Outcome,
        user_id: str | None,
        ip: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        content = (
            datetime.now(UTC).isoformat(),
            user_id,
            action,
            outcome,
            ip,
            json.dumps(detail or {}, default=str, separators=(",", ":")),
        )
        with self._meta.connect() as con:
            # Each row chains to the one before it (ADR-0022 row 4). The write lock is taken
            # first, so no other process can chain from the same row in between.
            con.execute("BEGIN IMMEDIATE")
            prev = con.execute(
                "SELECT chain_hash FROM audit_log WHERE chain_hash IS NOT NULL"
                " ORDER BY audit_id DESC LIMIT 1"
            ).fetchone()
            chain = audit_hash(prev[0] if prev else GENESIS, content)
            con.execute(
                "INSERT INTO audit_log (ts, user_id, action, outcome, ip, detail, chain_hash)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (*content, chain),
            )


# --- reading (Slice 5 audit log viewer) -----------------------------------------------------

MAX_PAGE = 500


@dataclass(frozen=True, slots=True)
class AuditFilter:
    """All optional. `action` matches a prefix (`query.` finds every query action)."""

    action: str | None = None
    user_id: str | None = None
    outcome: str | None = None
    since: datetime | None = None
    until: datetime | None = None


@dataclass(frozen=True, slots=True)
class AuditRow:
    audit_id: int
    ts: str
    user_id: str | None
    username: str | None
    action: str
    outcome: str
    ip: str | None
    detail: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LlmCallRow:
    call_id: str
    ts: str
    user_id: str
    username: str | None
    provider_id: str
    model: str
    locality: str
    purpose: str
    prompt_ref: str
    sources_in_scope: list[str]
    classification_result: str
    redaction_applied: bool
    redaction_counts: dict[str, int] | None  # per kind; never values (ADR-0010)
    prompt_sha256: str | None
    response_sha256: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int | None
    queue_wait_ms: int | None  # ADR-0028: time waiting for the model
    busy_retries: int | None
    citation_check: str | None
    error: str | None
    finished_at: str | None
    provider_name: str | None = None  # None once the provider was deleted
    chain_hash: str | None = None  # set when the call completed (D61)


_EVENTS_SQL = (
    "SELECT a.*, u.username FROM audit_log a LEFT JOIN users u ON u.user_id = a.user_id"
    "{where} ORDER BY a.audit_id DESC LIMIT ?"
)
_CALLS_SQL = (
    "SELECT c.*, u.username, p.name AS provider_name FROM llm_calls c"
    " LEFT JOIN users u ON u.user_id = c.owner_id"
    " LEFT JOIN llm_providers p ON p.provider_id = c.provider_id"
    "{where} ORDER BY c.ts DESC, c.call_id DESC LIMIT ?"
)


def _like_prefix(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class AuditReader:
    """Newest first, paged by id (activity) or by time then id (AI calls). Bodies of
    prompts and responses are never returned, even when `llm.store_bodies` kept them."""

    def __init__(self, meta: MetaDB) -> None:
        self._meta = meta

    def events(self, f: AuditFilter, before: int | None, limit: int) -> list[AuditRow]:
        where, args = self._where(f, "a.ts", "a.user_id")
        if f.action:
            where.append("a.action LIKE ? ESCAPE '\\'")
            args.append(_like_prefix(f.action))
        if f.outcome:
            where.append("a.outcome = ?")
            args.append(f.outcome)
        if before is not None:
            where.append("a.audit_id < ?")
            args.append(before)
        # The clauses are fixed strings chosen above; every value is a bound parameter.
        clause = " WHERE " + " AND ".join(where) if where else ""
        sql = _EVENTS_SQL.format(where=clause)
        with self._meta.connect() as con:
            rows = con.execute(sql, (*args, min(limit, MAX_PAGE))).fetchall()
        return [
            AuditRow(
                audit_id=r["audit_id"],
                ts=r["ts"],
                user_id=r["user_id"],
                username=r["username"],
                action=r["action"],
                outcome=r["outcome"],
                ip=r["ip"],
                detail=_json_object(r["detail"]),
            )
            for r in rows
        ]

    def llm_calls(
        self, f: AuditFilter, before: tuple[str, str] | None, limit: int
    ) -> list[LlmCallRow]:
        where, args = self._where(f, "c.ts", "c.owner_id")
        if f.action:  # the purpose, for AI calls
            where.append("c.purpose = ?")
            args.append(f.action)
        if f.outcome == "blocked":
            where.append("c.classification_result = 'blocked'")
        elif f.outcome == "failure":
            where.append("c.error IS NOT NULL")
        elif f.outcome == "success":
            where.append("c.error IS NULL AND c.classification_result = 'allowed'")
        if before is not None:
            where.append("(c.ts < ? OR (c.ts = ? AND c.call_id < ?))")
            args.extend([before[0], before[0], before[1]])
        clause = " WHERE " + " AND ".join(where) if where else ""
        sql = _CALLS_SQL.format(where=clause)
        with self._meta.connect() as con:
            rows = con.execute(sql, (*args, min(limit, MAX_PAGE))).fetchall()
        out = []
        for r in rows:
            scope = json.loads(r["sources_in_scope"] or "[]")
            out.append(
                LlmCallRow(
                    call_id=r["call_id"],
                    ts=r["ts"],
                    user_id=r["owner_id"],
                    username=r["username"],
                    provider_id=r["provider_id"],
                    model=r["model"],
                    locality=r["locality"],
                    purpose=r["purpose"],
                    prompt_ref=r["prompt_ref"],
                    sources_in_scope=[str(s) for s in scope] if isinstance(scope, list) else [],
                    classification_result=r["classification_result"],
                    redaction_applied=bool(r["redaction_applied"]),
                    redaction_counts=_counts(r["redaction_counts"]),
                    prompt_sha256=r["prompt_sha256"],
                    response_sha256=r["response_sha256"],
                    prompt_tokens=r["prompt_tokens"],
                    completion_tokens=r["completion_tokens"],
                    latency_ms=r["latency_ms"],
                    queue_wait_ms=r["queue_wait_ms"],
                    busy_retries=r["busy_retries"],
                    citation_check=r["citation_check"],
                    error=r["error"],
                    finished_at=r["finished_at"],
                    provider_name=r["provider_name"],
                    chain_hash=r["chain_hash"],
                )
            )
        return out

    @staticmethod
    def _where(f: AuditFilter, ts: str, user: str) -> tuple[list[str], list[Any]]:
        where: list[str] = []
        args: list[Any] = []
        if f.user_id:
            where.append(f"{user} = ?")
            args.append(f.user_id)
        if f.since:
            where.append(f"{ts} >= ?")
            args.append(f.since.astimezone(UTC).isoformat())
        if f.until:
            where.append(f"{ts} < ?")
            args.append(f.until.astimezone(UTC).isoformat())
        return where, args


def _json_object(text: str | None) -> dict[str, Any]:
    try:
        value = json.loads(text or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {"value": value}


def _counts(text: str | None) -> dict[str, int] | None:
    if not text:
        return None
    value = _json_object(text)
    return {str(k): int(v) for k, v in value.items() if isinstance(v, int)}
