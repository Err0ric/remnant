"""Envelope parser test matrix (CLAUDE.md section 6, SPEC 3.5)."""

import time
from datetime import UTC, datetime

import pytest

from app.ingest.envelope import EnvelopeParser, SyslogEnvelopeConfig

NOW = datetime(2026, 10, 10, 12, 0, 0, tzinfo=UTC)


def parser(**cfg: object) -> EnvelopeParser:
    return EnvelopeParser(SyslogEnvelopeConfig.model_validate(cfg), clock=lambda: NOW)


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)  # type: ignore[misc]  # positional datetime parts


# --- RFC 3164 ----------------------------------------------------------------------


def test_3164_file_style_without_pri() -> None:
    env = parser().parse(
        "Oct  9 20:41:12 bastion sshd[2231]: Accepted publickey for jordan from 10.20.1.5"
    )
    assert env.rfc == "3164"
    assert env.pri is None
    assert env.timestamp == utc(2026, 10, 9, 20, 41, 12)
    assert (env.hostname, env.app_name, env.procid) == ("bastion", "sshd", "2231")
    assert env.msg == "Accepted publickey for jordan from 10.20.1.5"
    assert env.errors == ()


def test_3164_with_pri() -> None:
    env = parser().parse("<38>Oct  9 20:41:12 bastion sshd[2231]: Failed password")
    assert (env.pri, env.facility, env.severity) == (38, 4, 6)
    assert env.app_name == "sshd"


def test_3164_with_explicit_year() -> None:
    env = parser().parse("<38>Oct  9 2025 20:41:12 bastion sshd: hello")
    assert env.timestamp == utc(2025, 10, 9, 20, 41, 12)
    assert env.msg == "hello"


def test_3164_without_year_rollover_safe() -> None:
    p = EnvelopeParser(
        SyslogEnvelopeConfig(assume_year="rollover_safe"),
        clock=lambda: datetime(2027, 1, 1, 0, 5, tzinfo=UTC),
    )
    env = p.parse("Dec 31 23:59:00 host app: late event")
    assert env.timestamp == utc(2026, 12, 31, 23, 59, 0)


def test_3164_without_year_assume_current() -> None:
    p = EnvelopeParser(
        SyslogEnvelopeConfig(assume_year="current"),
        clock=lambda: datetime(2027, 1, 1, 0, 5, tzinfo=UTC),
    )
    assert p.parse("Dec 31 23:59:00 host app: x").timestamp == utc(2027, 12, 31, 23, 59, 0)


def test_3164_source_timezone_applied() -> None:
    env = parser(timezone="America/Los_Angeles").parse("Oct  9 13:41:12 host app: x")
    assert env.timestamp == utc(2026, 10, 9, 20, 41, 12)


def test_3164_with_rfc3339_timestamp_and_offset() -> None:
    env = parser().parse("<13>2026-10-09T13:41:12.123456-07:00 bastion app[7]: x")
    assert env.rfc == "3164"
    assert env.timestamp == datetime(2026, 10, 9, 20, 41, 12, 123456, tzinfo=UTC)
    assert (env.hostname, env.app_name, env.procid) == ("bastion", "app", "7")


def test_3164_without_hostname() -> None:
    env = parser().parse("Oct  9 20:41:12 sshd[1]: no host here")
    assert env.hostname is None
    assert env.app_name == "sshd"
    assert env.msg == "no host here"


def test_3164_without_tag() -> None:
    env = parser().parse("Oct  9 20:41:12 fw01 kernel message without a tag")
    assert env.hostname == "fw01"
    assert env.app_name is None
    assert env.msg == "kernel message without a tag"


def test_3164_invalid_calendar_date() -> None:
    env = parser().parse("Feb 30 10:00:00 host app: x")
    assert env.timestamp is None
    assert "invalid_timestamp" in env.errors


def test_message_starting_with_a_date_is_not_a_relay() -> None:
    env = parser().parse("Oct  9 20:41:12 host app: Oct 9 maintenance window starts")
    assert env.relay_hops == 0
    assert env.msg == "Oct 9 maintenance window starts"


# --- RFC 5424 ----------------------------------------------------------------------


def test_5424_with_structured_data_and_bom() -> None:
    line = (
        "<165>1 2026-10-09T20:41:12.003Z mymachine.example.com evntslog - ID47 "
        '[exampleSDID@32473 iut="3" eventSource="Application" eventID="1011"]'
        '[examplePriority@32473 class="high"] ﻿An application event'
    )
    env = parser().parse(line)
    assert env.rfc == "5424"
    assert (env.facility, env.severity) == (20, 5)
    assert env.timestamp == datetime(2026, 10, 9, 20, 41, 12, 3000, tzinfo=UTC)
    assert (env.hostname, env.app_name, env.procid, env.msgid) == (
        "mymachine.example.com",
        "evntslog",
        None,
        "ID47",
    )
    assert env.structured_data == {
        "exampleSDID@32473": {"iut": "3", "eventSource": "Application", "eventID": "1011"},
        "examplePriority@32473": {"class": "high"},
    }
    assert env.msg == "An application event"


def test_5424_escaped_sd_values() -> None:
    env = parser().parse('<34>1 2026-10-09T20:41:12Z h su - - [a@1 k="x\\"y\\]z\\\\"] msg')
    assert env.structured_data == {"a@1": {"k": 'x"y]z\\'}}
    assert env.msg == "msg"


def test_5424_nil_values_and_empty_message() -> None:
    env = parser().parse("<34>1 2026-10-09T20:41:12+02:00 - - - - -")
    assert env.timestamp == utc(2026, 10, 9, 18, 41, 12)
    assert (env.hostname, env.app_name, env.procid, env.msgid) == (None, None, None, None)
    assert env.structured_data is None
    assert env.msg == ""


