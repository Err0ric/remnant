"""One rule for comparisons (fix list items 8, 9, and S1): when "Comparisons start", and no
change from a window before that the sources do not cover."""

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.ai.watch_summary import source_classes
from app.search.dashboard import (
    History,
    Kpi,
    Window,
    _history,
    bounds,
    comparisons_start,
    settle,
)

NOW = datetime(2026, 11, 16, 12, tzinfo=UTC)
OLDEST = datetime(2026, 11, 10, tzinfo=UTC)


def history(window: Window, now: datetime, first: dict[str, datetime], tz: str = "UTC") -> History:
    start, before, _ = bounds(window, now, tz)
    h = _history(first, list(first), start, before)
    if not h.compared and h.since is not None:
        h.starts = comparisons_start(h.since, start, before, now, window, tz)
    return h


@pytest.mark.parametrize(
    ("window", "starts"),
    [
        ("24h", None),  # Nov 14 to 15 is covered: compared now
        ("7d", datetime(2026, 11, 23, tzinfo=UTC)),
        ("30d", datetime(2027, 1, 5, tzinfo=UTC)),
    ],
)
def test_worked_examples_oldest_data_nov_10_seen_on_nov_16(
    window: Window, starts: datetime | None
) -> None:
    h = history(window, NOW, {"fw": OLDEST})
    assert h.compared is (starts is None)
    assert h.starts == starts
    if starts is None:
        return
    # The date is the first moment the same rule compares (checked at each step).
    assert history(window, starts, {"fw": OLDEST}).compared is True
    assert history(window, starts - timedelta(minutes=1), {"fw": OLDEST}).compared is False


def test_the_24_hour_window_starts_comparing_at_an_hour() -> None:
    first = {"fw": datetime(2026, 11, 15, 20, 30, tzinfo=UTC)}
    h = history("24h", NOW, first)
    # 90% of 24 hours after 20:30 is 18:06 the next day; that hour starts the window at
    # 19:00, 23 hours before its last hour.
    assert h.starts == datetime(2026, 11, 17, 18, tzinfo=UTC)
    assert history("24h", h.starts, first).compared is True
    assert history("24h", h.starts - timedelta(hours=1), first).compared is False


def test_days_start_at_the_viewers_midnight() -> None:
    tz = "America/Los_Angeles"
    h = history("7d", NOW, {"fw": OLDEST}, tz)
    assert h.starts is not None
    local = h.starts.astimezone(ZoneInfo(tz))
    assert (local.hour, local.minute) == (0, 0)
    assert history("7d", h.starts, {"fw": OLDEST}, tz).compared is True
    assert history("7d", h.starts - timedelta(minutes=1), {"fw": OLDEST}, tz).compared is False


@pytest.mark.parametrize("window", ["24h", "7d", "30d"])
def test_plenty_of_history_compares_with_no_start_date(window: Window) -> None:
    h = history(window, NOW, {"fw": datetime(2026, 1, 1, tzinfo=UTC)})
    assert h.compared is True and h.starts is None


@pytest.mark.parametrize("window", ["24h", "7d", "30d"])
def test_an_empty_lake_has_nothing_to_compare_and_no_date(window: Window) -> None:
    h = history(window, NOW, {})
    assert h.compared is True and h.since is None and h.starts is None


def test_a_rolling_window_starts_a_window_after_the_window_before_is_covered() -> None:
    start, before = NOW - timedelta(days=7), NOW - timedelta(days=14)
    first = datetime(2026, 11, 15, 17, tzinfo=UTC)
    assert comparisons_start(first, start, before, NOW) == first + timedelta(days=6.3 + 7)


@dataclass
class Part:
    history: History
    failed: Kpi
    rows: list[Kpi] = field(default_factory=list)


def test_no_earlier_data_is_not_a_change_from_zero() -> None:
    start, before, _ = bounds("7d", NOW)
    part = Part(_history({"m365": OLDEST}, ["m365"], start, before), Kpi(235, 0, drill_before="q"))
    part.rows.append(Kpi(3, 0))
    settle(part, start, before, NOW, "7d")
    assert part.failed.before is None and part.failed.drill_before is None
    assert part.rows[0].before is None
    assert part.history.starts == datetime(2026, 11, 23, tzinfo=UTC)


def test_a_covered_window_before_with_zero_is_a_real_change() -> None:
    start, before, _ = bounds("7d", NOW)
    old = datetime(2026, 10, 1, tzinfo=UTC)
    part = Part(_history({"m365": old}, ["m365"], start, before), Kpi(235, 0))
    settle(part, start, before, NOW, "7d")
    assert part.failed.before == 0 and part.history.starts is None


