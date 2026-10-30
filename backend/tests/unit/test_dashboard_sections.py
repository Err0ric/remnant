"""Dashboard sections (ADR-0038 edit 10): page windows and "outside approved countries"."""

from datetime import UTC, datetime, timedelta

from app.enrich.geoip import GeoInfo
from app.search.dashboard import (
    NO_GEOIP,
    NOT_ADDRESS,
    NOT_IN_GEOIP,
    NOT_PUBLIC,
    _history,
    _outside,
    _trend,
    bounds,
    trend_points,
    unplaced,
)

NOW = datetime(2026, 10, 30, 11, 37, tzinfo=UTC)


def test_windows_end_now_and_compare_with_the_same_length_before() -> None:
    start, before, buckets = bounds("24h", NOW)
    assert len(buckets) == 24 and buckets[-1] == datetime(2026, 10, 30, 11, tzinfo=UTC)
    assert start == buckets[0] and start - before == timedelta(hours=24)
    start, before, buckets = bounds("7d", NOW)
    assert len(buckets) == 7 and buckets[-1] == datetime(2026, 10, 30, tzinfo=UTC)
    assert start == datetime(2026, 10, 24, tzinfo=UTC) and start - before == timedelta(days=7)
    assert len(bounds("30d", NOW)[2]) == 30


def test_outside_counts_only_placed_addresses_in_other_countries() -> None:
    places = {
        "198.51.100.1": GeoInfo("US", "United States", 64500, "Example"),
        "203.0.113.5": GeoInfo("NL", "Netherlands", 64501, "Example"),
    }

    def geo(ips: list[str]) -> dict[str, GeoInfo]:
        return {i: places[i] for i in ips if i in places}

    rows = [["198.51.100.1", 10, 4], ["203.0.113.5", 3, 1], ["192.0.2.9", 7, 7]]
    kpi, _ = _outside(rows, geo, {"US"})
    assert (kpi.value, kpi.before) == (3, 1)  # the unplaced address is not counted
    kpi, _ = _outside(rows, geo, {"US", "NL"})
    assert (kpi.value, kpi.before) == (0, 0)


def test_trend_is_hourly_through_7_days_and_lines_up_the_window_before() -> None:
    unit, points = trend_points("24h", NOW)
    assert unit == "hour" and len(points) == 24
    unit, points = trend_points("7d", NOW)
    # Oct 24 00:00 through the hour holding now (Oct 30 11:00): 6 days and 12 hours.
    assert unit == "hour" and points[0] == datetime(2026, 10, 24, tzinfo=UTC)
    assert len(points) == 6 * 24 + 12 and points[-1] == datetime(2026, 10, 30, 11, tzinfo=UTC)
    unit, points = trend_points("30d", NOW)
    assert unit == "day" and len(points) == 30
    unit, points = trend_points("7d", NOW)
    rows = [
        ["2026-10-24 00:00:00", 3],  # first point now
        ["2026-10-17 00:00:00", 5],  # the same point a week before
        ["2026-10-30 11:00:00", 2],
        ["2026-10-01 00:00:00", 9],  # outside both windows
    ]
    t = _trend(rows, points, timedelta(days=7))
    assert (t.counts[0], t.before[0], t.counts[-1]) == (3, 5, 2)
    assert sum(t.counts) == 5 and sum(t.before) == 5


def test_no_changes_until_each_counted_source_covers_90_percent_of_the_window_before() -> None:
    start, before, _ = bounds("7d", NOW)  # before: Oct 17, start: Oct 24
    old = datetime(2026, 10, 1, tzinfo=UTC)
    late = datetime(2026, 10, 21, 9, tzinfo=UTC)  # 3 of 7 days before
    first = {"fw": old, "m365": late, "quiet": late}
    assert _history(first, ["fw"], start, before).compared is True
    h = _history(first, ["fw", "m365"], start, before)
    assert h.compared is False and h.since == late
    # Only counted sources matter, and a source with no events at all is not counted.
    assert _history(first, ["fw", "missing"], start, before).compared is True
    # Half a day short of the full week is still within 90%.
    nearly = datetime(2026, 10, 17, 12, tzinfo=UTC)
    assert _history({"a": nearly}, ["a"], start, before).compared is True


def test_an_address_without_a_country_says_why() -> None:
    assert unplaced("host-17", True) == NOT_ADDRESS
    assert unplaced("-", True) == NOT_ADDRESS
    assert unplaced("100.64.3.9", True) == NOT_PUBLIC  # carrier-grade NAT
    assert unplaced("203.0.113.40", True) == NOT_PUBLIC  # documentation range
    assert unplaced("8.8.8.8", True) == NOT_IN_GEOIP
    assert unplaced("8.8.8.8", False) == NO_GEOIP


def test_identity_drills_pass_the_guard_with_bounds_filled() -> None:
    from app.ai.consents import drill_sql
    from app.engine.guard import guard
    from app.search import drill
    from app.search.dashboard import FAILED_SIGNIN, changes_drill, outside_where

    fill = {"{from}": "2026-10-24T00:00:00+00:00", "{to}": "2026-10-30T11:37:00+00:00"}
    sqls = [changes_drill(k) for k in ("inbox", "role", "ca")]
    sqls += [drill_sql(blocked=True), drill_sql(blocked=False)]
    sqls += [drill.events(FAILED_SIGNIN), drill.events(outside_where(["m365_signin"], ("us",)))]
    for sql in sqls:
        for k, v in fill.items():
            sql = sql.replace(k, v)
        assert "{" not in sql
        guard(sql, ["events"])
    assert "['US']" in outside_where(["m365_signin"], ("us",))
    assert drill.lit("o'brien") == "'o''brien'"
