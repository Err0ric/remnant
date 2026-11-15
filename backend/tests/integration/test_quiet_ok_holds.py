"""Marking a push source "Quiet is normal for up to N days" holds its quiet alert for those
days, then it fires anyway (owner, 2026-11-14; D262, amends D260). The hold is measured from
the source's newest event in the lake, as Health reads it, with the one rule
`inside_quiet_days`, never from when the watch was turned on."""

import json
from datetime import timedelta
from typing import Any

import pytest

from app.ingest.quiet import QuietWatch
from app.ingest.watcher import SourceStatus
from app.ingest.writer import LakeWriter
from tests.integration.test_quiet_sources import actions, lab, tick, watch  # noqa: F401
from tests.integration.test_schedules import NOW, _lake_rows

SID = "otel_collector"
HOUR = 3600.0
DAY = 86400.0


@pytest.fixture
def push(lab: dict[str, Any]) -> dict[str, Any]:  # noqa: F811
    """A collector OTLP source (its default quiet alert replaced by a 1-hour one with a
    target), last received at NOW, and a file source for comparison."""
    res = lab["admin"].post(
        "/api/sources",
        json={"source_id": SID, "format": "json", "kind": "otlp", "sender": "collector"},
        headers=lab["h"],
    )
    assert res.status_code == 201, res.text
    lab["received"][SID] = NOW
    lab["app"].state.overview._clock = lab["clock"]
    lake = lab["app"].state.engine._lake
    LakeWriter(lake).write(_lake_rows(SID, "generic_json", NOW, 1))
    ingest = lab["app"].state.ingest
    with ingest._lock:
        ingest._status[SID] = SourceStatus(last_pass_at=NOW, last_event_at=NOW)
    assert watch(lab, SID).status_code == 200
    assert watch(lab, "lin_auth").status_code == 200
    return lab


def mark(env: dict[str, Any], days: int | None, sid: str = SID) -> Any:
    res = env["admin"].patch(f"/api/sources/{sid}", json={"quiet_ok_days": days}, headers=env["h"])
    assert res.status_code == 200, res.text
    return res


def at(env: dict[str, Any], seconds: float) -> None:
    env["clock"].now = NOW + timedelta(seconds=seconds)


def sent(env: dict[str, Any], sid: str = SID) -> list[dict[str, Any]]:
    """Quiet messages sent to the alert target for this source."""
    docs = [json.loads(body) for _, body in env["rx"].got]
    return [d for d in docs if d["title"] == sid and d["kind"] == "quiet"]


def state(env: dict[str, Any], sid: str = SID) -> str:
    env["app"].state.overview._cache.clear()
    env["app"].state.overview._count_cache.clear()
    rows = env["admin"].get("/api/overview").json()["sources"]
    row = next(r for r in rows if r["source_id"] == sid)
    return str(row["condition"])


def gap_items(env: dict[str, Any], sid: str = SID) -> list[str]:
    with env["app"].state.meta.connect() as con:
        rows = con.execute(
            "SELECT item_id FROM alert_items WHERE kind = 'gap' AND subject = ?", (sid,)
        ).fetchall()
    return [r[0] for r in rows]


def quiet_rows(env: dict[str, Any], sid: str = SID) -> int:
    with env["app"].state.meta.connect() as con:
        rows = con.execute("SELECT detail FROM audit_log WHERE action = 'source.quiet'").fetchall()
    return sum(1 for r in rows if json.loads(r[0])["source_id"] == sid)


# (case, days marked, silence in seconds, the alert fires)
CASES = [
    ("unmarked, shorter than the alert", None, 0.5 * HOUR, False),
    ("unmarked, past the alert", None, 2 * HOUR, True),
    ("marked 7 d, shorter than the alert", 7, 0.5 * HOUR, False),
    ("marked 7 d, between alert and ceiling: held", 7, 2 * DAY, False),
    ("marked 1 d, just inside the ceiling: held", 1, DAY - 60, False),
    ("marked 1 d, past the ceiling: fires", 1, DAY + 60, True),
    ("marked 7 d, past the ceiling: fires", 7, 7 * DAY + 60, True),
]


