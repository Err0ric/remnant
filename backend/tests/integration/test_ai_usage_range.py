"""AI usage reads the day a range starts in from the rollup's whole hours after the start,
and only the rest of the start's hour from events (findings 2026-11, fix D): every number is
the one the old read gives, which read that whole day from events. Compared on a lake where
a difference would show: use and sign-ins at odd minutes in the start's hour, addresses that
need a person from a sign-in before and after the start, people alternating on one address,
both periods (the range and the one before it), a start day with no rollup, a pending one,
a stale one, a source the caller may not see, and an empty range."""

import shutil
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from app.ai.rollup import AiRollup
from app.ai.usage import Usage
from app.engine.duckdb import IDENT_FILE, QueryScope
from app.ingest.writer import LakeWriter
from tests.integration.test_schedules import NOW, _lake_rows, make_lab

PEOPLE = ["alice", "bob", "carol", "dave"]
HOSTS = ["chatgpt.com", "claude.ai", "gemini.google.com", "api.anthropic.com"]


def _one(source: str, template: str, at: datetime, **fields: Any) -> dict[str, Any]:
    (row,) = _lake_rows(source, template, at, 1)
    return {**row, **fields}


def _rows(source: str, days: int) -> list[dict[str, Any]]:
    """Use at odd minutes over `days`, some by name, most by address only, and sign-ins
    on those addresses (people alternate on one) a few minutes apart."""
    out = []
    for h in range(days * 24):
        base = NOW - timedelta(hours=h)
        for k, minute in enumerate((3, 17, 29, 41, 58)):
            at = base.replace(minute=minute) - timedelta(seconds=7 * k)
            ip = f"10.0.{h % 3}.{5 + k % 3}"
            who = f"{PEOPLE[(h + k) % 4]}@example.com" if k == 4 else None
            out.append(_one(
                source, "dns_bind", at, dst_endpoint_hostname=HOSTS[(h + k) % 4],
                src_endpoint_ip=ip, actor_user_name=who,
            ))  # fmt: skip
            if k in (1, 3):  # a sign-in on that address, by one person then another
                out.append(_one(
                    "auth", "linux_sshd", at - timedelta(minutes=2), class_uid=3002,
                    status_id=1, activity_id=1, src_endpoint_ip=ip,
                    actor_user_name=PEOPLE[(h * 3 + k) % 4], device_hostname=f"ws-{k}",
                ))  # fmt: skip
        # An address signed in early in the hour and used late in it, by address only:
        # whether a start between the two sees the person is the old read's to decide.
        lone = f"10.9.{h % 5}.1"
        out.append(_one(
            "auth", "linux_sshd", base.replace(minute=10), class_uid=3002, status_id=1,
            activity_id=1, src_endpoint_ip=lone, actor_user_name=PEOPLE[h % 4],
        ))  # fmt: skip
        out.append(_one(source, "dns_bind", base.replace(minute=50), dst_endpoint_hostname="claude.ai", src_endpoint_ip=lone))  # fmt: skip
    return out


@pytest.fixture(autouse=True)
def _now(pin_now: Callable[[datetime], None]) -> None:
    """The event dates are fixed, so the clock is too: an open end is `NOW`."""
    pin_now(NOW)


@pytest.fixture
def lab(tmp_path: Any) -> Iterator[dict[str, Any]]:
    out = make_lab(tmp_path)
    app = out["app"]
    lake = app.state.engine._lake
    LakeWriter(lake).write(_rows("dns_a", 12) + _rows("dns_b", 9))
    rollup: AiRollup = app.state.ai_rollup
    rollup._clock = lambda: NOW
    for _ in range(20):  # every closed day, with its identities
        if not rollup.run().pending:
            break
    out["rollup"] = rollup
    out["usage"] = Usage(app.state.engine, app.state.ai_catalog, rollup)
    yield out