def test_5424_nil_timestamp() -> None:
    env = parser().parse("<34>1 - host app 12 - - hi")
    assert env.timestamp is None
    assert env.errors == ()
    assert env.msg == "hi"


def test_5424_unterminated_structured_data() -> None:
    env = parser().parse('<34>1 2026-10-09T20:41:12Z h su - - [a@1 k="cut off')
    assert env.rfc == "5424"
    assert "unterminated_structured_data" in env.errors


# --- relay headers ------------------------------------------------------------------


def test_relay_5424_wrapping_3164() -> None:
    line = (
        "<13>1 2026-10-09T20:41:13Z relay01 rsyslogd - - - "
        "<38>Oct  9 20:41:12 bastion sshd[1]: Accepted publickey"
    )
    env = parser().parse(line)
    assert env.relay_hops == 1
    assert (env.hostname, env.app_name, env.pri) == ("bastion", "sshd", 38)
    assert env.timestamp == utc(2026, 10, 9, 20, 41, 12)
    assert env.msg == "Accepted publickey"


def test_relay_3164_without_pri() -> None:
    env = parser().parse("Oct  9 20:41:13 relay01 Oct  9 20:41:12 bastion sshd[1]: x")
    assert env.relay_hops == 1
    assert env.hostname == "bastion"


def test_relay_hops_capped_at_three() -> None:
    inner = "<38>Oct  9 20:41:12 origin sshd[1]: deep"
    line = inner
    for i in range(5):
        line = f"<13>Oct  9 20:41:1{i} relay{i} {line}"
    env = parser().parse(line)
    assert env.relay_hops == 3
    assert "relay_hops_capped" in env.errors


def test_relay_stripping_can_be_disabled() -> None:
    env = parser(strip_relay_headers=False).parse(
        "<13>Oct  9 20:41:13 relay01 <38>Oct  9 20:41:12 bastion sshd[1]: x"
    )
    assert env.relay_hops == 0
    assert env.hostname == "relay01"


# --- headerless and malformed -------------------------------------------------------


def test_headerless_line() -> None:
    env = parser().parse('{"EventID": 4624, "Computer": "WS01"}')
    assert env.rfc == "none"
    assert env.msg == '{"EventID": 4624, "Computer": "WS01"}'
    assert env.timestamp is None


def test_pri_without_header_keeps_priority_and_message() -> None:
    env = parser().parse('<189>date=2026-10-09 time=20:41:12 devname="FGT60F"')
    assert env.rfc == "3164" and env.pri == 189 and env.severity == 5
    assert env.msg == 'date=2026-10-09 time=20:41:12 devname="FGT60F"'
    assert env.timestamp is None and env.hostname is None
    assert "no_header" in env.errors


def test_invalid_pri_flagged_but_header_parsed() -> None:
    env = parser().parse("<999>Oct  9 20:41:12 host app: x")
    assert env.pri is None
    assert "invalid_pri" in env.errors
    assert env.hostname == "host"


def test_forced_rfc_5424_rejects_3164() -> None:
    env = parser(rfc="5424").parse("Oct  9 20:41:12 host app: x")
    assert env.rfc == "none"
    assert "not_rfc5424" in env.errors


def test_envelope_json_shape() -> None:
    env = parser().parse("<38>Oct  9 20:41:12 bastion sshd[2231]: x")
    assert env.to_column() == {
        "rfc": "3164",
        "pri": 38,
        "facility": 4,
        "severity": 6,
        "hostname": "bastion",
        "app_name": "sshd",
        "procid": "2231",
        "msgid": None,
        "structured_data": None,
        "relay_hops": 0,
    }


# --- pathological input (T14) -------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "<" + "1" * 10_000,
        "<13>1 2026-10-09T20:41:12Z h a - - " + "[" * 10_000,
        "<13>1 2026-10-09T20:41:12Z h a - - [x " + 'k="' * 5_000,
        "Oct  9 20:41:12 " + "a" * 10_000,
        "Oct  9 20:41:12 h " + "[" * 10_000 + ":",
        "\x00\x01\x02" * 4_000,
    ],
)
def test_pathological_lines_are_fast_and_safe(line: str) -> None:
    start = time.perf_counter()
    env = parser().parse(line)
    assert time.perf_counter() - start < 0.25
    assert isinstance(env.msg, str)


def test_fractional_seconds_in_a_bsd_timestamp() -> None:
    env = parser().parse("<189>Oct  9 20:41:12.123 rtr01 sshd[1]: x")
    assert env.timestamp is not None and env.timestamp.microsecond == 123000
    assert env.hostname == "rtr01"


def test_cisco_service_timestamp_inside_a_message_is_not_a_relay_header() -> None:
    env = parser().parse(
        "<188>Oct  9 20:42:00 rtr01 45: Oct  9 20:42:00.456 UTC: %SEC_LOGIN-4-LOGIN_FAILED: x"
    )
    assert env.relay_hops == 0 and env.hostname == "rtr01"
    assert env.msg.startswith("Oct  9 20:42:00.456 UTC: %SEC_LOGIN")


def test_cisco_asa_timestamp_colon_and_device_id_forms() -> None:
    a = parser().parse("<166>Oct 09 2026 20:41:12: %ASA-6-302013: Built")
    assert a.hostname is None and a.app_name == "%ASA-6-302013" and a.msg == "Built"
    b = parser().parse("<164>Oct  9 2026 20:42:00 asa01 : %ASA-4-106023: Deny")
    assert b.hostname == "asa01" and b.app_name == "%ASA-4-106023"