@pytest.mark.parametrize(
    ("days", "silence", "fires"), [c[1:] for c in CASES], ids=[c[0] for c in CASES]
)
def test_the_quiet_alert_is_held_inside_the_days_and_fires_after(
    push: dict[str, Any], days: int | None, silence: float, fires: bool
) -> None:
    if days:
        mark(push, days)
    at(push, silence)
    tick(push)
    tick(push)  # a second tick never raises it again
    assert len(sent(push)) == (1 if fires else 0)
    assert len(gap_items(push)) == (1 if fires else 0)
    if fires:
        (doc,) = sent(push)
        assert doc["range_start"] == NOW.isoformat()  # the real start of the silence
    elif days and silence > HOUR:
        assert state(push) == "healthy"  # held: Idle on Health, no alert


def test_one_alert_once_the_ceiling_passes_with_the_whole_silence(push: dict[str, Any]) -> None:
    mark(push, 1)
    for hours in (2, 6, 12, 23):
        at(push, hours * HOUR)
        tick(push)
    assert sent(push) == []
    at(push, 25 * HOUR)
    assert tick(push) == 1
    at(push, 26 * HOUR)
    assert tick(push) == 0
    (doc,) = sent(push)
    assert doc["detail"] == "No events received for 1 d 1 h"
    assert doc["range_start"] == NOW.isoformat()
    assert state(push) == "quiet"


def test_a_restart_during_a_hold_neither_loses_nor_repeats_it(push: dict[str, Any]) -> None:
    mark(push, 1)
    at(push, 2 * HOUR)
    tick(push)
    # A restart: ingest status is forgotten and a new watch reads the same table.
    push["received"][SID] = None
    old: QuietWatch = push["app"].state.quiet
    fresh = QuietWatch(
        old._meta,
        received=lambda: dict(push["received"]),
        source_ids=old._source_ids,
        dispatcher=old._dispatcher,
        audit=old._audit,
        link=old._link,
        clock=push["clock"],
        items=old._items,
        quiet_days=old._quiet_days,
        last_event=old._last_event,
    )
    push["app"].state.quiet = fresh
    at(push, 12 * HOUR)
    assert tick(push) == 0  # still held, measured from the newest event in the lake
    at(push, 25 * HOUR)
    assert tick(push) == 1
    at(push, 30 * HOUR)
    assert tick(push) == 0
    assert len(sent(push)) == 1 and sent(push)[0]["range_start"] == NOW.isoformat()


def test_unmarking_during_a_hold_raises_it_on_the_next_check(push: dict[str, Any]) -> None:
    mark(push, 7)
    at(push, 3 * HOUR)
    tick(push)
    assert sent(push) == []
    mark(push, None)
    tick(push)  # the next scheduled check judges it by its own 1-hour threshold
    (doc,) = sent(push)
    assert doc["detail"] == "No events received for 3 h"
    assert state(push) == "quiet"


def test_an_alert_already_firing_stays_until_events_resume(push: dict[str, Any]) -> None:
    at(push, 2 * HOUR)
    tick(push)
    assert len(sent(push)) == 1
    mark(push, 7)
    at(push, 3 * HOUR)
    tick(push)
    assert len(sent(push)) == 1  # not raised again
    assert state(push) == "quiet"  # and not hidden: it closes when events resume
    push["received"][SID] = NOW + timedelta(hours=3, minutes=30)
    at(push, 4 * HOUR)
    assert tick(push) == 1  # resumed
    kinds = [json.loads(b)["kind"] for _, b in push["rx"].got if json.loads(b)["title"] == SID]
    assert kinds == ["quiet", "resumed"]


def test_a_file_source_is_unaffected(push: dict[str, Any]) -> None:
    at(push, 2 * HOUR)
    tick(push)
    assert len(sent(push, "lin_auth")) == 1  # its 1-hour alert fires as before
    assert "source.quiet" in actions(push)


