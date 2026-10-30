"""Dashboard sections (ADR-0038 edit 10): page windows and "outside approved countries"."""

from datetime import UTC, datetime, timedelta

from app.enrich.geoip import GeoInfo
from app.search.dashboard import _outside, bounds

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
