"""F60: the Events tile compares against a usual day only with 7 full days of history,
and leaves out sources newer than that."""

from datetime import UTC, datetime, timedelta

from app.search.overview import _usual_day

START = datetime(2026, 10, 22, 0, tzinfo=UTC)
END = START + timedelta(hours=23, minutes=59)


def _days(first_day_back: int, per_hour: int = 1) -> dict[datetime, int]:
    """Hourly counts from `first_day_back` days before START up to START."""
    begin = START - timedelta(days=first_day_back)
    return {begin + timedelta(hours=h): per_hour for h in range(first_day_back * 24)}


def test_under_seven_days_says_how_many() -> None:
    usual = _usual_day({"fw": _days(2)}, {"fw": [1] * 24}, START, END)
    assert usual.days == 2 and usual.average is None


def test_seven_days_compares_and_leaves_out_a_source_added_this_week() -> None:
    usual = _usual_day(
        {"fw": _days(7, per_hour=2), "new_dns": _days(1, per_hour=50)},
        {"fw": [2] * 24, "new_dns": [50] * 24},
        START,
        END,
    )
    assert usual.days == 7
    assert usual.compared == frozenset({"fw"}) and usual.new == ["new_dns"]
    assert usual.average == 48.0  # fw alone: 24 hours at 2 a day, every earlier day


def test_a_source_with_no_history_at_all_is_new() -> None:
    usual = _usual_day({}, {"m365": [3] * 24}, START, END)
    assert (usual.days, usual.average, usual.new) == (0, None, ["m365"])