def test_the_hold_writes_no_audit_row_of_its_own(push: dict[str, Any]) -> None:
    mark(push, 7)
    at(push, 2 * DAY)
    tick(push)
    assert quiet_rows(push) == 0  # the setting change is the audited act
    assert quiet_rows(push, "lin_auth") == 1  # an unmarked source's alert is still recorded


def _another(env: dict[str, Any], sid: str, last_event_days_ago: float | None) -> None:
    res = env["admin"].post(
        "/api/sources",
        json={"source_id": sid, "format": "json", "kind": "otlp", "sender": "collector"},
        headers=env["h"],
    )
    assert res.status_code == 201, res.text
    env["received"][sid] = None  # nothing received since this server started
    if last_event_days_ago is not None:
        when = NOW - timedelta(days=last_event_days_ago)
        LakeWriter(env["app"].state.engine._lake).write(_lake_rows(sid, "generic_json", when, 1))
    assert watch(env, sid).status_code == 200  # turned on now: its own clock starts at NOW


def test_a_marked_source_that_never_sent_is_never_held(push: dict[str, Any]) -> None:
    _another(push, "otel_new", None)
    mark(push, 30, "otel_new")
    at(push, 2 * HOUR)
    tick(push)
    (doc,) = sent(push, "otel_new")  # fires at the alert's own 1-hour threshold
    assert doc["detail"] == "No events received for 2 h"


def test_the_hold_counts_from_the_last_real_event_not_from_turning_the_watch_on(
    push: dict[str, Any],
) -> None:
    _another(push, "otel_old", 6)  # silent 6 of its 7 days before the watch was turned on
    mark(push, 7, "otel_old")
    at(push, 2 * HOUR)
    tick(push)
    assert sent(push, "otel_old") == []  # 6 d 2 h since its last event: still inside
    at(push, DAY + 60)
    tick(push)
    (doc,) = sent(push, "otel_old")  # the real silence passed 7 days, not 7 more
    # Said from the real last event, not from when the watch was turned on.
    assert doc["range_start"] == (NOW - timedelta(days=6)).isoformat()
    assert doc["detail"] == "No events received for 7 d"


def test_the_change_answers_without_reading_the_lake(push: dict[str, Any]) -> None:
    reads: list[str] = []

    def read(sid: str, days: int, now: Any) -> None:
        reads.append(sid)

    push["app"].state.quiet._last_event = read
    at(push, 3 * HOUR)  # its alert is due
    res = push["admin"].patch(f"/api/sources/{SID}", json={"quiet_ok_days": 3}, headers=push["h"])
    assert res.status_code == 200, res.text
    assert reads == []  # evaluated by the next scheduled check, not inside the request
    with push["app"].state.meta.connect() as con:
        rows = con.execute(
            "SELECT detail FROM audit_log WHERE action = 'source.quiet_ok_change'"
        ).fetchall()
    assert [json.loads(r[0]) for r in rows] == [{"source_id": SID, "from": None, "to": 3}]


def test_a_failed_read_holds_nothing_and_never_stops_the_other_watches(
    push: dict[str, Any],
) -> None:
    mark(push, 7)

    def broken(sid: str, days: int, now: Any) -> None:
        raise RuntimeError("lake busy")

    push["app"].state.quiet._last_event = broken
    at(push, 2 * HOUR)
    tick(push)
    # The marked source is judged by its own 1-hour threshold (never silent, D236), and
    # lin_auth, unmarked and checked after it, still alerts.
    assert len(sent(push)) == 1
    assert len(sent(push, "lin_auth")) == 1


