"""Handoff item 1 (2026-11-11): one Claude Code session from 23:50 to 00:10 UTC counts as
one session on every page that counts sessions, with the AI rollup built or not, for a
session that ends today (the today build) or in closed days, and for ranges that start or
end at midnight. Hook records and Claude Code telemetry. Synthetic data.

The failure that found it was in the test helper: `_record` named its session after the
day of the month, so records either side of midnight were two sessions."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.engine.duckdb import QueryScope
from app.ingest.writer import LakeWriter
from tests.integration.test_agents_overview import _otel
from tests.integration.test_claude_hooks import _otlp
from tests.integration.test_claude_hooks import lab as hooks_lab  # noqa: F401  # fixture
from tests.integration.test_hooks_rollup import _record
from tests.integration.test_otlp import send

MIDNIGHT = datetime(2026, 10, 12, tzinfo=UTC)
# Six tool calls, 23:50 to 00:10 UTC, three each side of midnight.
TIMES = [MIDNIGHT + timedelta(minutes=m) for m in (-10, -6, -2, 2, 6, 10)]
NOWS = {
    "today": MIDNIGHT + timedelta(hours=6),  # the session ends in today's build
    "closed": MIDNIGHT + timedelta(days=3, hours=12),  # both days are closed
}


@pytest.fixture
def lab(hooks_lab: dict[str, Any]) -> dict[str, Any]:  # noqa: F811  # wraps the fixture
    return hooks_lab


def _load(lab: dict[str, Any], now: datetime, built: bool) -> None:
    app = lab["app"]
    app.state.ingest._clock = lambda: now - timedelta(minutes=3)  # observed before the cutoff
    app.state.ai_rollup._clock = lambda: now
    hooks = [
        _record(t, i, session_id="s-night", mcp_server_name="tracker", tool_name="mcp__tracker__x")
        for i, t in enumerate(TIMES, 1)
    ]
    assert send(lab, _otlp(hooks)).status_code < 300
    app.state.ingest.run_once()
    # Telemetry: erin's session seen only by telemetry, across the same midnight.
    tel = [_otel("claude_code.tool_result", "t-night", t.isoformat(), "erin@example.com")
           for t in TIMES]  # fmt: skip
    LakeWriter(app.state.engine._lake).write(tel)
    if built:
        rollup = app.state.ai_rollup
        rollup.run()
        rollup.refresh_today(max_age_s=0)
        scope = QueryScope(None, now - timedelta(days=7), now)
        assert "claude|2026-10-11" in rollup.covered(scope)
        assert rollup.mcp_covered(scope)
        assert (rollup.today(scope) is not None) == (now.date() == MIDNIGHT.date())


def _get(lab: dict[str, Any], path: str, **params: Any) -> Any:
    app = lab["app"]
    app.state.page_cache.clear()
    app.state.ai_usage.cache = None
    res = lab["admin"].get(path, params=params)
    assert res.status_code == 200, res.text
    return res.json()


def _people(lab: dict[str, Any], start: datetime, end: datetime | None = None) -> dict[str, Any]:
    params = {"start": start.isoformat()} | ({"end": end.isoformat()} if end else {})
    out = _get(lab, "/api/ai/usage", **params)
    return {p["person"]: (p["sessions"], p["tool_calls"]) for p in out["people"] if p["via"]}


@pytest.mark.parametrize("built", [False, True])
@pytest.mark.parametrize("case", sorted(NOWS))
def test_a_session_across_utc_midnight_counts_once_everywhere(
    lab: dict[str, Any], pin_now: Callable[[datetime], None], case: str, built: bool
) -> None:
    now = NOWS[case]
    pin_now(now)
    _load(lab, now, built)
    week = now - timedelta(days=7)
    both = {"dana@example.com": (1, 6), "erin@example.com": (1, 6)}
    after = {"dana@example.com": (1, 3), "erin@example.com": (1, 3)}

    # AI usage > People: Last 7 days, from midnight on, and up to midnight.
    assert _people(lab, week) == both
    assert _people(lab, MIDNIGHT) == after
    assert _people(lab, MIDNIGHT - timedelta(days=2), MIDNIGHT) == after
    assert _people(lab, MIDNIGHT - timedelta(hours=1), MIDNIGHT + timedelta(hours=1)) == both

    # AI usage > MCP: the six calls once (the page counts calls and installs, no sessions).
    mcp = {m["name"]: m for m in _get(lab, "/api/ai/usage", start=week.isoformat())["mcp"]}
    assert (mcp["tracker"]["calls"], mcp["tracker"]["people"]) == (6, 1)

    # Agents > Sessions, and the person page's sessions.
    sessions = _get(lab, "/api/ai/sessions", days=7)
    assert [(s["session_id"], s["tool_calls"]) for s in sessions] == [("s-night", 6)]
    mine = _get(lab, "/api/ai/sessions", days=7, person="dana@example.com")
    assert [s["session_id"] for s in mine] == ["s-night"]
    person = _get(lab, "/api/ai/people/dana@example.com/activity", days=7)
    assert [s["session_id"] for s in person["sessions"]] == ["s-night"]
    timeline = _get(lab, "/api/people/dana@example.com/timeline", days=7)
    assert [r["count"] for r in timeline["rows"] if r["kind"] == "session"] == [6]

    # Agents > Accounts and Overview.
    accounts = _get(lab, "/api/agents/accounts", days=7)
    assert [r["sessions"] for r in accounts["rows"]] == [1]
    overview = _get(lab, "/api/agents/overview", days=7)
    assert overview["sessions"]["value"] == 2  # dana's and erin's
    assert overview["calls"]["value"] == 12
