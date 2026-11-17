"""The "What was counted" line under an Ask answer without event ids (fix list 2026-11-16
item 21): written by code from the run's own facts and the library entry's words."""

from datetime import UTC, datetime, timedelta

from app.search.ask_summary import counted_line, window_words

END = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
WORDS = ("events", "AI service", "AI services")


def test_a_library_entry_names_what_it_counted() -> None:
    """The headline and the table give the count; the line does not repeat it."""
    line = counted_line(["service", "events"], 4, 3, "for the last 24 hours", WORDS)
    assert line == (
        "Read 3 sources for the last 24 hours and counted events, grouped by AI service."
    )
    assert counted_line(["service"], 1, 1, "for today", WORDS) == (
        "Read 1 source for today and counted events, grouped by AI service."
    )


def test_with_no_rows_it_is_the_one_line() -> None:
    assert counted_line(["service"], 0, 8, "for the last 24 hours", WORDS) == (
        "Read 8 sources for the last 24 hours: no AI services."
    )
    assert counted_line(["n"], 0, 2, "for today", None) == "Read 2 sources for today: no rows."


def test_without_words_it_says_what_was_read() -> None:
    assert counted_line(["n"], 12, 2, "for the last 7 days", None) == (
        "Read 2 sources for the last 7 days."
    )


def test_rows_with_event_ids_have_no_line() -> None:
    assert counted_line(["event_id", "time"], 3, 1, "for today", WORDS) is None


def test_the_window_in_words() -> None:
    day = END - timedelta(hours=24, seconds=20)
    assert window_words(day, END, True, None, "UTC") == "for the last 24 hours"
    assert window_words(day, END, False, None, "UTC") == (
        "from Oct 19, 11:59 AM UTC to Oct 20, 12:00 PM UTC"
    )
    assert window_words(day, END, True, "today", "UTC") == "for today"
    assert window_words(day, END, True, "since Monday", "UTC") == "since Monday"
