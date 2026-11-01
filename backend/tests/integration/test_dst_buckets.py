"""Viewer-zone charts across clock changes (owner, 2026-11-01). In America/Los_Angeles,
2026-11-01 has 25 hours (01:00 to 01:59 twice) and 2026-03-08 has 23 (no 02:00). Hourly
points are one per elapsed hour, each holding only its own events; days hold their 23 or
25 hours; nothing is counted twice or dropped, from events or from the rollup with today
so far."""

from datetime import UTC, datetime, time, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import pytest

from app.ingest.writer import LakeWriter
from app.search.buckets import bucket_sql
from app.search.dashboard import _trend, bounds, trend_points
from app.search.m365 import overview
from tests.integration.test_m365_consents import _row
from tests.integration.test_m365_rollup import PLACES, SOURCES, _lab

LA = "America/Los_Angeles"


def _hours(start: datetime, n: int) -> list[datetime]:
    return [start + timedelta(hours=i) for i in range(n)]


@pytest.mark.parametrize(
    ("day_start", "length"),
    [
        (datetime(2026, 11, 1, 7, tzinfo=UTC), 25),  # Nov 1, 00:00 PDT
        (datetime(2026, 3, 8, 8, tzinfo=UTC), 23),  # Mar 8, 00:00 PST
    ],
)
def test_each_elapsed_hour_is_its_own_bucket(day_start: datetime, length: int) -> None:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    instants = [h + timedelta(minutes=15) for h in _hours(day_start, length)]
    con.execute("CREATE TABLE f (t TIMESTAMPTZ)")
    con.executemany("INSERT INTO f VALUES (?)", [(t,) for t in instants])
    params = {"unit": "hour", "tz": LA, "start": day_start}
    rows = con.execute(f"SELECT {bucket_sql()} AS b, count(*) FROM f GROUP BY 1", params)
    got = {b.astimezone(UTC): n for b, n in rows.fetchall()}
    assert got == {h: 1 for h in _hours(day_start, length)}
    day = con.execute(
        f"SELECT {bucket_sql()} AS b, count(*) FROM f GROUP BY 1", {**params, "unit": "day"}
    ).fetchall()
    assert [(b.astimezone(UTC), n) for b, n in day] == [(day_start, length)]


def test_day_points_are_the_viewer_days_with_their_lengths() -> None:
    now = datetime(2026, 11, 3, 20, tzinfo=UTC)
    _, _, days = bounds("7d", now, LA)
    lengths = [(b - a) / timedelta(hours=1) for a, b in pairwise(days)]
    nov1 = days.index(datetime(2026, 11, 1, 7, tzinfo=UTC))
    assert lengths[nov1] == 25 and all(x == 24 for i, x in enumerate(lengths) if i != nov1)
    unit, hours = trend_points("7d", now, LA)
    assert unit == "hour" and hours == _hours(days[0], len(hours))


def test_the_window_before_matches_by_day_across_the_change() -> None:
    # 30 days ending Nov 20: this window has the 25-hour day, the one before has none, so
    # "the same day a window earlier" is not a fixed number of hours back.
    now = datetime(2026, 11, 20, 20, tzinfo=UTC)
    start, before, days = bounds("30d", now, LA)
    z = ZoneInfo(LA)
    earlier = [
        datetime.combine(d.astimezone(z).date() - timedelta(days=30), time(), tzinfo=z)
        for d in days
    ]
    rows: list[list[Any]] = [[d, 1] for d in days] + [[e.astimezone(UTC), 2] for e in earlier]
    t = _trend(rows, days, start - before, LA)
    assert t.counts == [1] * 30 and t.before == [2] * 30


NOW = datetime(2026, 11, 1, 20, tzinfo=UTC)  # 12:00 PST, the 25-hour day


def _signins() -> list[dict[str, Any]]:
    """One failed sign-in every 20 minutes from Oct 25 to now: three per elapsed hour."""
    out, t = [], datetime(2026, 10, 25, 0, tzinfo=UTC)
    while t <= NOW - timedelta(minutes=5):
        out.append(
            _row(
                "m365_signin", "successful sign-in", "m365_signin",
                createdDateTime=t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                status={"errorCode": 50126, "failureReason": "bad password"},
                userPrincipalName="user1@example.com", ipAddress="203.0.113.7",
                appDisplayName="Outlook",
            )
        )  # fmt: skip
        t += timedelta(minutes=20)
    return out


def test_m365_hourly_chart_across_fall_back_from_events_and_rollup(tmp_path: Path) -> None:
    engine, rollup = _lab(tmp_path)
    rollup._clock = lambda: NOW
    LakeWriter(engine._lake).write(_signins())
    rollup.run()
    rollup.refresh_today(max_age_s=0)
    for window in ("24h", "7d"):
        live = overview(engine, None, SOURCES, PLACES, window, NOW, tz=LA)
        rolled = overview(engine, None, SOURCES, PLACES, window, NOW, rollup, tz=LA)
        for o in (live, rolled):
            assert o.outcome is not None
            pts, fail = o.outcome.points, o.outcome.failed
            assert len(set(pts)) == len(pts)  # the repeated local hour is two points
            full = [n for p, n in zip(pts, fail, strict=True) if p + timedelta(hours=1) <= NOW]
            assert full and all(n == 3 for n in full), (window, fail)
        assert live.outcome is not None and rolled.outcome is not None
        assert live.outcome.failed == rolled.outcome.failed
    seven = overview(engine, None, SOURCES, PLACES, "7d", NOW, rollup, tz=LA)
    assert seven.outcome is not None
    nov1_local_1am = [
        p for p in seven.outcome.points if p in (datetime(2026, 11, 1, 8, tzinfo=UTC),
                                                 datetime(2026, 11, 1, 9, tzinfo=UTC))
    ]  # fmt: skip
    assert len(nov1_local_1am) == 2
