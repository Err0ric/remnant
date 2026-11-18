"""ADR-0042 row 8 and C1 (slice 1c): the headline is code, never model text; a model sees
at most 20 rows that carry event ids; statements that cite no sent row are removed."""

from datetime import UTC, datetime

from app.search.ask_summary import (
    ANSWER_ROWS,
    MAX_CHARS,
    check_claims,
    headline,
    removed_note,
    sample,
)

A = "0190a1b2-0000-7000-8000-00000000000a"
B = "0190a1b2-0000-7000-8000-00000000000b"


def test_headline_from_a_template_or_the_first_row() -> None:
    cols = ["address", "failures"]
    rows = [["203.0.113.7", 1204], ["198.51.100.4", 3]]
    t = "{n} addresses with failed SSH logins; most from {first.address} ({first.failures} failures)"
    assert headline(cols, rows, False, t) == (
        "2 addresses with failed SSH logins; most from 203.0.113.7 (1,204 failures)"
    )
    # A template naming a column the result lacks falls back; it never shows a blank.
    assert headline(cols, rows, False, "{first.user} failed") == (
        "2 rows. First row: address 203.0.113.7, failures 1,204."
    )
    assert headline(cols, rows, True) == (
        "More than 2 rows. First row: address 203.0.113.7, failures 1,204."
    )
    assert headline(cols, [], False, t) == "No matching rows in this time range."
    assert headline(["total"], [[42]], False) == "total: 42"


def test_headline_times_read_in_the_askers_zone() -> None:
    """Owner, 2026-11-04: times in Ask read as everywhere else, in the viewer's zone."""
    t = datetime(2026, 10, 21, 16, 5, tzinfo=UTC)
    tpl = "Last used {first.last_seen}"
    assert headline(["last_seen"], [[t]], False, tpl, "America/Los_Angeles") == (
        "Last used Oct 21, 9:05 AM PDT"
    )
    assert headline(["last_seen"], [[t]], False, tpl) == "Last used 2026-10-21 16:05 UTC"
    assert headline(["last_seen"], [[t]], False, tpl, "Not/AZone") == (
        "Last used 2026-10-21 16:05 UTC"
    )


def test_headline_skips_event_ids_and_nulls() -> None:
    at = datetime(2026, 11, 2, 9, 30, tzinfo=UTC)
    got = headline(["event_id", "time", "user", "client"], [[A, at, "dana", None]] * 3, False)
    assert got == "3 rows. First row: time 2026-11-02 09:30 UTC, user dana."


def test_no_event_ids_means_nothing_to_summarize() -> None:
    assert sample(["user", "failures"], [["dana", 3]], False) is None
    assert sample(["event_id", "user"], [[None, "dana"]], False) is None


def test_a_sample_is_small_and_lists_what_may_be_cited() -> None:
    cols = ["user", *[f"c{i}" for i in range(15)], "event_id"]
    rows = [
        [f"u{i}", *(["x" * 1000] * 2), *(["y"] * 13), A.upper() if i == 0 else B] for i in range(50)
    ]
    s = sample(cols, rows, True)
    assert s is not None
    assert s.columns[0] == "event_id" and len(s.columns) == 12
    assert 1 <= len(s.rows) <= ANSWER_ROWS
    assert all(len(v) <= 301 for r in s.rows for v in r[1:] if isinstance(v, str))
    assert sum(len(str(r)) for r in s.rows) < MAX_CHARS * 2
    assert s.event_ids == {A, B}  # stored lowercase
    assert s.row_count == 50 and s.truncated


def test_uncited_and_wrongly_cited_statements_are_removed() -> None:
    sent = frozenset({A, B})
    got = check_claims(
        [
            ("dana failed 3 times", [A.upper()]),
            ("no citation", []),
            ("an id that was not sent", ["0190a1b2-0000-7000-8000-00000000ffff"]),
            ("half right", [B, "0190a1b2-0000-7000-8000-00000000ffff"]),
            ("both", [A, B, A]),
        ],
        sent,
    )
    assert got.claims == [("dana failed 3 times", [A]), ("both", [A, B])]
    assert got.removed == 3
    assert removed_note(3, 2) == "3 statements removed: they cited no events from these rows."
    assert removed_note(1, 1) == "1 statement removed: it cited no events from these rows."
    assert removed_note(2, 0) == "No summary: the model's statements did not cite these rows."
    assert removed_note(0, 2) is None


def test_at_most_five_statements() -> None:
    got = check_claims([(f"s{i}", [A]) for i in range(8)], frozenset({A}))
    assert len(got.claims) == 5 and got.removed == 0


def test_headline_reads_iso_text_times_and_plain_column_names() -> None:
    """Owner, 2026-11-08: the headline showed "time 2026-11-05T20:03:35+00:00,
    actor_user_name frank@example.com": rows can carry times as ISO text."""
    cols = ["event_id", "time", "actor_user_name", "src_endpoint_ip"]
    row = [A, "2026-11-05T20:03:35+00:00", "frank@example.com", "203.0.113.59"]
    got = headline(cols, [row] * 2, False, None, "America/Los_Angeles")
    assert got == (
        "2 rows. First row: time Nov 5, 12:03 PM PST, user frank@example.com,"
        " source IP 203.0.113.59."
    )
    # Text that only looks like a date stays as it is.
    assert headline(["note"], [["2026-11-05 maintenance"]], False) == (
        "note: 2026-11-05 maintenance"
    )


def test_the_summary_gets_ten_rows_and_stats_over_every_row_never_more() -> None:
    """D270: at most ANSWER_ROWS rows plus per-column stats over all kept rows, together
    within the 7,000 characters the 20 rows alone had before."""
    import json

    from app.search.ask_summary import STATS_CHARS

    cols = ["event_id", "time", "user", "bytes", "message", *[f"c{i}" for i in range(10)]]
    rows = [
        [
            f"0190a1b2-0000-7000-8000-{i:012d}",
            datetime(2026, 10, 10, i % 24, tzinfo=UTC),
            ["alice", "bob", "carol"][i % 3],
            i,
            f"message {i} " + "x" * 400,
            *([f"v{i % 7}"] * 10),
        ]
        for i in range(1000)
    ]
    s = sample(cols, rows, True)
    assert s is not None
    assert ANSWER_ROWS == 10 and len(s.rows) <= 10
    assert len(s.event_ids) == len(s.rows)  # only the rows sent may be cited
    assert set(s.stats) == set(s.columns[1:])  # every column but event_id, at most 11
    assert s.stats["user"]["values"] == 1000 and s.stats["user"]["distinct"] == 3
    assert s.stats["user"] == {"values": 1000, "distinct": 3}  # no text values, ever
    assert s.stats["bytes"] == {"values": 1000, "distinct": 1000, "min": 0, "max": 999}
    assert s.stats["time"]["min"].startswith("2026-10-10T00:00")
    assert s.stats["time"]["max"].startswith("2026-10-10T23:00")
    assert set(s.stats["message"]) == {"values", "distinct"}
    assert len(json.dumps(s.rows, default=str)) <= MAX_CHARS + 2_000  # one row may cross
    assert len(json.dumps(s.stats, default=str)) <= STATS_CHARS
