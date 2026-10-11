import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.schema import COLUMN_NAMES
from app.ingest.envelope import SyslogEnvelopeConfig
from app.ingest.normalizer import Normalizer, SourceSpec
from app.ingest.records import DecodedLine

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def norm(fmt: str, **kw: object) -> Normalizer:
    spec = SourceSpec.model_validate({"source_id": "test_src", "format": fmt, **kw})
    return Normalizer(spec, clock=lambda: NOW)


def line(text: str, invalid: bool = False, truncated: bool = False) -> DecodedLine:
    return DecodedLine(text=text, bytes_invalid=invalid, truncated=truncated)


def row(n: Normalizer, text: str, **kw: bool) -> dict[str, object]:
    out = n.normalize(line(text, **kw))
    assert out is not None
    return out


# --- shape ----------------------------------------------------------------------


def test_every_row_has_exactly_the_schema_columns() -> None:
    r = row(norm("syslog"), "<38>Oct  9 20:41:12 bastion sshd[1]: hello")
    assert tuple(r) == COLUMN_NAMES


def test_identity_governance_and_time_observed() -> None:
    r = row(norm("syslog", classification="cloud_allowed", owner_id="u1"), "hello")
    assert uuid.UUID(str(r["event_id"])).version == 7
    assert (r["source_id"], r["classification"], r["owner_id"]) == (
        "test_src",
        "cloud_allowed",
        "u1",
    )
    assert r["time_observed"] == NOW


def test_classification_defaults_to_local_only() -> None:
    assert row(norm("json"), "{}")["classification"] == "local_only"


# --- syslog (generic, envelope only) ---------------------------------------------


def test_syslog_line_maps_envelope_fields() -> None:
    r = row(norm("syslog"), "<38>Oct  9 20:41:12 bastion sshd[2231]: Accepted publickey")
    assert r["template_id"] == "generic_syslog"
    assert r["parse_status"] == "envelope_only"
    assert r["time"] == datetime(2026, 10, 9, 20, 41, 12, tzinfo=UTC)
    assert (r["device_hostname"], r["actor_process_name"], r["actor_process_pid"]) == (
        "bastion",
        "sshd",
        2231,
    )
    assert r["message"] == "Accepted publickey"
    assert r["severity_id"] == 1  # syslog informational
    env = json.loads(str(r["envelope"]))
    assert env["rfc"] == "3164" and env["pri"] == 38


@pytest.mark.parametrize(
    ("pri", "ocsf"), [(8, 5), (10, 5), (11, 4), (12, 3), (13, 2), (14, 1), (15, 1)]
)
def test_syslog_severity_maps_to_ocsf(pri: int, ocsf: int) -> None:
    r = row(norm("syslog"), f"<{pri}>Oct  9 20:41:12 h app: x")
    assert r["severity_id"] == ocsf


def test_raw_is_never_modified() -> None:
    text = "<85>Oct  9 20:41:12 bastion sudo[1]:     alex : TTY=pts/0 ;  "
    assert row(norm("syslog"), text)["raw"] == text


def test_headerless_line_in_syslog_source() -> None:
    r = row(norm("syslog"), "kernel: something without a header")
    assert r["parse_status"] == "envelope_only"
    assert r["parse_errors"] == "no_syslog_header"
    assert r["time"] is None
    assert r["message"] == "kernel: something without a header"


def test_truncated_and_invalid_bytes_flagged() -> None:
    r = row(norm("syslog"), "<38>Oct  9 20:41:12 h app: cut �", truncated=True, invalid=True)
    assert r["parse_status"] == "partial"
    assert "truncated" in str(r["parse_errors"])
    assert r["raw_bytes_invalid"] is True


def test_relay_hops_recorded() -> None:
    r = row(
        norm("syslog"),
        "<13>1 2026-10-09T20:41:13Z relay01 rsyslogd - - - <38>Oct  9 20:41:12 bastion sshd[1]: x",
    )
    assert json.loads(str(r["envelope"]))["relay_hops"] == 1
    assert r["device_hostname"] == "bastion"


def test_syslog_source_timezone_used() -> None:
    n = norm("syslog", envelope=SyslogEnvelopeConfig(timezone="America/Los_Angeles"))
    assert row(n, "Oct  9 13:41:12 h app: x")["time"] == datetime(
        2026, 10, 9, 20, 41, 12, tzinfo=UTC
    )


# --- JSON lines ---------------------------------------------------------------------


def test_json_line_time_message_and_unmapped() -> None:
    text = '{"@timestamp":"2026-10-09T20:41:12.5Z","message":"An account failed to log on","event":{"code":"4625"}}'
    r = row(norm("json"), text)
    assert r["template_id"] == "generic_json"
    assert r["parse_status"] == "ok"
    assert r["time"] == datetime(2026, 10, 9, 20, 41, 12, 500000, tzinfo=UTC)
    assert r["message"] == "An account failed to log on"
    assert json.loads(str(r["unmapped"]))["event"] == {"code": "4625"}
    assert r["envelope"] is None


