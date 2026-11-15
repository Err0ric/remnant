"""One source state for Health and the Dashboard footer (handoff item 4)."""

from typing import Any

import pytest

from app.search.source_state import SourceInput, assess, condition, idle


def src(source_id: str, **kw: Any) -> SourceInput:
    base: dict[str, Any] = {
        "state": "reading",
        "last_event_at": "2026-11-09T11:59:00+00:00",
        "total_24h": 100,
    }
    return SourceInput(source_id, **(base | kw))


def six() -> list[SourceInput]:
    return [
        src("lin_auth"),
        src("fw_main", last_event_at="2026-11-09T11:00:00+00:00"),
        src("dns", last_event_at="2026-11-09T11:58:00+00:00"),
        src("proxy"),
        # Quiet: nothing in 24 hours (no watch), and a firing quiet watch.
        src("win_dc", last_event_at="2026-11-07T12:00:00+00:00", total_24h=0),
        src("vpn", last_event_at="2026-11-09T06:00:00+00:00", quiet_since="2026-11-09T08:00:00"),
    ]


def test_six_sources_two_quiet_is_four_of_six_healthy() -> None:
    conditions, summary = assess(six())
    assert summary.total == 6 and summary.healthy == 4
    assert [q.source_id for q in summary.quiet] == ["win_dc", "vpn"]  # longest quiet first
    assert conditions["win_dc"] == conditions["vpn"] == "quiet"
    # The longest wait is over the sources that are not quiet.
    assert summary.longest_wait is not None
    assert summary.longest_wait.source_id == "fw_main"


def test_refusal_only_source_quiet_for_six_days_is_neither_quiet_nor_the_longest_wait() -> None:
    # Six sources: two quiet, and server_events with nothing refused for 6 days.
    sources = [
        *[s for s in six() if s.source_id != "proxy"],
        src(
            "server_events",
            last_event_at="2026-11-03T12:00:00+00:00",
            total_24h=0,
            quiet_expected=True,
            gap_alert="g1",
        ),
    ]
    conditions, summary = assess(sources)
    assert conditions["server_events"] == "healthy"
    assert summary.total == 6 and summary.healthy == 4
    assert [q.source_id for q in summary.quiet] == ["win_dc", "vpn"]
    assert summary.longest_wait is not None
    assert summary.longest_wait.source_id == "fw_main"


def test_errors_reading_problems_gaps_and_paused() -> None:
    conditions, summary = assess(
        [
            src("a", state="error"),
            src("b", reading_issue=True),
            src("c", gaps=2),
            src("d", state="disabled"),
            src("e", state="waiting", total_24h=0, last_event_at=None),
            src("f", quiet_expected=True, state="error"),
        ]
    )
    assert conditions == {
        "a": "error",
        "b": "attention",
        "c": "gap",
        "d": "paused",
        "e": "attention",
        "f": "error",
    }
    assert summary.total == 6 and summary.healthy == 0  # paused: in the total, never healthy
    assert summary.gaps == 2 and summary.quiet == []


def test_an_ongoing_gap_or_open_gap_alert_is_quiet() -> None:
    conditions, summary = assess([src("a", ongoing_gap=True, gaps=1), src("b", gap_alert="g")])
    assert conditions == {"a": "quiet", "b": "quiet"}
    assert summary.gaps == 0  # the quiet line says so; not counted twice


# --- Quiet is normal for up to N days (D260, owner 2026-11-14) -------------------------------
# `quiet_ok`: an admin marked this push source and it last received an event inside that
# period. The server computes it (app.search.overview); here it is given.

QUIET_OK_CASES = [
    # (case, overrides, condition, idle)
    ("unmarked, silent a day", {"total_24h": 0}, "quiet", False),
    ("unmarked, ongoing gap", {"ongoing_gap": True, "gaps": 1}, "quiet", False),
    ("unmarked, a gap that ended", {"gaps": 1}, "gap", False),
    ("marked, silent a day", {"total_24h": 0, "quiet_ok": True}, "healthy", True),
    ("marked, ongoing gap", {"ongoing_gap": True, "gaps": 1, "quiet_ok": True}, "healthy", True),
    ("marked, a gap that ended", {"gaps": 1, "quiet_ok": True}, "healthy", False),
    ("marked, sending", {"quiet_ok": True}, "healthy", False),
    # Past the period the server sends quiet_ok false: quiet as before.
    ("marked, silent longer than its days", {"total_24h": 0}, "quiet", False),
    ("marked, never sent", {"total_24h": 0, "last_event_at": None}, "quiet", False),
    ("marked, in error", {"total_24h": 0, "quiet_ok": True, "state": "error"}, "error", False),
    # A listener that is down or a full spool is an ingest error: still raised.
    ("marked, receiver down", {"quiet_ok": True, "state": "error", "total_24h": 0}, "error", False),
    ("marked, not read yet", {"quiet_ok": True, "state": "waiting"}, "attention", False),
    ("marked, records refused", {"quiet_ok": True, "records_skipped": 3}, "attention", False),
    ("marked, reading problem", {"quiet_ok": True, "reading_issue": True}, "attention", False),
    # An alert someone set up still counts: the quiet alert or an open gap alert.
    ("marked, quiet alert firing", {"quiet_ok": True, "quiet_since": "x"}, "quiet", False),
    ("marked, open gap alert", {"quiet_ok": True, "gap_alert": "g"}, "quiet", False),
    ("marked, paused", {"quiet_ok": True, "state": "disabled"}, "paused", False),
]


@pytest.mark.parametrize(
    ("overrides", "expected", "idle_now"),
    [c[1:] for c in QUIET_OK_CASES],
    ids=[c[0] for c in QUIET_OK_CASES],
)
def test_quiet_is_normal_for_a_marked_source_inside_its_period(
    overrides: dict[str, Any], expected: str, idle_now: bool
) -> None:
    s = src("claude_hooks", **overrides)
    assert condition(s) == expected
    assert idle(s, condition(s)) is idle_now


def test_an_idle_source_counts_as_healthy_and_is_neither_quiet_nor_the_longest_wait() -> None:
    sources = [
        *six(),
        src("claude_hooks", last_event_at="2026-11-07T09:00:00+00:00", total_24h=0, quiet_ok=True),
        src("claude_code_otel", last_event_at="2026-11-01T09:00:00+00:00", total_24h=0),
    ]
    conditions, summary = assess(sources)
    assert conditions["claude_hooks"] == "healthy"
    assert conditions["claude_code_otel"] == "quiet"  # past its days: quiet as before
    assert summary.total == 8 and summary.healthy == 5
    assert summary.idle == 1
    assert [q.source_id for q in summary.quiet] == ["claude_code_otel", "win_dc", "vpn"]
    assert summary.longest_wait is not None
    assert summary.longest_wait.source_id == "fw_main"


def test_the_gaps_of_an_idle_source_are_not_counted() -> None:
    _, summary = assess([src("a", gaps=2), src("b", gaps=3, quiet_ok=True)])
    assert summary.gaps == 2 and summary.idle == 0  # b sent in the last hours: not idle


def test_the_quiet_list_counts_from_the_newest_dated_event() -> None:
    # Old events delivered just now (a queue, an import): quiet for 2 days, not a minute.
    _, summary = assess(
        [
            src(
                "otel_collector",
                total_24h=0,
                last_event_at="2026-11-09T11:59:00+00:00",
                newest_event_at="2026-11-07T12:00:00+00:00",
            )
        ]
    )
    assert [(q.source_id, q.last_event_at) for q in summary.quiet] == [
        ("otel_collector", "2026-11-07T12:00:00+00:00")
    ]
