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
    # MCP servers seen only in hook records are not in the first-seen index or AI usage's
    # MCP list (ADR-0026 row 13: agents and sessions read hooks); the inventory lists them.
    # Proposed in D151, pending review.
    assert "mcp:github" not in first

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