def test_json_nxlog_style_naive_time_uses_source_timezone() -> None:
    text = '{"EventTime":"2026-10-09 13:41:12","EventID":4624,"Message":"An account was successfully logged on."}'
    n = norm("json", envelope=SyslogEnvelopeConfig(timezone="America/Los_Angeles"))
    r = row(n, text)
    assert r["time"] == datetime(2026, 10, 9, 20, 41, 12, tzinfo=UTC)
    assert r["message"] == "An account was successfully logged on."


def test_json_epoch_millis() -> None:
    r = row(norm("json"), '{"timestamp": 1791578472000, "msg": "x"}')
    assert r["time"] == datetime.fromtimestamp(1791578472, tz=UTC)


@pytest.mark.parametrize("text", ["not json", "[1, 2, 3]", '{"unterminated": '])
def test_json_invalid_is_failed_but_stored(text: str) -> None:
    r = row(norm("json"), text)
    assert r["parse_status"] == "failed"
    assert r["parse_errors"] == "invalid_json"
    assert r["raw"] == text


# --- CSV with header -----------------------------------------------------------------


def test_csv_header_then_rows() -> None:
    n = norm("csv")
    assert n.normalize(line("time,user,action,note")) is None
    r = row(n, '2026-10-09T20:41:12Z,jordan,login,"comma, inside"')
    assert r["template_id"] == "generic_csv"
    assert r["parse_status"] == "ok"
    assert r["time"] == datetime(2026, 10, 9, 20, 41, 12, tzinfo=UTC)
    assert json.loads(str(r["unmapped"])) == {
        "time": "2026-10-09T20:41:12Z",
        "user": "jordan",
        "action": "login",
        "note": "comma, inside",
    }


def test_csv_row_with_wrong_column_count_is_partial() -> None:
    n = norm("csv")
    n.normalize(line("a,b"))
    r = row(n, "1,2,3")
    assert r["parse_status"] == "partial"
    assert r["parse_errors"] == "column_count_mismatch"
    assert json.loads(str(r["unmapped"])) == {"a": "1", "b": "2", "_extra": ["3"]}


def test_csv_tab_delimiter() -> None:
    n = norm("csv", csv_delimiter="\t")
    n.normalize(line("EventTime\tEventID"))
    assert json.loads(str(row(n, "2026-10-09 20:41:12\t4624")["unmapped"]))["EventID"] == "4624"


def test_json_escape_lone_surrogate_does_not_fail_the_lake_write(tmp_path: Path) -> None:
    # Review finding: "\ud800" in a JSON line produced a str the Parquet writer rejected,
    # losing the whole batch.
    from app.ingest.writer import LakeWriter

    n = Normalizer(SourceSpec(source_id="app", format="json"))
    line = '{"message": "a\\ud800b", "time": "2026-10-01T00:00:00Z"}'
    row = n.normalize(DecodedLine(text=line, bytes_invalid=False, truncated=False))
    assert row is not None and row["raw"] == line
    LakeWriter(tmp_path).write([row])
    import pyarrow.parquet as pq

    (written,) = tmp_path.rglob("*.parquet")
    assert pq.read_table(written).column("message").to_pylist() == ["a�b"]


def test_rows_without_a_message_field_get_a_short_summary() -> None:
    """Generic CSV and JSON rows with no message column used to show a blank message."""
    from app.ingest.normalizer import Normalizer
    from app.ingest.records import DecodedLine

    csv = Normalizer(SourceSpec(source_id="vpn", format="csv"))
    csv.normalize(
        DecodedLine(text="time,user,client_ip,result,reason", bytes_invalid=False, truncated=False)
    )
    row = csv.normalize(
        DecodedLine(
            text="2026-10-10T03:30:40Z,bob,203.0.113.9,failure,",
            bytes_invalid=False,
            truncated=False,
        )
    )
    assert row is not None
    assert row["message"] == "user=bob client_ip=203.0.113.9 result=failure"  # no time, no empties
    assert row["raw"] == "2026-10-10T03:30:40Z,bob,203.0.113.9,failure,"  # raw untouched

    js = Normalizer(SourceSpec(source_id="app", format="json"))
    row = js.normalize(
        DecodedLine(
            text='{"ts": 1, "level": "warn", "ctx": {"a": 1}, "note": "' + "x" * 600 + '"}',
            bytes_invalid=False,
            truncated=False,
        )
    )
    assert row is not None
    assert row["message"].startswith("ts=1 level=warn note=xxx")  # nested values are left out
    assert len(row["message"]) <= 300
    kept = js.normalize(
        DecodedLine(text='{"msg": "hello", "a": 1}', bytes_invalid=False, truncated=False)
    )
    assert kept is not None and kept["message"] == "hello"  # a real message wins
