"""Audit log viewer and export (Slice 5): who may read, filters, paging, no bodies."""

import csv
import io
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from tests.integration.test_schedules import make_lab


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    out = make_lab(tmp_path)
    with sqlite3.connect(out["db"]) as db:
        db.execute(
            "INSERT INTO llm_calls (call_id, ts, owner_id, provider_id, model, locality, purpose,"
            " prompt_ref, sources_in_scope, classification_result, redaction_applied,"
            " prompt_sha256, prompt_body, response_body, error, finished_at)"
            " VALUES ('c1', '2026-10-10T11:00:00+00:00', ?, 'p1', 'qwen', 'cloud', 'ask',"
            " 'ask.v2@abc', '[\"lin_auth\"]', 'blocked', 0, 'deadbeef', 'SECRET PROMPT',"
            " 'SECRET REPLY', 'classification_blocked', '2026-10-10T11:00:01+00:00')",
            (out["ids"]["ana"],),
        )
    return out


def test_admins_and_auditors_read_the_log_and_analysts_do_not(lab: dict[str, Any]) -> None:
    assert lab["ana"].get("/api/audit/events").status_code == 403
    assert lab["ana"].get("/api/audit/llm-calls").status_code == 403
    rows = lab["aud"].get("/api/audit/events").json()
    assert rows and rows[0]["audit_id"] > rows[-1]["audit_id"]  # newest first
    assert {"source.create", "user.create"} & {r["action"] for r in rows}
    assert lab["admin"].get("/api/audit/events", headers=lab["h"]).status_code == 200


def test_filters_and_paging(lab: dict[str, Any]) -> None:
    aud = lab["aud"]
    users = aud.get("/api/audit/events", params={"action": "user."}).json()
    assert users and all(r["action"].startswith("user.") for r in users)
    ana = aud.get("/api/audit/events", params={"user_id": lab["ids"]["ana"]}).json()
    assert ana and all(r["username"] == "ana" for r in ana)
    first = aud.get("/api/audit/events", params={"limit": 2}).json()
    more = aud.get("/api/audit/events", params={"limit": 2, "before": first[-1]["audit_id"]})
    assert more.json()[0]["audit_id"] < first[-1]["audit_id"]
    none = aud.get("/api/audit/events", params={"since": "2999-01-01T00:00:00Z"}).json()
    assert none == []
    assert aud.get("/api/audit/events", params={"since": "2026-10-10T00:00:00"}).status_code == 400
    assert aud.get("/api/audit/events", params={"action": "%"}).json() == []  # literal %


def test_reading_and_exporting_are_on_the_trail(lab: dict[str, Any]) -> None:
    aud = lab["aud"]
    aud.get("/api/audit/events", params={"action": "query."})
    res = aud.get("/api/audit/events/export", params={"action": "user."})
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(res.text)))
    assert rows[0] == ["audit_id", "time", "user", "action", "outcome", "ip", "detail"]
    assert all(r[3].startswith("user.") for r in rows[1:])
    trail = aud.get("/api/audit/events", params={"action": "audit."}).json()
    actions = [(r["action"], r["detail"].get("action")) for r in trail]
    assert ("audit.export", "user.") in actions and ("audit.view", "query.") in actions


def test_ai_calls_never_return_bodies(lab: dict[str, Any]) -> None:
    (row,) = lab["aud"].get("/api/audit/llm-calls").json()
    assert row["classification_result"] == "blocked" and row["username"] == "ana"
    assert row["sources_in_scope"] == ["lin_auth"]
    assert "SECRET" not in str(row)
    blocked = lab["aud"].get("/api/audit/llm-calls", params={"outcome": "blocked"}).json()
    assert len(blocked) == 1
    assert lab["aud"].get("/api/audit/llm-calls", params={"action": "explain"}).json() == []
    export = lab["aud"].get("/api/audit/llm-calls/export")
    assert "SECRET" not in export.text and "c1" in export.text


def test_the_trail_cannot_be_deleted_or_changed(lab: dict[str, Any]) -> None:
    with sqlite3.connect(lab["db"]) as db:
        for sql in (
            "DELETE FROM audit_log",
            "UPDATE audit_log SET outcome = 'success'",
            "DELETE FROM llm_calls",
        ):
            with pytest.raises(sqlite3.DatabaseError, match="append-only"):
                db.execute(sql)
