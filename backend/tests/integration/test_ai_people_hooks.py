"""Owner item 3 (2026-11-08): AI usage > People is filled from hooks plugin records alone
(no telemetry), for Last 7 days, across a day boundary, with the AI rollup for older days
built or not. D115: People counts named people; a session telemetry also saw counts once.
Synthetic data."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from tests.integration.test_claude_hooks import _otlp
from tests.integration.test_claude_hooks import lab as hooks_lab  # noqa: F401  # fixture
from tests.integration.test_hooks_rollup import _record
from tests.integration.test_otlp import send


@pytest.fixture
def lab(hooks_lab: dict[str, Any]) -> dict[str, Any]:  # noqa: F811  # wraps the fixture
    return hooks_lab


def _people(lab: dict[str, Any], start: datetime) -> dict[str, dict[str, Any]]:
    app = lab["app"]
    app.state.page_cache.clear()
    app.state.ai_usage.cache = None
    res = lab["admin"].get("/api/ai/usage", params={"start": start.isoformat()})
    assert res.status_code == 200, res.text
    return {p["person"]: p for p in res.json()["people"]}


def _ingest(lab: dict[str, Any], now: datetime, records: list[dict[str, Any]]) -> None:
    app = lab["app"]
    app.state.ingest._clock = lambda: now
    app.state.ai_rollup._clock = lambda: now
    assert send(lab, _otlp(records)).status_code < 300
    app.state.ingest.run_once()


def _now() -> datetime:
    # Today at 12:00 UTC, never the clock's own time: records a few minutes after `now - 5
    # days` must not cross UTC midnight unless a test means them to (failed at 23:56 UTC).
    return datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)


@pytest.mark.parametrize("built", [False, True])
def test_hooks_only_person_five_days_old_shows_for_last_7_days(
    lab: dict[str, Any], built: bool
) -> None:
    now = _now()
    at = now - timedelta(days=5)
    _ingest(lab, now, [_record(at + timedelta(minutes=i), i) for i in range(1, 6)])
    if built:
        lab["app"].state.ai_rollup.run()
        lab["app"].state.ai_rollup.refresh_today(max_age_s=0)
    people = _people(lab, (now - timedelta(days=7)).replace(second=0))
    row = people.get("dana@example.com")
    assert row is not None, people
    assert (row["via"], row["seen_through"]) == (["hooks"], "plugin")
    assert (row["sessions"], row["tool_calls"], row["cost_reported"]) == (1, 5, False)


@pytest.mark.parametrize("built", [False, True])
def test_a_session_across_utc_midnight_counts_once_and_the_range_edge_holds(
    lab: dict[str, Any], built: bool
) -> None:
    now = _now()
    midnight = (now - timedelta(days=5)).replace(hour=0, minute=0, second=0)
    start = (now - timedelta(days=7)).replace(second=0)
    records = [
        _record(midnight - timedelta(minutes=2), 1, session_id="s-night"),
        _record(midnight + timedelta(minutes=2), 2, session_id="s-night"),
        # Just before the range starts: not in Last 7 days.
        _record(start - timedelta(minutes=5), 3, session_id="s-old", user="erin@example.com"),
    ]
    _ingest(lab, now, records)
    if built:
        lab["app"].state.ai_rollup.run()
    people = _people(lab, start)
    assert set(people) == {"dana@example.com"}
    assert (people["dana@example.com"]["sessions"], people["dana@example.com"]["tool_calls"]) == (
        1,
        2,
    )


def test_a_resent_record_and_a_test_record_are_not_use(lab: dict[str, Any]) -> None:
    now = _now()
    at = now - timedelta(days=5)
    one = _record(at, 7)
    test = _record(at, 8, test_record="true", user="")
    _ingest(lab, now, [one, one, test])  # the same install and seq twice: one copy
    people = _people(lab, (now - timedelta(days=7)).replace(second=0))
    assert set(people) == {"dana@example.com"}
    assert people["dana@example.com"]["tool_calls"] == 1
