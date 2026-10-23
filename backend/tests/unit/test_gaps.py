"""F55: a source that stops sending for hours is called out, with or without history."""

from datetime import UTC, datetime, timedelta

from app.search.gaps import find_gaps

START = datetime(2026, 10, 22, 0, tzinfo=UTC)
HOURS = [START + timedelta(hours=i) for i in range(24)]


def test_five_empty_hours_while_others_flow_is_one_gap() -> None:
    """The F55 case: paloalto_fw sent nothing 09:00 to 14:00 UTC."""
    counts = [40] * 24
    counts[9:14] = [0] * 5
    (gap,) = find_gaps(counts, HOURS, others=[100] * 24)
    assert (gap.start, gap.end, gap.hours) == (
        "2026-10-22T09:00:00+00:00",
        "2026-10-22T14:00:00+00:00",
        5,
    )
    assert gap.others_flowing and not gap.ongoing


def test_silence_until_now_is_ongoing() -> None:
    counts = [40] * 20 + [0, 0, 0, 0]
    (gap,) = find_gaps(counts, HOURS, others=[0] * 24)
    assert gap.ongoing and gap.end is None and gap.hours == 4
    assert not gap.others_flowing  # nothing else flowed either: say only the gap


def test_one_empty_hour_and_bursty_sources_are_not_gaps() -> None:
    one = [40] * 24
    one[5] = 0
    assert find_gaps(one, HOURS) == []
    bursty = [0, 0, 5, 0, 0, 0, 3, 0, 0, 0, 0, 9] * 2  # sends in a third of hours
    assert find_gaps(bursty, HOURS) == []


def test_the_current_hour_alone_is_never_a_gap() -> None:
    counts = [40] * 23 + [0]
    assert find_gaps(counts, HOURS) == []


def test_a_new_source_with_little_history_is_not_judged() -> None:
    counts = [0] * 18 + [10, 10, 10, 0, 0, 5]
    assert find_gaps(counts, HOURS) == []
