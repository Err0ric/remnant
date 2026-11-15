"""Alert handling numbers (D261): time to close, opened against closed by day, open and
overdue now, on a seeded meta store with a fixed clock. Each case states which alerts a
number counts: closed fast and slow, reopened, muted, merged, closed by the server, never
closed, each severity, the range's edges, the percentile with one and two values."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.alerts.items import AlertItems
from app.alerts.metrics import Handling, Thresholds, handling, percentile, spread
from app.auth.users import User
from app.meta.audit import AuditLog
from app.meta.db import MetaDB

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
START = datetime(2026, 11, 1, tzinfo=UTC)
ADMIN = User("u-admin", "admin", "admin")
ANA = User("u-ana", "ana", "analyst")
H, D = 3600, 86_400


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    meta, clock = MetaDB(tmp_path / "meta.sqlite"), Clock()
    items = AlertItems(meta, AuditLog(meta), clock=clock)
    return {"meta": meta, "clock": clock, "items": items, "n": 0}


def raise_at(lab: dict[str, Any], at: datetime, **kw: Any) -> str:
    lab["clock"].now = at
    lab["n"] += 1
    kind = kw.pop("kind", "rule")
    item = lab["items"].raise_item(kind, f"s{lab['n']}", "Alert", ref_id=f"r{lab['n']}", **kw)
    return str(item.item_id)


def close_at(lab: dict[str, Any], item_id: str, at: datetime, user: User = ADMIN) -> None:
    lab["clock"].now = at
    lab["items"].close(item_id, user, "resolved", None, None)


def numbers(
    lab: dict[str, Any],
    start: datetime = START,
    end: datetime = NOW,
    user: User = ADMIN,
    allowed: list[str] | None = None,
) -> Handling:
    lab["clock"].now = NOW
    return handling(lab["meta"], user, allowed, start, end, NOW, lab["items"].day_of, Thresholds())


@pytest.mark.parametrize(
    ("values", "median", "p90"),
    [
        ([], None, None),
        ([60.0], 60.0, 60.0),
        ([60.0, 160.0], 110.0, 150.0),
        ([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0], 6.0, 10.0),
    ],
)
def test_percentile_interpolates_between_ranks(
    values: list[float], median: float | None, p90: float | None
) -> None:
    assert percentile(values, 0.5) == median and percentile(values, 0.9) == p90
    s = spread(values)
    assert (s.count, s.median_s) == (len(values), None if median is None else round(median))


def test_an_empty_range_lists_every_day_with_zeros(lab: dict[str, Any]) -> None:
    got = numbers(lab)
    assert [d[0] for d in got.days][:2] == ["2026-11-01", "2026-11-02"]
    assert got.days[-1] == ("2026-11-10", 0, 0) and len(got.days) == 10
    assert (got.opened, got.closed, got.open, got.overdue) == (0, 0, 0, 0)
    assert got.time_to_close.count == 0 and got.time_to_close.median_s is None
    assert got.restricted is False


def test_time_to_close_counts_closes_by_a_person_in_the_range(lab: dict[str, Any]) -> None:
    fast = raise_at(lab, START + timedelta(days=2), severity="high")
    close_at(lab, fast, START + timedelta(days=2, hours=1))
    slow = raise_at(lab, START + timedelta(days=3), severity="medium")
    close_at(lab, slow, START + timedelta(days=5))
    plain = raise_at(lab, START + timedelta(days=4))  # no severity
    close_at(lab, plain, START + timedelta(days=4, minutes=30))
    got = numbers(lab)
    assert got.time_to_close.count == 3
    assert got.time_to_close.median_s == H  # 30 min, 1 h, 2 d
    assert got.time_to_close.p90_s == round(H + 0.8 * (2 * D - H))
    by = got.time_to_close_by_severity
    assert (by["high"].median_s, by["medium"].median_s, by["other"].median_s) == (H, 2 * D, 1800)
    assert (got.opened, got.closed, got.closed_not_timed) == (3, 3, 0)
    days = {d: (o, c) for d, o, c in got.days}
    assert days["2026-11-03"] == (1, 1) and days["2026-11-06"] == (0, 1)


def test_a_reopened_alert_counts_once_by_its_latest_close(lab: dict[str, Any]) -> None:
    iid = raise_at(lab, START + timedelta(days=1), severity="high")
    close_at(lab, iid, START + timedelta(days=1, hours=2))
    lab["clock"].now = START + timedelta(days=2)
    lab["items"].reopen(iid, ADMIN, None)
    open_again = numbers(lab)
    # Open again: opened once, not closed, no time to close.
    assert (open_again.opened, open_again.closed, open_again.open) == (1, 0, 1)
    assert open_again.time_to_close.count == 0
    close_at(lab, iid, START + timedelta(days=3))
    got = numbers(lab)
    assert (got.opened, got.closed, got.time_to_close.median_s) == (1, 1, 2 * D)
    assert {d: c for d, _, c in got.days if c} == {"2026-11-04": 1}


def test_muted_and_merged_alerts_are_left_out(lab: dict[str, Any]) -> None:
    lab["clock"].now = START + timedelta(days=1)
    first = lab["items"].raise_item("rule", "noisy", "Noisy", ref_id="n1")
    lab["items"].mute(first.item_id, 7, ADMIN, None)
    close_at(lab, first.item_id, START + timedelta(days=1, minutes=5))
    lab["clock"].now = START + timedelta(days=2)
    muted = lab["items"].raise_item("rule", "noisy", "Noisy", ref_id="n2")
    assert muted.close_reason == "muted"
    with lab["meta"].connect() as con:  # an older duplicate merged into another alert
        con.execute(
            "UPDATE alert_items SET close_reason = 'merged' WHERE item_id = ?",
            (first.item_id,),
        )
    got = numbers(lab)
    assert (got.opened, got.closed, got.time_to_close.count) == (0, 0, 0)


def test_closes_with_no_person_or_no_time_count_as_closed_not_in_time_to_close(
    lab: dict[str, Any],
) -> None:
    raise_at(lab, START + timedelta(days=1), kind="gap")
    lab["clock"].now = START + timedelta(days=1, hours=3)
    lab["items"].close_resolved("gap", "s1", "Backup succeeded")
    legacy = raise_at(lab, START + timedelta(days=2))
    close_at(lab, legacy, START + timedelta(days=4))
    with lab["meta"].connect() as con:  # closed before close times were kept
        con.execute("UPDATE alert_items SET closed_at = NULL WHERE item_id = ?", (legacy,))
    got = numbers(lab)
    # The gap closed by the server, and the person's close whose time was not kept.
    assert (got.closed, got.closed_not_timed, got.time_to_close.count) == (2, 2, 0)
    # The one with no close time counts on the day it was raised.
    assert {d: c for d, _, c in got.days if c} == {"2026-11-02": 1, "2026-11-03": 1}


def test_the_range_includes_both_edges_and_nothing_outside(lab: dict[str, Any]) -> None:
    end = START + timedelta(days=5)
    before = raise_at(lab, START - timedelta(seconds=1))
    close_at(lab, before, START)  # raised before, closed on the start: closed, not opened
    at_end = raise_at(lab, end)
    after = raise_at(lab, end + timedelta(seconds=1))
    close_at(lab, after, end + timedelta(hours=1))
    got = numbers(lab, end=end)
    assert (got.opened, got.closed) == (1, 1)
    assert got.time_to_close.median_s == 1
    assert got.days[0] == ("2026-11-01", 0, 1) and got.days[-1] == ("2026-11-06", 1, 0)
    assert at_end  # still open: in open now whatever the range
    assert got.open == 1


def test_open_and_overdue_now_by_severity_and_kind(lab: dict[str, Any]) -> None:
    # Overdue: High over 3 days, Medium over 7, no severity over 30 (Low).
    raise_at(lab, NOW - timedelta(days=3, minutes=1), severity="high")
    raise_at(lab, NOW - timedelta(days=2), severity="high")
    raise_at(lab, NOW - timedelta(days=8), severity="medium", kind="ai_watch")
    raise_at(lab, NOW - timedelta(days=6), severity="medium", kind="gap")
    raise_at(lab, NOW - timedelta(days=31), kind="schedule")
    raise_at(lab, NOW - timedelta(days=29), kind="schedule")
    got = numbers(lab)
    assert got.open_by_severity == {"high": 2, "medium": 2, "other": 2} and got.open == 6
    assert got.open_by_kind == {"rule": 2, "schedule": 2, "ai_watch": 1, "gap": 1}
    assert got.overdue_by_severity == {"high": 1, "medium": 1, "other": 1}
    assert got.overdue == 3
    # Open now does not depend on the range; opened does.
    assert numbers(lab, start=NOW - timedelta(days=1)).open == 6
    assert numbers(lab, start=NOW - timedelta(days=1)).opened == 0
    longer = handling(
        lab["meta"], ADMIN, None, START, NOW, NOW, lab["items"].day_of, Thresholds(high=1)
    )
    assert longer.overdue_by_severity["high"] == 2


def test_visibility_follows_the_queue(lab: dict[str, Any]) -> None:
    raise_at(lab, START + timedelta(days=1), sources=["lin_auth"])
    raise_at(lab, START + timedelta(days=1), sources=["win_dc"])
    raise_at(lab, START + timedelta(days=1), kind="schedule", owner_id="u-bob", shared=False)
    raise_at(lab, START + timedelta(days=1), kind="schedule", owner_id="u-ana", shared=False)
    ana = numbers(lab, user=ANA, allowed=["lin_auth"])
    # Her Linux alert and her own private one; Windows only sets the flag; Bob's private
    # alert is not hers to know of, so it neither counts nor flags.
    assert (ana.open, ana.opened, ana.restricted) == (2, 2, True)
    admin = numbers(lab)
    assert (admin.open, admin.restricted) == (4, False)


def test_days_follow_the_install_time_zone(tmp_path: Path) -> None:
    meta, clock = MetaDB(tmp_path / "meta.sqlite"), Clock()
    items = AlertItems(meta, AuditLog(meta), clock=clock, tz="America/Los_Angeles")
    clock.now = datetime(2026, 11, 5, 3, 0, tzinfo=UTC)  # Nov 4, 8 PM in Los Angeles
    items.raise_item("rule", "late", "Late", ref_id="x")
    got = handling(meta, ADMIN, None, START, NOW, NOW, items.day_of, Thresholds())
    assert {d: o for d, o, _ in got.days if o} == {"2026-11-04": 1}
    assert got.days[0][0] == "2026-10-31"  # Nov 1, 00:00 UTC is Oct 31 there


def test_a_grouped_alert_counts_once_however_many_repeats_join_it(lab: dict[str, Any]) -> None:
    lab["clock"].now = START + timedelta(days=1)
    for n in range(4):
        lab["clock"].now += timedelta(minutes=n + 1)
        lab["items"].raise_item(
            "rule", "r", "Repeat", group=("host-1", "r"), change=f"line {n}", severity="high"
        )
    got = numbers(lab)
    assert (got.opened, got.open, got.open_by_severity["high"]) == (1, 1, 1)


@pytest.mark.parametrize("days_back", [1, 19, 21, 60])
def test_restricted_is_the_queues_flag_whatever_the_range(
    lab: dict[str, Any], days_back: int
) -> None:
    # A closed alert in a source Ana cannot read never sets the flag, at any range, so the
    # range cannot date it (D243 counts open alerts only).
    hidden = raise_at(lab, NOW - timedelta(days=20), sources=["win_dc"])
    close_at(lab, hidden, NOW - timedelta(days=20, hours=-1))
    start = NOW - timedelta(days=days_back)
    assert numbers(lab, start=start, user=ANA, allowed=["lin_auth"]).restricted is False
    # An open one sets it, at any range.
    raise_at(lab, NOW - timedelta(days=90), sources=["win_dc"])
    assert numbers(lab, start=start, user=ANA, allowed=["lin_auth"]).restricted is True
