"""Palo Alto event time: the offset-bearing timestamp wins; zone-less times use the source's
time zone (trial finding: a Pacific firewall's events landed 7 hours early)."""

from datetime import UTC, datetime

import pytest

from app.ingest.envelope import SyslogEnvelopeConfig
from app.ingest.records import DecodedLine
from app.templates.loader import load_dir
from app.templates.registry import STARTER_DIR
from app.templates.runtime import TemplateNormalizer
from app.templates.tables import load_tables

pytestmark = pytest.mark.templates
TABLES, _ = load_tables(STARTER_DIR / "maps")
TEMPLATES, _ = load_dir(STARTER_DIR, TABLES)
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def system_line(generated: str, hires: str = "") -> str:
    tail = f",,,{hires}" if hires else ""
    return (
        f"<14>Nov  1 01:30:00 pa-fw01 1,{generated},012345678901,SYSTEM,general,,{generated},"
        f'vsys1,general,,,,general,informational,"Something happened",1,0x0,0,0,0,0,,pa-fw01{tail}'
    )


def event_time(line: str, zone: str, template: str = "paloalto_system") -> datetime:
    t = TEMPLATES[template]
    env = t.envelope.syslog.model_copy(update={"timezone": zone})
    norm = TemplateNormalizer(t, "fw", envelope=env, clock=lambda: NOW, tables=TABLES)
    row = norm.normalize(DecodedLine(text=line, bytes_invalid=False, truncated=False))
    assert row["parse_status"] == "ok", row["parse_errors"]
    value: datetime = row["time"]
    return value


@pytest.mark.parametrize("zone", ["UTC", "America/Los_Angeles", "Asia/Kolkata"])
def test_the_high_resolution_timestamp_wins_whatever_the_source_zone(zone: str) -> None:
    line = system_line("2026/10/21 23:04:36", "2026-10-21T23:04:36.123-07:00")
    assert event_time(line, zone) == datetime(2026, 10, 22, 6, 4, 36, 123000, tzinfo=UTC)


def test_a_half_hour_offset_is_exact() -> None:
    line = system_line("2026/10/22 11:34:36", "2026-10-22T11:34:36.000+05:30")
    assert event_time(line, "UTC") == datetime(2026, 10, 22, 6, 4, 36, tzinfo=UTC)


@pytest.mark.parametrize(
    ("zone", "expected"),
    [
        ("UTC", datetime(2026, 10, 21, 23, 4, 36, tzinfo=UTC)),
        ("America/Los_Angeles", datetime(2026, 10, 22, 6, 4, 36, tzinfo=UTC)),
        ("Asia/Kolkata", datetime(2026, 10, 21, 17, 34, 36, tzinfo=UTC)),
    ],
)
def test_without_it_generated_time_is_read_in_the_source_zone(
    zone: str, expected: datetime
) -> None:
    assert event_time(system_line("2026/10/21 23:04:36"), zone) == expected


def test_pan_os_9_placeholder_is_ignored() -> None:
    line = system_line("2026/10/21 23:04:36", "1969-12-31T16:00:00.000-08:00")
    assert event_time(line, "America/Los_Angeles") == datetime(2026, 10, 22, 6, 4, 36, tzinfo=UTC)


def test_daylight_saving_end_keeps_the_two_one_thirties_apart() -> None:
    """01:30 happens twice on 2026-11-01 in Los Angeles; only the offset tells them apart."""
    first = system_line("2026/11/01 01:30:00", "2026-11-01T01:30:00.000-07:00")
    second = system_line("2026/11/01 01:30:00", "2026-11-01T01:30:00.000-08:00")
    a, b = event_time(first, "UTC"), event_time(second, "UTC")
    assert (b - a).total_seconds() == 3600
    # Without the offset, an ambiguous local time is read as the first one (daylight time).
    zoneless = event_time(system_line("2026/11/01 01:30:00"), "America/Los_Angeles")
    assert zoneless == datetime(2026, 11, 1, 8, 30, tzinfo=UTC)


def test_daylight_saving_start() -> None:
    line = system_line("2026/03/08 03:15:00", "2026-03-08T03:15:00.000-07:00")
    assert event_time(line, "UTC") == datetime(2026, 3, 8, 10, 15, tzinfo=UTC)
    before = system_line("2026/03/08 01:45:00")
    assert event_time(before, "America/Los_Angeles") == datetime(2026, 3, 8, 9, 45, tzinfo=UTC)


@pytest.mark.parametrize(
    "template", ["paloalto_traffic", "paloalto_threat", "paloalto_userid", "paloalto_globalprotect"]
)
def test_every_pan_template_reads_the_offset(template: str) -> None:
    sample = (
        STARTER_DIR.parent.parent / "backend" / "tests" / "fixtures" / "logs" / template
    ) / "sample.log"
    pacific = sample.read_text().splitlines()[1]  # fixtures: line 2 is a Pacific firewall
    assert "-07:00" in pacific
    assert event_time(pacific, "UTC", template) == event_time(pacific, "Asia/Kolkata", template)


def test_every_starter_template_reads_zoneless_times_in_the_source_zone() -> None:
    """Item 2: the source's zone reaches template transforms, not only syslog headers."""
    for template in TEMPLATES.values():
        env = template.envelope.syslog.model_copy(update={"timezone": "Asia/Kolkata"})
        norm = TemplateNormalizer(template, "x", envelope=env, clock=lambda: NOW, tables=TABLES)
        assert str(norm._tz) == "Asia/Kolkata"
        assert str(norm._transforms._tz) == "Asia/Kolkata"


def test_source_config_carries_its_zone() -> None:
    assert SyslogEnvelopeConfig(timezone="America/Los_Angeles").timezone == "America/Los_Angeles"
