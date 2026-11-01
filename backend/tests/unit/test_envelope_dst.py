"""Local-time syslog around daylight saving changes (owner, 2026-11-01). On 2026-11-01 in
America/Los_Angeles, 01:00 to 01:59 happened twice (PDT, UTC-7, then PST, UTC-8); on
2026-03-08, 02:00 to 02:59 never happened. A repeated hour is resolved from the receive
time (live) or the source's previous event (backfill) and flagged; a skipped hour is read
with the offset before the change and flagged."""

from datetime import UTC, datetime

from app.ingest.envelope import EnvelopeParser, SyslogEnvelopeConfig

LA = SyslogEnvelopeConfig(timezone="America/Los_Angeles")


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)  # type: ignore[misc]  # positional datetime parts


def at(now: datetime) -> EnvelopeParser:
    return EnvelopeParser(LA, clock=lambda: now)


def test_live_in_the_first_pass_reads_pdt() -> None:
    env = at(utc(2026, 11, 1, 8, 16)).parse("Nov  1 01:15:00 fw01 app: first")
    assert env.timestamp == utc(2026, 11, 1, 8, 15)  # 01:15 PDT
    assert "ambiguous_local_time" in env.errors


def test_live_in_the_second_pass_reads_pst() -> None:
    env = at(utc(2026, 11, 1, 9, 16)).parse("Nov  1 01:15:00 fw01 app: second")
    assert env.timestamp == utc(2026, 11, 1, 9, 15)  # 01:15 PST
    assert "ambiguous_local_time" in env.errors


def test_a_late_arrival_never_lands_in_the_future() -> None:
    # Written 01:55 PDT, delivered 01:05 PST: the PST reading (09:55 UTC) is still ahead.
    env = at(utc(2026, 11, 1, 9, 5)).parse("Nov  1 01:55:00 fw01 app: queued")
    assert env.timestamp == utc(2026, 11, 1, 8, 55)


def test_a_backfill_follows_the_previous_event() -> None:
    p = at(utc(2026, 11, 3, 12))  # read two days later: the receive time cannot decide
    lines = [
        "Nov  1 00:50:00 fw01 app: a",  # PDT, not ambiguous
        "Nov  1 01:10:00 fw01 app: b",  # first pass
        "Nov  1 01:50:00 fw01 app: c",
        "Nov  1 01:05:00 fw01 app: d",  # the clock went back: second pass
        "Nov  1 01:40:00 fw01 app: e",
        "Nov  1 02:00:00 fw01 app: f",  # PST, not ambiguous
    ]
    got = [p.parse(line) for line in lines]
    assert [e.timestamp for e in got] == [
        utc(2026, 11, 1, 7, 50),
        utc(2026, 11, 1, 8, 10),
        utc(2026, 11, 1, 8, 50),
        utc(2026, 11, 1, 9, 5),
        utc(2026, 11, 1, 9, 40),
        utc(2026, 11, 1, 10, 0),
    ]
    flagged = ["ambiguous_local_time" in e.errors for e in got]
    assert flagged == [False, True, True, True, True, False]
    stamps = [e.timestamp for e in got]
    assert stamps == sorted(stamps) and len(set(stamps)) == 6  # in order, none on another


def test_the_skipped_spring_hour_is_flagged_and_read_before_the_change() -> None:
    env = at(utc(2026, 3, 8, 11)).parse("Mar  8 02:30:00 fw01 app: never")
    assert env.timestamp == utc(2026, 3, 8, 10, 30)  # 02:30 PST = 03:30 PDT
    assert "nonexistent_local_time" in env.errors
    before = at(utc(2026, 3, 8, 11)).parse("Mar  8 01:59:00 fw01 app: x")
    after = at(utc(2026, 3, 8, 11)).parse("Mar  8 03:00:00 fw01 app: y")
    assert before.timestamp == utc(2026, 3, 8, 9, 59) and not before.errors
    assert after.timestamp == utc(2026, 3, 8, 10, 0) and not after.errors


def test_rfc3339_without_a_zone_is_resolved_the_same_way() -> None:
    env = at(utc(2026, 11, 1, 9, 16)).parse("2026-11-01T01:15:00 fw01 app: x")
    assert env.timestamp == utc(2026, 11, 1, 9, 15)
    assert "ambiguous_local_time" in env.errors


def test_utc_sources_are_never_flagged() -> None:
    p = EnvelopeParser(SyslogEnvelopeConfig(), clock=lambda: utc(2026, 11, 1, 9, 16))
    env = p.parse("Nov  1 01:15:00 fw01 app: x")
    assert env.timestamp == utc(2026, 11, 1, 1, 15) and not env.errors


def test_a_template_keeps_parse_status_ok_and_notes_the_hour() -> None:
    """The notes find events; they are not parse faults (a header in the repeated hour
    once turned every Palo Alto line partial for an hour)."""
    from app.ingest.records import DecodedLine
    from app.templates.loader import load_dir
    from app.templates.registry import STARTER_DIR
    from app.templates.runtime import TemplateNormalizer
    from app.templates.tables import load_tables

    tables, _ = load_tables(STARTER_DIR / "maps")
    templates, _ = load_dir(STARTER_DIR, tables)
    t = templates["paloalto_system"]
    env = t.envelope.syslog.model_copy(update={"timezone": "America/Los_Angeles"})
    now = utc(2026, 11, 1, 9, 16)
    norm = TemplateNormalizer(t, "fw", envelope=env, clock=lambda: now, tables=tables)
    line = (
        "<14>Nov  1 01:15:00 pa-fw01 1,2026/11/01 01:15:00,012345678901,SYSTEM,general,,"
        '2026/11/01 01:15:00,vsys1,general,,,,general,informational,"x",1,0x0,0,0,0,0,,pa-fw01'
    )
    row = norm.normalize(DecodedLine(text=line, bytes_invalid=False, truncated=False))
    assert row["parse_status"] == "ok"
    assert "ambiguous_local_time" in (row["parse_errors"] or "")
    assert row["time"] == utc(2026, 11, 1, 9, 15)  # the payload's zone-less time, PST
