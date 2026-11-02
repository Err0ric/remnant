"""Before the Claude plugin pilot (owner's batch, item 6, 2026-11-01): hook records sent
over OTLP feed the daily AI rollup (closed days) and the 5-minute today build, so AI usage,
AI Watch, and the inventory read them without scanning the days again. Synthetic data."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.engine.duckdb import QueryScope
from tests.integration.test_claude_hooks import _otlp
from tests.integration.test_claude_hooks import lab as hooks_lab  # noqa: F401  # fixture
from tests.integration.test_otlp import send


def _record(at: datetime, n: int, **attrs: str) -> dict[str, Any]:
    base = {
        "event_name": "claude_hooks.pre_tool_use",
        "role": "tool_call",
        "session_id": f"s-{at:%d}",
        "install_id": "i1",
        "seq": str(n),
        "user": "dana@example.com",
        "tool_name": "Read",
    } | attrs
    return {
        "timeUnixNano": str(int(at.timestamp()) * 1_000_000_000),
        "body": {"stringValue": base["event_name"]},
        "attributes": [{"key": k, "value": {"stringValue": v}} for k, v in base.items()],
    }


@pytest.fixture
def lab(hooks_lab: dict[str, Any]) -> dict[str, Any]:  # noqa: F811  # wraps the fixture
    return hooks_lab


def test_hook_records_feed_the_rollup_and_the_today_build(lab: dict[str, Any]) -> None:
    app = lab["app"]
    now = datetime.now(UTC).replace(microsecond=0)
    if now.hour == 0 and now.minute < 10:
        now += timedelta(minutes=15)  # keep "today" records after midnight
    app.state.ingest._clock = lambda: now - timedelta(minutes=3)  # observed before the cutoff
    rollup = app.state.ai_rollup
    rollup._clock = lambda: now
    yesterday = now - timedelta(days=1)
    earlier = now - timedelta(minutes=5)
    records = [
        _record(yesterday, 1, tool_name="WebFetch", web_host="claude.ai"),
        _record(yesterday, 2, tool_name="mcp__github__search_issues", mcp_server_name="github",
                mcp_tool_name="search_issues"),
        _record(earlier, 3, tool_name="WebFetch", web_host="claude.ai"),
    ]  # fmt: skip
    assert send(lab, _otlp(records)).status_code < 300
    app.state.ingest.run_once()

    rollup.run()
    day = yesterday.date().isoformat()
    assert f"claude|{day}" in rollup.covered(QueryScope(None, now - timedelta(days=3), now))
    closed = app.state.engine.run(
        "SELECT service_id, sum(n) FROM ai_rollup WHERE source_id = 'claude' GROUP BY 1",
        QueryScope(None, now - timedelta(days=3), now),
        rollup=True,
    ).rows
    assert closed == [["claude", 1]]
    first = rollup.first_seen(None)
    assert "service:claude" in first and "agent:cc|dana@example.com" in first
    # D151 (accepted): an MCP server seen only in hook records is in the first-seen index.
    assert "mcp:github" in first

    rollup.refresh_today(max_age_s=0)
    part = rollup.today(QueryScope(None, now - timedelta(days=3), now))
    assert part is not None and "claude" in part[1]
    today = app.state.engine.run(
        "SELECT service_id, sum(n) FROM ai_today WHERE source_id = 'claude' GROUP BY 1",
        QueryScope(None, now - timedelta(days=3), now),
        rollup=True,
    ).rows
    assert today == [["claude", 1]]
    # AI usage counts both, read from the rollup and the today build.
    usage = (
        lab["admin"]
        .get("/api/ai/usage", params={"start": (now - timedelta(days=3)).isoformat()})
        .json()
    )
    claude = next(s for s in usage["services"] if s["service"]["id"] == "claude")
    assert claude["events"] == 2


def test_a_hook_only_mcp_server_is_listed_reviewed_and_read_from_the_rollup(
    lab: dict[str, Any],
) -> None:
    """D151: a server seen only through the hooks plugin is in AI usage's MCP list, AI
    Watch's review, and the inventory, and closed days come from the rollup's MCP rows."""
    app = lab["app"]
    now = datetime.now(UTC).replace(microsecond=0)
    app.state.ingest._clock = lambda: now
    app.state.ai_rollup._clock = lambda: now
    yesterday = now - timedelta(days=1)
    calls = [
        _record(yesterday, i, tool_name="mcp__notes__add", mcp_server_name="notes-x")
        for i in range(1, 4)
    ]
    assert send(lab, _otlp(calls)).status_code < 300
    app.state.ingest.run_once()
    start = (now - timedelta(days=3)).replace(second=0).isoformat()
    live = lab["admin"].get("/api/ai/usage", params={"start": start}).json()
    row = next(m for m in live["mcp"] if m["name"] == "notes-x")
    assert (row["calls"], row["status"], row["sources"]) == (3, "unreviewed", ["hooks"])
    app.state.ai_rollup.run()
    assert app.state.ai_rollup.mcp_covered(QueryScope(None, now - timedelta(days=3), now))
    app.state.page_cache.clear()
    app.state.ai_usage.cache = None
    rolled = lab["admin"].get("/api/ai/usage", params={"start": start}).json()
    assert next(m for m in rolled["mcp"] if m["name"] == "notes-x")["calls"] == 3
    review = app.state.ai_usage.review_mcp(QueryScope(None, now - timedelta(days=3), now))
    assert any(r[0] == "notes-x" for r in review)  # never skips review
    inv = lab["admin"].get("/api/ai/inventory", params={"days": 3}).json()
    item = next(i for i in inv["items"] if i["type"] == "mcp" and i["key"] == "notes-x")
    assert item["where"] == ["Claude Code hooks plugin"]


def test_a_server_seen_by_telemetry_and_hooks_is_listed_once_with_calls_counted_once(
    lab: dict[str, Any],
) -> None:
    """D151: presence joins both sources by name; calls come from telemetry for a session
    telemetry saw, and from hooks only for sessions it did not."""
    from app.ai.usage import MCP_SQL, mcp_sql

    app = lab["app"]
    now = datetime.now(UTC).replace(microsecond=0)
    app.state.ingest._clock = lambda: now
    t0 = now - timedelta(hours=1)
    hooks = [_record(t0, i, session_id="both", mcp_server_name="tracker") for i in range(1, 3)] + [
        _record(t0, 9, session_id="hooks-only", mcp_server_name="tracker")
    ]
    assert send(lab, _otlp(hooks)).status_code < 300
    app.state.ingest.run_once()
    engine = app.state.engine
    scope = QueryScope(None, now - timedelta(days=1), now + timedelta(minutes=1))
    # Telemetry for session "both": the same two calls, written straight to the lake.
    from app.ingest.writer import LakeWriter
    from tests.integration.test_schedules import _lake_rows

    tele = [
        {**r, "message": "claude_code.tool_result", "actor_user_name": "dana@example.com",
         "unmapped": '{"attr": {"mcp_server_name": "tracker", "session_id": "both"}}'}
        for r in _lake_rows("otel", "claude_code_otel", t0, 2)
    ]  # fmt: skip
    LakeWriter(engine._lake).write(tele)
    (row,) = [r for r in engine.run(MCP_SQL, scope).rows if r[0] == "tracker"]
    assert row[1] == 3  # 2 from telemetry for "both", 1 from hooks for "hooks-only"
    assert sorted(row[8]) == ["hooks", "telemetry"] and row[2] == ["dana@example.com"]
    assert mcp_sql(False) == MCP_SQL
