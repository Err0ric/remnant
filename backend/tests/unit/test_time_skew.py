"""Event times a whole number of hours off are reported, delivery delay is not."""

from datetime import UTC, datetime, timedelta

import pytest

from app.ingest.skew import SkewTracker, offset_hours, skew_text


@pytest.mark.parametrize(
    ("center_s", "expected"),
    [
        (7 * 3600, 7.0),  # Pacific daylight read as UTC: events 7 hours early
        (-5.5 * 3600, -5.5),  # India read as UTC: 5.5 hours late
        (7 * 3600 + 120, 7.0),  # plus two minutes of delivery delay
        (30, None),  # ordinary delay
        (40 * 60, None),  # under the minimum
        (7 * 3600 + 15 * 60, None),  # not near a half hour
    ],
)
def test_offset_hours(center_s: float, expected: float | None) -> None:
    assert offset_hours([center_s + i % 5 for i in range(100)]) == expected


def test_a_backfill_with_spread_out_times_is_not_a_zone() -> None:
    assert offset_hours([3600 * h for h in range(1, 100)]) is None


def test_too_few_events_say_nothing() -> None:
    assert offset_hours([7 * 3600] * 10) is None


def test_tracker_keeps_recent_rows_per_source() -> None:
    tracker = SkewTracker()
    now = datetime(2026, 10, 22, 6, 0, tzinfo=UTC)
    rows = [{"time": now - timedelta(hours=7, seconds=i), "time_observed": now} for i in range(50)]
    tracker.observe("fw", rows)
    tracker.observe("ok", [{"time": now, "time_observed": now} for _ in range(50)])
    tracker.observe("none", [{"time": None, "time_observed": now}])
    assert tracker.offsets() == {"fw": 7.0}
    tracker.forget("fw")
    assert tracker.offsets() == {}


def test_wording() -> None:
    assert skew_text(7.0) == "Event times look 7 hours early; check this source's time zone"
    assert skew_text(-1.0) == "Event times look 1 hour late; check this source's time zone"
    assert skew_text(5.5) == "Event times look 5.5 hours early; check this source's time zone"
