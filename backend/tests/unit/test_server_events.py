"""server_events writer (handoff item 9): which requests are recorded, the rate caps, and
that a flood of requests never crowds out a refusal or fills memory."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.ingest import server_events as se

T0 = datetime(2026, 11, 8, 9, 0, tzinfo=UTC)


class FakeSpool:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def append(self, source_id: str, chunk: list[bytes], now: datetime) -> int:
        assert source_id == se.SOURCE_ID
        self.records += [json.loads(b) for b in chunk]
        return len(chunk)


class FakeSources:
    def list(self) -> list[Any]:
        return [type("S", (), {"source_id": se.SOURCE_ID})()]


def writer() -> tuple[se.ServerEvents, FakeSpool]:
    spool = FakeSpool()
    return se.ServerEvents(spool, FakeSources(), clock=lambda: T0), spool  # type: ignore[arg-type]  # fakes


@pytest.mark.parametrize(
    ("method", "path", "status", "want"),
    [
        ("POST", "/api/auth/login", 200, True),
        ("DELETE", "/api/tokens/{token_id}", 204, True),
        ("PUT", "/api/settings/backups", 200, True),
        ("GET", "/api/audit/{log}/export", 200, True),
        ("POST", "/api/query/export", 200, True),
        ("POST", "/api/users", 400, True),  # a failed change is still a change
        # Reads sent as POST (owner, 2026-11-10): only when denied.
        ("POST", "/api/query", 200, False),
        ("POST", "/api/query", 400, False),
        ("POST", "/api/search/facets", 200, False),
        ("POST", "/api/ask", 200, False),
        ("POST", "/api/query", 403, True),
        ("GET", "/api/users", 401, True),
        ("POST", "/api/auth/login", 429, True),
        ("GET", "/api/overview", 200, False),
        ("GET", "/api/health", 200, False),
        ("HEAD", "/api/health", 200, False),
        ("OPTIONS", "/api/query", 200, False),
        ("POST", "/api/otlp/v1/logs", 401, False),  # its refusal has its own record
        ("POST", "/api/client-errors", 200, False),
        ("GET", "/assets/index-AbCdEf12.js", 200, False),
        ("POST", "/login", 200, False),
        ("POST", "/api/not-a-route", 200, False),  # unlisted: never recorded by default
    ],
)
def test_only_listed_changes_exports_and_denials_are_recorded(
    method: str, path: str, status: int, want: bool
) -> None:
    assert se.wanted(method, path, status) is want


def test_a_request_record_is_metadata_only(tmp_path: Path) -> None:
    w, spool = writer()
    w.request("POST", "/api/searches?q=secret", 201, 4.5, "u-1", "alice", "203.0.113.50")
    w.signed_in("u-1", "alice", "203.0.113.50", "password", "browser")
    assert spool.records == []  # queued, never written on the request
    assert w.flush() == 2 and w.flush() == 0
    req, sign_in = spool.records
    assert req["event"] == "server.request" and req["time"] == T0.isoformat()
    assert req["attr"] == {
        "outcome": "success", "method": "POST", "path": "/api/searches", "status": 201,
        "duration_ms": 4.5, "user_id": "u-1", "username": "alice", "client": "203.0.113.50",
        "dropped_since_last": 0,
    }  # fmt: skip
    assert sign_in["event"] == "server.sign_in" and sign_in["attr"]["method"] == "password"


def test_a_request_flood_is_capped_and_never_crowds_out_a_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(se, "MAX_PER_MINUTE", 5)
    monkeypatch.setattr(se, "QUEUE_MAX", 8)
    monkeypatch.setattr(se.time, "monotonic", lambda: 600.0)  # one minute, never crossed
    w, spool = writer()
    for _ in range(50):
        w.request("POST", "/api/query", 200, 1.0, None, None, "198.51.100.9")
    w.refused("sign_in", "198.51.100.9", username="mallory")  # its own budget: written at once
    assert [r["event"] for r in spool.records] == ["server.refused.sign_in"]
    assert w.flush() == 5  # the cap, not the flood
    for _ in range(3):
        w.signed_in("u-2", "bob", "192.0.2.10", "sso", "browser")
    w.flush()
    assert [r["event"] for r in spool.records].count("server.sign_in") == 3


def test_the_queue_is_bounded_when_nothing_flushes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(se, "QUEUE_MAX", 4)
    w, _ = writer()
    for _ in range(20):
        w.signed_in("u-1", "alice", "192.0.2.1", "password", "cli")
    assert len(w._queue) == 4