def test_the_lake_is_read_once_per_quiet_episode(push: dict[str, Any]) -> None:
    mark(push, 7)
    reads: list[str] = []
    real = push["app"].state.quiet._last_event

    def counted(sid: str, days: int, now: Any) -> Any:
        reads.append(sid)
        return real(sid, days, now)

    push["app"].state.quiet._last_event = counted
    for minutes in (30, 70, 80, 90, 100, 110):  # due from 60 min, held throughout
        at(push, minutes * 60)
        tick(push)
    assert reads == [SID] and sent(push) == []
    push["received"][SID] = NOW + timedelta(minutes=115)  # an event arrives: read again later
    at(push, 116 * 60)
    tick(push)
    at(push, 200 * 60)
    tick(push)
    assert reads == [SID, SID]


def test_a_failed_read_later_in_the_same_silence_keeps_the_hold(push: dict[str, Any]) -> None:
    mark(push, 7)
    at(push, 2 * HOUR)
    tick(push)  # read once: held on the real last event
    assert sent(push) == []

    def broken(sid: str, days: int, now: Any) -> None:
        raise RuntimeError("lake busy")

    push["app"].state.quiet._last_event = broken
    for hours in (4, 6, 30):  # past the hour the answer is kept for, the read fails each time
        at(push, hours * HOUR)
        tick(push)
    assert sent(push) == [] and state(push) == "healthy"  # the same silence, still held
    at(push, 8 * DAY)  # and the days still end: it fires, never silent
    tick(push)
    assert len(sent(push)) == 1


def test_old_events_received_now_are_held_and_said_from_their_own_date(
    push: dict[str, Any],
) -> None:
    """A queue delivers events dated 2 days ago, now: the watch saw a record now, Health and
    the hold count from the 2-day-old event, and the alert, when the days pass, says so."""
    from tests.integration.test_quiet_ok import _dated

    sid = "otel_queue"
    _another(push, sid, None)
    _dated(push, sid, timedelta(days=2), timedelta(minutes=1))
    push["received"][sid] = NOW - timedelta(minutes=1)
    mark(push, 7, sid)
    at(push, 2 * HOUR)
    tick(push)
    assert sent(push, sid) == []  # due by its 1-hour alert, held: 2 d 2 h of its 7 days
    at(push, 5 * DAY + 60)
    tick(push)
    (doc,) = sent(push, sid)  # the newest event is now 7 days old
    assert doc["range_start"] == (NOW - timedelta(days=2)).isoformat()  # Logs opens there
    # A record arrived 5 days ago, so the text names both times instead of "received".
    assert doc["detail"] == (
        "No new events for 7 d. Newest event dated 2026-10-08 12:00 UTC;"
        " last data arrived 2026-10-10 11:59 UTC."
    )
    with push["app"].state.meta.connect() as con:  # the alert item on the Alerts page says it too
        (item_detail,) = con.execute(
            "SELECT detail FROM alert_items WHERE kind = 'gap' AND subject = ?", (sid,)
        ).fetchone()
    assert item_detail == doc["detail"]
    (row,) = _quiet_audit(push, sid)
    assert row == {
        "source_id": sid,
        "last_received": (NOW - timedelta(minutes=1)).isoformat(),
        "newest_event": (NOW - timedelta(days=2)).isoformat(),
    }


def _quiet_audit(env: dict[str, Any], sid: str) -> list[dict[str, Any]]:
    with env["app"].state.meta.connect() as con:
        rows = con.execute("SELECT detail FROM audit_log WHERE action = 'source.quiet'").fetchall()
    return [d for d in (json.loads(r[0]) for r in rows) if d["source_id"] == sid]


def test_when_the_newest_event_arrived_on_its_date_the_alert_says_it_the_short_way(
    push: dict[str, Any],
) -> None:
    _another(push, "otel_old", 6)  # dated and received 6 days ago
    mark(push, 7, "otel_old")
    at(push, DAY + 60)
    tick(push)
    (doc,) = sent(push, "otel_old")
    assert doc["detail"] == "No events received for 7 d"
    (row,) = _quiet_audit(push, "otel_old")
    assert row["last_received"] == row["newest_event"] == (NOW - timedelta(days=6)).isoformat()
