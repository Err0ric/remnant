"""Unusual-hour marks on the Overview volume (D65): busy and quiet against the same hour
on the days before."""

from app.search.hour_marks import mark_hours, typical


def test_typical_is_the_median_of_the_same_hour_and_needs_three_days() -> None:
    assert typical([10, 12, 50]) == 12
    assert typical([10, 12, 14, 16]) == 13
    assert typical([10, 12]) is None
    assert typical([]) is None


def test_busy_needs_three_times_typical_and_twenty_more_events() -> None:
    marks = mark_hours([60, 25, 29, 0], [10.0, 0.0, 10.0, None])
    assert marks == ["busy", "busy", "", ""]


def test_quiet_needs_a_usually_busy_hour_at_a_quarter_or_less() -> None:
    marks = mark_hours([0, 5, 6, 0], [40.0, 20.0, 20.0, 10.0])
    assert marks == ["quiet", "quiet", "", ""]


def test_the_current_hour_is_never_quiet_because_it_is_not_over() -> None:
    assert mark_hours([0, 0], [40.0, 40.0], current=1) == ["quiet", ""]
    assert mark_hours([0, 90], [40.0, 10.0], current=1) == ["quiet", "busy"]


def test_baseline_uses_only_days_since_the_first_event() -> None:
    from datetime import UTC, datetime, timedelta

    from app.search.overview import _baseline

    hours = [datetime(2026, 10, 10, 9, tzinfo=UTC), datetime(2026, 10, 10, 10, tzinfo=UTC)]
    earlier = {datetime(2026, 10, d, 9, tzinfo=UTC): 10 * d for d in (6, 7, 8, 9)}
    usual = _baseline(earlier, hours)
    assert usual[0] == 75.0  # median of 60, 70, 80, 90; days before the 6th not counted
    assert usual[1] == 0.0  # hour 10 was always empty
    assert _baseline({}, hours) == [None, None]
    assert _baseline({hours[0] - timedelta(days=1): 5}, hours) == [None, None]
