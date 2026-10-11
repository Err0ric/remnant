"""Cron schedules for scheduled searches and rules (SPEC 5.5)."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.core.errors import ParamInvalidError
from app.search.cron import PRESETS, Cron

T0 = datetime(2026, 10, 11, 8, 17, 30, tzinfo=UTC)  # a Sunday


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("* * * * *", datetime(2026, 10, 11, 8, 18, tzinfo=UTC)),
        ("0 * * * *", datetime(2026, 10, 11, 9, 0, tzinfo=UTC)),
        ("*/15 * * * *", datetime(2026, 10, 11, 8, 30, tzinfo=UTC)),
        ("5,40 8 * * *", datetime(2026, 10, 11, 8, 40, tzinfo=UTC)),
        ("0 7 * * *", datetime(2026, 10, 12, 7, 0, tzinfo=UTC)),
        ("0 7 * * 1-5", datetime(2026, 10, 12, 7, 0, tzinfo=UTC)),  # Monday
        ("0 7 * * 6", datetime(2026, 10, 17, 7, 0, tzinfo=UTC)),  # Saturday
        ("0 0 1 * *", datetime(2026, 11, 1, 0, 0, tzinfo=UTC)),
        ("0 0 29 2 *", datetime(2028, 2, 29, 0, 0, tzinfo=UTC)),  # next leap day
        ("30 9 1 * 0", datetime(2026, 10, 11, 9, 30, tzinfo=UTC)),  # day OR weekday (cron rule)
        ("30 9 1 * 1", datetime(2026, 10, 12, 9, 30, tzinfo=UTC)),
        ("0 0 * * 7", datetime(2026, 10, 18, 0, 0, tzinfo=UTC)),  # 7 is Sunday too
        ("10-20/5 8 * * *", datetime(2026, 10, 11, 8, 20, tzinfo=UTC)),
    ],
)
def test_next_fire_time(expr: str, expected: datetime) -> None:
    assert Cron.parse(expr).next_after(T0, UTC) == expected


def test_time_zone_is_the_installations() -> None:
    la = ZoneInfo("America/Los_Angeles")
    got = Cron.parse("0 7 * * *").next_after(T0, la)  # 01:17 in Los Angeles
    assert got == datetime(2026, 10, 11, 14, 0, tzinfo=UTC)  # 07:00 PDT
    # Across the November change: 07:00 PST is 15:00 UTC.
    assert Cron.parse("0 7 * * *").next_after(
        datetime(2026, 11, 2, 0, 0, tzinfo=UTC), la
    ) == datetime(2026, 11, 2, 15, 0, tzinfo=UTC)


def test_presets_parse() -> None:
    assert set(PRESETS) == {"hourly", "daily", "weekdays"}
    for expr in PRESETS.values():
        Cron.parse(expr).next_after(T0, UTC)


@pytest.mark.parametrize(
    "expr",
    [
        "",
        "* * * *",
        "* * * * * *",
        "60 * * * *",
        "* 24 * * *",
        "* * 0 * *",
        "* * 32 * *",
        "* * * 13 *",
        "* * * * 8",
        "*/0 * * * *",
        "5-1 * * * *",
        "a * * * *",
        "0 0 31 2 *",  # never happens
        ",".join(str(m) for m in range(60)) + " * * * *",  # over the length limit
        "0 0 * * *" + " " * 300,
    ],
)
def test_bad_expressions_are_refused(expr: str) -> None:
    with pytest.raises(ParamInvalidError):
        Cron.parse(expr)


def test_naive_times_are_refused() -> None:
    with pytest.raises(ValueError):
        Cron.parse("* * * * *").next_after(datetime(2026, 1, 1), UTC)
