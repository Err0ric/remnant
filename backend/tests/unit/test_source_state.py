"""One source state for Health and the Dashboard footer (handoff item 4)."""

from typing import Any

from app.search.source_state import SourceInput, assess


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