def _answer(usage: Usage, scope: QueryScope) -> tuple[Any, ...]:
    services, read = usage._all_services(scope)
    shown = sorted(
        (u.service.id, u.events, u.people, u.machines, str(u.first_seen), str(u.last_seen),
         tuple(u.top_people), tuple(u.top_machines))
        for u in services
    )  # fmt: skip
    net = sorted(
        (n.who, tuple(n.services), n.lookups, n.devices, n.last_seen, n.machine)
        for n in usage.claude_network_people(scope)
    )  # fmt: skip
    return shown, net, sorted(read)


def _both(lab: dict[str, Any], scope: QueryScope, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any]:  # fmt: skip
    usage: Usage = lab["usage"]
    new = _answer(usage, scope)
    with monkeypatch.context() as m:
        m.setattr(AiRollup, "head", lambda self, scope: [])  # the old read: the day from events
        old = _answer(usage, scope)
    return new, old


def _zone(hours: int, minutes: int = 0) -> timezone:
    sign = -1 if hours < 0 else 1
    return timezone(sign * timedelta(hours=abs(hours), minutes=minutes))


# (how long before NOW, the zone the start is written in): the page may send any offset.
STARTS = [
    (timedelta(days=7, minutes=-23), UTC),  # 12:23
    (timedelta(days=7, minutes=1), UTC),  # 11:59
    (timedelta(days=6, hours=11, minutes=59), UTC),  # 00:01
    (timedelta(days=5, hours=-11, minutes=-58), UTC),  # 23:58
    (timedelta(days=8, hours=-3, minutes=-17), UTC),  # 15:17
    (timedelta(days=3, minutes=-30), UTC),  # half past, a range of 3 days
    (timedelta(days=7, minutes=37), _zone(5, 30)),  # 11:23 UTC, 16:53 here
    (timedelta(days=7, minutes=30), _zone(5, 30)),  # 11:30 UTC, 17:00 here: on its hour, not UTC's
    (timedelta(days=6, minutes=-15), _zone(5, 45)),  # 12:15 UTC, 18:00 here
    (timedelta(days=6, hours=-1, minutes=-30), _zone(-3, 30)),  # 13:30 UTC, 10:00 here
    (timedelta(days=5, minutes=-21), _zone(2)),  # 12:21 UTC, a whole-hour zone
    (timedelta(days=6, hours=8, minutes=40), _zone(-8)),  # 03:20 UTC, 19:20 the day before here
    (timedelta(days=5, hours=13, minutes=10), _zone(9)),  # 22:50 UTC, 07:50 the next day here
]


def _truth(lab: dict[str, Any], scope: QueryScope) -> tuple[Any, ...]:
    """The answer from events alone, with no rollup."""
    return _answer(Usage(lab["app"].state.engine, lab["app"].state.ai_catalog, None), scope)


@pytest.mark.parametrize(("back", "zone"), STARTS)
def test_both_periods_are_the_old_answer(
    lab: dict[str, Any], monkeypatch: pytest.MonkeyPatch, back: timedelta, zone: timezone
) -> None:
    start = (NOW - back).astimezone(zone)
    earlier = start - (NOW - start)
    for scope in (
        QueryScope(None, start, None),  # the range, as the page asks it
        QueryScope(None, earlier, start - timedelta(microseconds=1)),  # the period before
        QueryScope(["dns_a", "auth"], start, None),  # dns_b hidden from the caller
    ):
        new, old = _both(lab, scope, monkeypatch)
        assert new == old
        # People come from sign-ins too, so the identities are part of what is compared.
        assert any(row[2] > 0 for row in new[0]) and new[1]
        # And a range as the page asks it counts all of its use: the counts events alone
        # give, whatever zone the start is written in. (The period before ends inside an
        # hour, which the rollup keeps whole, before this change as after it: not compared.)
        if scope.end is None:
            events = {r[0]: r[1] for r in _truth(lab, scope)[0]}
            assert {r[0]: r[1] for r in new[0]} == events, scope
    # The head was really used, unless the start is on a UTC hour.
    utc = start.astimezone(UTC)
    assert bool(lab["rollup"].head(QueryScope(None, start, NOW))) is (utc.minute != 0)