def test_partial_cover_counts_as_no_earlier_data_and_agrees_with_the_date() -> None:
    start, before, _ = bounds("7d", NOW)  # before: Nov 3, start: Nov 10
    half = datetime(2026, 11, 6, 12, tzinfo=UTC)  # half the window before
    part = Part(_history({"m365": half}, ["m365"], start, before), Kpi(40, 12))
    settle(part, start, before, NOW, "7d")
    assert part.history.compared is False and part.failed.before is None
    # Covered 90% from Nov 12 19:12: the window starting Nov 13 compares, on Nov 19.
    assert part.history.starts == datetime(2026, 11, 19, tzinfo=UTC)
    assert history("7d", datetime(2026, 11, 19, tzinfo=UTC), {"m365": half}).compared is True


def test_the_servers_own_events_are_not_ai_telemetry() -> None:
    kinds = source_classes([("claude", "otlp", "auto"), ("server_events", "otlp", "server_events")])
    assert kinds["telemetry"] == ["claude"]


# Zones with no clock change: across one, the Dashboard's days are 23 or 25 hours and
# Agents' are 24, so the two windows rightly differ by up to a day.
@pytest.mark.parametrize("tz", ["UTC", "Asia/Kolkata"])
@pytest.mark.parametrize("days", [7, 30])
@pytest.mark.parametrize("hour", [0, 9, 17, 23])
def test_the_same_sources_give_one_date_on_every_page(tz: str, days: int, hour: int) -> None:
    """The Dashboard's day windows and Agents' rolling window, over sources with the same
    first event, name the same day in the viewer's zone (the coordinator's check, PR 638)."""
    first = datetime(2026, 10, 31, hour, 28, tzinfo=UTC)
    window: Window = "7d" if days == 7 else "30d"
    start, before, _ = bounds(window, NOW, tz)
    dashboard = comparisons_start(first, start, before, NOW, window, tz)
    rolling = comparisons_start(
        first, NOW - timedelta(days=days), NOW - timedelta(days=2 * days), NOW
    )
    where = ZoneInfo(tz)
    assert dashboard.astimezone(where).date() == rolling.astimezone(where).date()


def test_a_clock_change_between_now_and_the_date_does_not_move_it_a_day() -> None:
    """The reviewer's case: Los Angeles leaves daylight time between now and the date, so
    the window before on that date is an hour longer than today's."""
    tz, now = "America/Los_Angeles", datetime(2026, 11, 3, 10, 21, tzinfo=UTC)
    first = {"fw": datetime(2026, 10, 6, 7, 21, tzinfo=UTC)}
    h = history("30d", now, first, tz)
    assert h.starts is not None
    assert h.starts.astimezone(ZoneInfo(tz)).date().isoformat() == "2026-12-02"
    assert history("30d", h.starts, first, tz).compared is True
    day_before = h.starts.astimezone(ZoneInfo(tz)) - timedelta(days=1)
    assert history("30d", day_before.astimezone(UTC), first, tz).compared is False


@pytest.mark.parametrize(
    "tz", ["UTC", "Asia/Kolkata", "America/Los_Angeles", "Europe/Berlin", "Australia/Sydney"]
)
@pytest.mark.parametrize("window", ["7d", "30d", "24h"])
def test_not_compared_the_step_before_and_compared_at_the_date(tz: str, window: Window) -> None:
    rng = random.Random(f"{tz}{window}")
    where = ZoneInfo(tz)
    checked = 0
    for _ in range(400):
        # Around the spring and autumn clock changes of both hemispheres.
        month = rng.choice([3, 4, 10, 11])
        now = datetime(2026, month, 1, tzinfo=UTC) + timedelta(minutes=rng.randrange(43_200))
        reach = {"24h": 2, "7d": 14, "30d": 60}[window]  # how far back data may start
        first = {"fw": now - timedelta(minutes=rng.randrange(1, 60 * 24 * reach))}
        h = history(window, now, first, tz)
        if h.compared:
            continue
        assert h.starts is not None
        checked += 1
        if window == "24h":
            earlier = h.starts - timedelta(hours=1)
        else:
            local = h.starts.astimezone(where)
            assert (local.hour, local.minute) == (0, 0)
            prev = datetime.combine(local.date() - timedelta(days=1), datetime.min.time(), where)
            earlier = prev.astimezone(UTC)
        assert history(window, h.starts, first, tz).compared is True
        assert history(window, earlier, first, tz).compared is False
    assert checked > 50
