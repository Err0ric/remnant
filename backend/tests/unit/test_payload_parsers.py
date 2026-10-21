"""Payload parsers (CLAUDE.md section 6): kv quoting, CSV commas, CEF pipes, LEEF 1 and 2,
JSON roots, XML safety, regex timeouts. Inputs are hostile: parsers return errors, never raise.
"""

import time

import pytest

from app.ingest.payload.cef import CefParser
from app.ingest.payload.delimited import CsvParser
from app.ingest.payload.jsonpayload import JsonParser, parse_root
from app.ingest.payload.kv import KvParser
from app.ingest.payload.leef import LeefParser
from app.ingest.payload.regexpayload import PlainParser, RegexParser
from app.ingest.payload.xmlpayload import XmlParser

GARBAGE = ["", " ", "\x00\x01\x02", "=" * 100, "|" * 100, "<" * 100, "{" * 5000, "a" * 10_000]

# --- kv --------------------------------------------------------------------------------


def test_kv_fortinet_quoted_and_escaped() -> None:
    line = (
        'date=2026-10-09 time=20:41:12 devname="FG-100F" type="event" subtype="user" '
        'srcip=192.0.2.5 msg="User \\"admin\\" login failed" action=login status=failed'
    )
    r = KvParser().parse(line)
    assert r.ok and not r.partial
    assert r.fields["devname"] == "FG-100F"
    assert r.fields["msg"] == 'User "admin" login failed'
    assert r.fields["srcip"] == "192.0.2.5" and r.fields["status"] == "failed"


def test_kv_backslash_escape_and_empty_value() -> None:
    r = KvParser().parse('path="C:\\\\Windows\\\\x" empty= next=1')
    assert r.fields == {"path": "C:\\Windows\\x", "empty": "", "next": "1"}


def test_kv_custom_separators_and_stray_tokens() -> None:
    r = KvParser(pair_sep=";", kv_sep=":").parse("src:10.0.0.1;dst:10.0.0.2;junk;port:443")
    assert r.fields["src"] == "10.0.0.1" and r.fields["port"] == "443"
    assert r.partial and r.fields["_unparsed"] == "junk"


def test_kv_multiple_spaces_and_tabs() -> None:
    r = KvParser().parse("a=1    b=2\tc=3")
    assert r.fields == {"a": "1", "b": "2", "c": "3"}


def test_kv_unterminated_quote_is_partial() -> None:
    r = KvParser().parse('a=1 msg="never closed')
    assert r.fields["a"] == "1" and r.fields["msg"] == "never closed" and r.partial


def test_kv_rejects_bad_config() -> None:
    with pytest.raises(ValueError):
        KvParser(pair_sep="=", kv_sep="=")


# --- csv -------------------------------------------------------------------------------


PAN_COLUMNS = [
    "_",
    "receive_time",
    "serial",
    "type",
    "subtype",
    "_",
    "time_generated",
    "src",
    "dst",
]


def test_csv_positional_with_embedded_commas() -> None:
    line = (
        '1,2026/10/09 20:41:12,0123,TRAFFIC,end,,2026/10/09 20:41:11,"10.0.0.5","192.0.2.9, extra"'
    )
    r = CsvParser(PAN_COLUMNS).parse(line)
    assert r.ok and not r.partial
    assert r.fields["type"] == "TRAFFIC" and r.fields["dst"] == "192.0.2.9, extra"
    assert "_" not in r.fields


def test_csv_empty_cells_are_none_and_counts_checked() -> None:
    r = CsvParser(["a", "b", "c"]).parse("1,,3,4")
    assert r.fields["b"] is None and r.fields["_extra"] == ["4"] and r.partial
    short = CsvParser(["a", "b", "c"]).parse("1")
    assert short.fields == {"a": "1"} and short.partial


def test_csv_tab_delimited_snare() -> None:
    r = CsvParser(["host", "type", "event_id"], delimiter="\t").parse("dc01\tMSWinEventLog\t4624")
    assert r.fields == {"host": "dc01", "type": "MSWinEventLog", "event_id": "4624"}


# --- CEF -------------------------------------------------------------------------------


def test_cef_escaped_pipes_and_extension() -> None:
    line = (
        "CEF:0|Security|threat\\|manager|1.0|100|worm successfully stopped|10|"
        "src=10.0.0.1 dst=192.0.2.1 msg=Detected a threat. No action needed act=blocked a\\=b"
    )
    r = CefParser().parse(line)
    assert r.ok and not r.partial
    assert r.fields["device_product"] == "threat|manager"
    assert r.fields["severity"] == "10"
    assert r.fields["src"] == "10.0.0.1"
    assert r.fields["msg"] == "Detected a threat. No action needed"
    assert r.fields["act"] == "blocked a=b"


def test_cef_after_syslog_prefix_and_line_breaks() -> None:
    r = CefParser().parse(
        "host1 CEF:0|V|P|1|sig|Name|Low|msg=line1\\nline2 cs1Label=Rule cs1=Allow"
    )
    assert r.fields["msg"] == "line1\nline2"
    assert r.fields["cs1Label"] == "Rule" and r.fields["cs1"] == "Allow"
    assert r.fields["signature_id"] == "sig"


def test_cef_truncated_header_is_partial() -> None:
    r = CefParser().parse("CEF:0|Vendor|Prod")
    assert r.partial and r.fields["device_vendor"] == "Vendor"


# --- LEEF ------------------------------------------------------------------------------