def test_a_start_day_not_ready_in_the_rollup_is_read_from_events(
    lab: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    rollup: AiRollup = lab["rollup"]
    start = NOW - timedelta(days=6, minutes=-37)
    day = start.date().isoformat()
    # dns_a: identities pending (no file yet); dns_b: no rollup day at all; auth: stale.
    (rollup._dir / "source=dns_a" / f"day={day}" / IDENT_FILE).unlink()
    shutil.rmtree(rollup._dir / "source=dns_b" / f"day={day}")
    built = rollup._dir / "source=auth" / f"day={day}" / "_built.json"
    built.write_text(built.read_text().replace('"catalog": "', '"catalog": "x'))
    assert rollup.head(QueryScope(None, start, NOW)) == []
    new, old = _both(lab, QueryScope(None, start, None), monkeypatch)
    assert new == old


def test_on_the_hour_today_and_empty_ranges_are_unchanged(
    lab: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    rollup: AiRollup = lab["rollup"]
    on_hour = NOW - timedelta(days=4)
    assert rollup.head(QueryScope(None, on_hour, NOW)) == []  # already whole hours
    today = NOW - timedelta(minutes=42)
    assert rollup.head(QueryScope(None, today, NOW)) == []
    for scope in (
        QueryScope(None, on_hour, None),
        QueryScope(None, today, None),
        QueryScope(None, NOW - timedelta(days=40, minutes=13), NOW - timedelta(days=30)),
    ):
        new, old = _both(lab, scope, monkeypatch)
        assert new == old


@pytest.mark.parametrize("minutes", [0, 23, 37])
def test_the_inventory_is_the_old_answer(
    lab: dict[str, Any], monkeypatch: pytest.MonkeyPatch, minutes: int
) -> None:
    """The AI inventory asks AI usage's question (`all_services`, the last N days to the
    minute), so it reads the start day the same new way and must give the same items."""
    from app.ai.inventory import inventory

    app = lab["app"]
    now = NOW - timedelta(minutes=minutes)

    def items() -> list[Any]:
        found, read = inventory(
            app.state.engine, lab["usage"], app.state.ai_catalog, None, None, {}, now, 7
        )
        return [sorted(map(repr, found)), sorted(read)]

    new = items()
    with monkeypatch.context() as m:
        m.setattr(AiRollup, "head", lambda self, scope: [])
        old = items()
    assert new == old and new[0]
    # A start inside a UTC hour reads the start day from the rollup's later hours.
    start = (now - timedelta(days=7)).replace(second=0, microsecond=0)
    assert bool(lab["rollup"].head(QueryScope(None, start, now))) is (minutes != 0)


@pytest.mark.parametrize(("back", "zone"), STARTS)
def test_the_people_ranking_reads_unreviewed_use_the_same_way(
    lab: dict[str, Any], monkeypatch: pytest.MonkeyPatch, back: timedelta, zone: timezone
) -> None:
    """People & devices (owner, 2026-11-17): who used an unreviewed AI service is read from
    the rollup's whole hours of the start's day too, with the answer the old read gives."""
    usage: Usage = lab["usage"]
    engine = lab["app"].state.engine
    start = (NOW - back).astimezone(zone)
    heads: list[Any] = []
    run = engine.run

    def spy(*a: Any, **k: Any) -> Any:
        if k.get("name") == "ai_use.unreviewed_people":
            heads.append(k.get("head"))
        return run(*a, **k)

    for scope in (QueryScope(None, start, None), QueryScope(["dns_a", "auth"], start, None)):
        with monkeypatch.context() as m:
            m.setattr(engine, "run", spy)
            new = sorted(usage.unreviewed_use(scope), key=str)
        with monkeypatch.context() as m:
            m.setattr(AiRollup, "head", lambda self, scope: [])  # the old read
            old = sorted(usage.unreviewed_use(scope), key=str)
        assert new == old and any(who for who, _ in new)
    # The head was really used, unless the start is on a UTC hour.
    assert any(h is not None for h in heads) is (start.astimezone(UTC).minute != 0)
