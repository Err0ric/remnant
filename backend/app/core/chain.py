"""Hash chains shared by the lake ledger, the audit log, and AI call records (ADR-0022)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any

GENESIS = "0" * 64


def entry_hash(prev: str, op: str, path: str, sha: str, size: int, reason: str, at: str) -> str:
    """One lake ledger entry, chained to the entry before it."""
    text = "\n".join((prev, op, path, sha, str(size), reason, at))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def audit_hash(prev: str, row: Sequence[Any]) -> str:
    """One audit row (ts, user, action, outcome, ip, detail), chained to the row before."""
    text = json.dumps([prev, *[("" if v is None else str(v)) for v in row]], separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Every column a completed row holds, in a fixed order, for its chain hash (ADR-0022 row 4,
# extended to AI calls by D61). A row is chained when it is completed, so the chain follows
# completion order; rows still in flight have no hash yet.
CHAIN_COLUMNS = (
    "call_id", "ts", "owner_id", "provider_id", "model", "locality", "purpose", "prompt_ref",
    "sources_in_scope", "classification_result", "redaction_applied", "redaction_counts",
    "prompt_sha256", "prompt_body", "prompt_tokens", "completion_tokens", "latency_ms",
    "response_sha256", "response_body", "cited_event_ids", "citation_check", "error",
    "finished_at",
)  # fmt: skip


def llm_chain_content(row: dict[str, Any]) -> list[Any]:
    """Values as SQLite gives them back (a bool is stored as 0 or 1), so the hash written
    and the hash checked later agree."""
    return [int(v) if isinstance(v, bool) else v for v in (row.get(c) for c in CHAIN_COLUMNS)]
