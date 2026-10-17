"""Hash chains shared by the lake ledger and the audit log (ADR-0022)."""

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