def test_leef_v1_tab_attributes() -> None:
    r = LeefParser().parse(
        "LEEF:1.0|Microsoft|MSExchange|2016|15345|src=10.0.0.1\tdst=192.0.2.2\tusrName=jordan"
    )
    assert r.fields["vendor"] == "Microsoft" and r.fields["event_id"] == "15345"
    assert r.fields["usrName"] == "jordan" and r.fields["dst"] == "192.0.2.2"


def test_leef_v2_custom_and_hex_delimiters() -> None:
    caret = LeefParser().parse(
        "LEEF:2.0|Lancope|StealthWatch|1.0|41|^|src=10.0.0.1^dst=192.0.2.1^sev=5"
    )
    assert caret.fields["src"] == "10.0.0.1" and caret.fields["sev"] == "5"
    hexed = LeefParser().parse("LEEF:2.0|V|P|1|E1|x09|a=1\tb=2")
    assert hexed.fields["a"] == "1" and hexed.fields["b"] == "2"
    no_delim = LeefParser().parse("LEEF:2.0|V|P|1|E1|a=1\tb=x=y")
    assert no_delim.fields["a"] == "1" and no_delim.fields["b"] == "x=y"


def test_leef_unknown_version() -> None:
    assert not LeefParser().parse("LEEF:9|x|y").ok


# --- JSON ------------------------------------------------------------------------------


def test_json_nested_root() -> None:
    line = '{"records": [{"user": {"name": "jordan"}, "ok": true}], "meta": 1}'
    r = JsonParser("$.records[0]").parse(line)
    assert r.fields == {"user": {"name": "jordan"}, "ok": True}
    q = JsonParser("$['meta data'].x").parse('{"meta data": {"x": {"y": 2}}}')
    assert q.fields == {"y": 2}


def test_json_prefixes_and_errors() -> None:
    assert JsonParser().parse('@cee: {"a": 1}').fields == {"a": 1}
    assert JsonParser().parse('app[1]: {"a": 1}').fields == {"a": 1}
    assert not JsonParser().parse("[1, 2]").ok
    assert not JsonParser("$.x").parse('{"y": 1}').ok
    assert not JsonParser().parse("{" * 100_000).ok  # deep nesting, no RecursionError


@pytest.mark.parametrize("bad", ["", "a.b", "$..x", "$[*]", "$.a[?(@.x)]"])
def test_json_root_syntax_is_validated(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_root(bad)


# --- XML -------------------------------------------------------------------------------

WIN_NS = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}
WIN_XML = (
    '<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event"><System>'
    '<Provider Name="Microsoft-Windows-Security-Auditing"/><EventID>4624</EventID>'
    "<Computer>dc01.example.internal</Computer></System><EventData>"
    '<Data Name="TargetUserName">jordan</Data><Data Name="IpAddress">192.0.2.7</Data>'
    "</EventData></Event>"
)


def test_xml_windows_event_fields() -> None:
    p = XmlParser(
        {
            "event_id": "e:System/e:EventID",
            "provider": "e:System/e:Provider/@Name",
            "user": "e:EventData/e:Data[@Name='TargetUserName']",
            "missing": "e:System/e:Nope",
        },
        WIN_NS,
    )
    r = p.parse(WIN_XML)
    assert r.fields == {
        "event_id": "4624",
        "provider": "Microsoft-Windows-Security-Auditing",
        "user": "jordan",
        "missing": None,
    }


@pytest.mark.parametrize(
    "hostile",
    [
        '<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><r>&b;</r>',
        '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><r>&x;</r>',
        "<r><unclosed></r>",
    ],
)
def test_xml_refuses_entities_external_refs_and_garbage(hostile: str) -> None:
    r = XmlParser({"v": "."}).parse(hostile)
    assert not r.ok
    assert "root:" not in str(r.fields)


def test_xml_bad_path_rejected_at_load() -> None:
    with pytest.raises(ValueError):
        XmlParser({"v": "a[@"})


# --- regex -----------------------------------------------------------------------------


def test_regex_first_match_wins_named_groups_only() -> None:
    p = RegexParser(
        [
            r"^(?P<outcome>Accepted|Failed) (?P<method>\S+) for (?:invalid user )?(?P<user>\S+)",
            r"^Invalid user (?P<user>\S+)",
        ]
    )
    assert p.parse("Failed password for invalid user oracle from 203.0.113.9").fields == {
        "outcome": "Failed",
        "method": "password",
        "user": "oracle",
    }
    assert p.parse("Invalid user admin from 203.0.113.9").fields == {"user": "admin"}
    assert not p.parse("Connection closed").ok


def test_regex_catastrophic_backtracking_times_out() -> None:
    p = RegexParser([r"^(?P<x>(a|aa)+)$"], timeout_s=0.05)
    started = time.monotonic()
    r = p.parse("a" * 40 + "!")
    assert not r.ok and r.error == "regex timed out"
    assert time.monotonic() - started < 2


def test_regex_patterns_validated() -> None:
    with pytest.raises(ValueError, match="pattern 1"):
        RegexParser(["(unclosed"])
    with pytest.raises(ValueError, match="named groups"):
        RegexParser([r"^\d+$"])


def test_plain() -> None:
    assert PlainParser().parse("anything at all").fields == {"message": "anything at all"}


# --- hostile input never raises ----------------------------------------------------------


@pytest.mark.parametrize("text", GARBAGE)
def test_no_parser_raises_on_garbage(text: str) -> None:
    parsers = [
        KvParser(),
        CsvParser(["a", "b"]),
        CefParser(),
        LeefParser(),
        JsonParser(),
        XmlParser({"v": "."}),
        RegexParser([r"^(?P<a>\w+)"]),
        PlainParser(),
    ]
    for p in parsers:
        p.parse(text)
