"""Rule file to runnable condition, with Windows narrowing (ADR-0006)."""

import json

import duckdb
import pytest

from app.core.errors import RuleRejectedError
from app.detect.logsource import LogSource
from app.detect.rules import MAX_RULE_BYTES, compile_rule, windows_narrowing

SYSMON = "Microsoft-Windows-Sysmon/Operational"
ROWS = [
    # Sysmon 1 (process creation) and Sysmon 3 (network) both carry Image.
    (
        "proc",
        {
            "winlog": {
                "channel": SYSMON,
                "event_id": 1,
                "event_data": {"Image": "C:\\Windows\\System32\\cmd.exe"},
            }
        },
    ),
    (
        "net",
        {
            "winlog": {
                "channel": SYSMON,
                "event_id": 3,
                "event_data": {"Image": "C:\\Windows\\System32\\cmd.exe"},
            }
        },
    ),
    ("sec", {"Channel": "Security", "EventID": 4625, "TargetUserName": "admin"}),
    ("sys", {"Channel": "System", "EventID": 4625, "TargetUserName": "admin"}),
    (
        "evtx",
        {
            "Event": {
                "System": {"Channel": "security", "EventID": 4625},
                "EventData": {"TargetUserName": "admin"},
            }
        },
    ),
    ("snare", {"log_name": "Security", "event_id": "4625", "TargetUserName": "admin"}),
]


@pytest.fixture(scope="module")
def con() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect(":memory:")
    c.execute(
        "CREATE TABLE events (id VARCHAR, device_hostname VARCHAR, raw VARCHAR, unmapped VARCHAR)"
    )
    c.executemany(
        "INSERT INTO events VALUES (?, 'h', 'x', ?)", [(i, json.dumps(u)) for i, u in ROWS]
    )
    return c


def rule(logsource: str, detection: str, extra: str = "") -> bytes:
    return (
        f"title: Test rule\nid: 0f0e0d0c-0000-4000-8000-000000000001\nauthor: Jane Doe\n"
        f"level: high\nstatus: test\ntags: [attack.t1059]\n{extra}"
        f"logsource:\n{logsource}\ndetection:\n{detection}"
    ).encode()


def hits(con: duckdb.DuckDBPyConnection, data: bytes) -> set[str]:
    c = compile_rule(data)
    return {r[0] for r in con.execute(f"SELECT id FROM events WHERE {c.condition}").fetchall()}


def test_process_creation_is_narrowed_to_sysmon_event_1(con: duckdb.DuckDBPyConnection) -> None:
    data = rule(
        "  product: windows\n  category: process_creation\n",
        "  sel:\n    Image|endswith: '\\cmd.exe'\n  condition: sel\n",
    )
    assert hits(con, data) == {"proc"}  # not the network event with the same Image


def test_service_is_narrowed_to_its_channel_on_every_transport(
    con: duckdb.DuckDBPyConnection,
) -> None:
    data = rule(
        "  product: windows\n  service: security\n",
        "  sel:\n    EventID: 4625\n  condition: sel\n",
    )
    assert hits(con, data) == {"sec", "evtx", "snare"}  # not the System event


def test_metadata_is_kept_for_attribution() -> None:
    c = compile_rule(rule("  product: linux\n", "  k:\n    - x\n  condition: k\n"))
    assert (c.rule_id, c.title, c.author, c.level, c.status) == (
        "0f0e0d0c-0000-4000-8000-000000000001", "Test rule", "Jane Doe", "high", "test"
    )  # fmt: skip
    assert c.tags == ("attack.t1059",) and len(c.sha256) == 64
    assert c.logsource == LogSource("linux")


def test_a_rule_without_author_or_id_still_has_an_identity() -> None:
    data = b"title: t\nlogsource: {product: linux}\ndetection:\n  k: [x]\n  condition: k\n"
    c = compile_rule(data)
    assert c.author == "" and c.rule_id == c.sha256


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"x" * (MAX_RULE_BYTES + 1), "larger than"),
        (b"\xff\xfe", "UTF-8"),
        (b"- a\n- b\n", "one YAML mapping"),
        (b"a: &x [1]\nb: *x\n", "UTF-8 YAML"),
        (b"title: t\nlogsource: {product: linux}\n", "no detection"),
        (b"title: t\ndetection: {k: [x], condition: k}\n", "names no product"),
        (
            b"title: t\ncorrelation: {type: event_count}\nlogsource: {product: linux}\ndetection: {}\n",
            "Correlation",
        ),
        (
            rule("  product: windows\n  service: madeup\n", "  k: [x]\n  condition: k\n"),
            "service 'madeup'",
        ),
        (
            rule("  product: windows\n  category: madeup\n", "  k: [x]\n  condition: k\n"),
            "category 'madeup'",
        ),
        (rule("  product: linux\n", "  s:\n    a|re: '(?<=x)y'\n  condition: s\n"), "RE2"),
        (rule("  product: linux\n", "  s:\n    a: x\n  condition: nope\n"), "cannot be converted"),
        (rule("  product: linux\n", '  s:\n    "a\'b": x\n  condition: s\n'), "field name"),
    ],
)
def test_bad_rules_are_refused_with_a_reason(data: bytes, reason: str) -> None:
    with pytest.raises(RuleRejectedError, match=reason):
        compile_rule(data)


def test_powershell_and_non_windows_narrowing() -> None:
    cond = windows_narrowing(LogSource("windows", None, "ps_script"))
    assert (
        cond is not None
        and "'microsoft-windows-powershell/operational'" in cond
        and "'4104'" in cond
    )
    assert windows_narrowing(LogSource("linux", "auditd")) is None
    assert windows_narrowing(LogSource("windows")) is None


SEC4688 = [
    (
        "sec_cmd",
        {
            "Channel": "Security",
            "EventID": 4688,
            "NewProcessName": "C:\\Windows\\System32\\cmd.exe",
            "ParentProcessName": "C:\\Program Files\\Office\\WINWORD.EXE",
            "CommandLine": "cmd /c whoami",
        },
    ),
    (
        "sec_other",
        {
            "Channel": "Security",
            "EventID": 4689,
            "NewProcessName": "C:\\Windows\\System32\\cmd.exe",
        },
    ),
]


@pytest.fixture(scope="module")
def con4688() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect(":memory:")
    c.execute(
        "CREATE TABLE events (id VARCHAR, device_hostname VARCHAR, raw VARCHAR, unmapped VARCHAR)"
    )
    c.executemany(
        "INSERT INTO events VALUES (?, 'h', 'x', ?)",
        [(i, json.dumps(u)) for i, u in ROWS + SEC4688],
    )
    return c


def test_process_creation_also_matches_security_4688_with_4688_field_names(
    con4688: duckdb.DuckDBPyConnection,
) -> None:
    data = rule(
        "  product: windows\n  category: process_creation\n",
        "  sel:\n    Image|endswith: '\\cmd.exe'\n    ParentImage|endswith: '\\WINWORD.EXE'\n"
        "  condition: sel\n",
    )
    assert compile_rule(data).security_4688 is True
    assert hits(con4688, data) == {"sec_cmd"}  # Sysmon proc has no Word parent; 4689 is not 4688
    simple = rule(
        "  product: windows\n  category: process_creation\n",
        "  sel:\n    Image|endswith: '\\cmd.exe'\n  condition: sel\n",
    )
    assert hits(con4688, simple) == {"proc", "sec_cmd"}  # Sysmon 1 and 4688, not Sysmon 3


def test_rules_using_fields_4688_lacks_stay_sysmon_only(con4688: duckdb.DuckDBPyConnection) -> None:
    data = rule(
        "  product: windows\n  category: process_creation\n",
        "  sel:\n    Image|endswith: '\\cmd.exe'\n  filter:\n    OriginalFileName: 'Cmd.Exe'\n"
        "  condition: sel and not filter\n",
    )
    compiled = compile_rule(data)
    assert compiled.security_4688 is False
    assert "sec_cmd" not in hits(con4688, data)  # the filter could never apply to 4688


def test_evtx_event_ids_with_qualifiers_are_read_from_their_text() -> None:
    c = duckdb.connect(":memory:")
    c.execute(
        "CREATE TABLE events (id VARCHAR, device_hostname VARCHAR, raw VARCHAR, unmapped VARCHAR)"
    )
    evtx = {
        "Event": {
            "System": {
                "Channel": "System",
                "EventID": {"#attributes": {"Qualifiers": 16384}, "#text": 7045},
            }
        }
    }
    c.execute("INSERT INTO events VALUES ('svc', 'h', 'x', ?)", [json.dumps(evtx)])
    data = rule(
        "  product: windows\n  service: system\n", "  s:\n    EventID: 7045\n  condition: s\n"
    )
    assert hits(c, data) == {"svc"}


def test_a_fieldref_to_a_field_4688_lacks_keeps_the_rule_sysmon_only() -> None:
    data = rule(
        "  product: windows\n  category: process_creation\n",
        "  sel:\n    Image|endswith: '\\cmd.exe'\n  filter:\n    Image|fieldref: OriginalFileName\n"
        "  condition: sel and not filter\n",
    )
    assert compile_rule(data).security_4688 is False
