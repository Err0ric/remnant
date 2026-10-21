"""Sigma to DuckDB conversion (D7, ADR-0006): run the compiled condition on real rows."""

import json

import duckdb
import pytest
from sigma.collection import SigmaCollection

from app.core.errors import RuleRejectedError
from app.detect.pipelines.compat import compat_pipeline
from app.detect.sigma_backend import DuckDBBackend
from app.engine.guard import guard

# The same failed logon as each transport stores it, plus lines that must not match.
ROWS = [
    ("nxlog", "DC01", "x", {"EventID": 4625, "TargetUserName": "Administrator"}),
    (
        "beat",
        "dc01",
        "x",
        {"winlog": {"event_id": "4625", "event_data": {"TargetUserName": "ADMINISTRATOR"}}},
    ),
    (
        "evtx",
        "DC01",
        "x",
        {"Event": {"System": {"EventID": 4625}, "EventData": {"TargetUserName": "administrator"}}},
    ),
    ("other_user", "DC01", "x", {"EventID": 4625, "TargetUserName": "bob"}),
    ("other_event", "DC01", "x", {"EventID": 4624, "TargetUserName": "Administrator"}),
    ("sshd", "bastion", "sshd[1]: Failed password for root from 203.0.113.9", {}),
    ("quote", "h", "x", {"EventID": 1, "CommandLine": "echo it's 100% done_now"}),
]


@pytest.fixture(scope="module")
def con() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect(":memory:")
    c.execute(
        "CREATE TABLE events (id VARCHAR, device_hostname VARCHAR, raw VARCHAR, unmapped VARCHAR)"
    )
    c.executemany(
        "INSERT INTO events VALUES (?, ?, ?, ?)",
        [(i, h, r, json.dumps(u) if u else None) for i, h, r, u in ROWS],
    )
    return c


def convert(rule_body: str) -> str:
    rule = "title: t\nlogsource: {product: windows, service: security}\n" + rule_body
    (condition,) = DuckDBBackend(processing_pipeline=compat_pipeline()).convert(
        SigmaCollection.from_yaml(rule)
    )
    assert isinstance(condition, str)
    return condition


def matches(con: duckdb.DuckDBPyConnection, rule_body: str) -> set[str]:
    sql = f"SELECT id FROM events WHERE {convert(rule_body)}"
    return {r[0] for r in con.execute(sql).fetchall()}


def test_one_rule_matches_every_transport_case_insensitively(
    con: duckdb.DuckDBPyConnection,
) -> None:
    got = matches(
        con,
        "detection:\n  sel:\n    EventID: 4625\n    TargetUserName: administrator\n"
        "  condition: sel\n",
    )
    assert got == {"nxlog", "beat", "evtx"}


def test_wildcards_modifiers_and_keywords(con: duckdb.DuckDBPyConnection) -> None:
    assert matches(con, "detection:\n  s:\n    Computer|startswith: dc\n  condition: s\n") >= {
        "nxlog",
        "beat",
    }
    assert matches(con, "detection:\n  s:\n    TargetUserName: 'Admin*'\n  condition: s\n") == {
        "nxlog", "beat", "evtx", "other_event"
    }  # fmt: skip
    assert matches(con, "detection:\n  k:\n    - 'failed password'\n  condition: k\n") == {"sshd"}


def test_quotes_and_like_characters_in_values_are_literal(con: duckdb.DuckDBPyConnection) -> None:
    rule = 'detection:\n  s:\n    CommandLine|contains: "it\'s 100% done_now"\n  condition: s\n'
    assert matches(con, rule) == {"quote"}
    # % and _ in a value are not wildcards: "100_ done" must not match "100% done".
    rule = "detection:\n  s:\n    CommandLine|contains: '100_ done'\n  condition: s\n"
    assert matches(con, rule) == set()


def test_a_filter_on_a_missing_field_does_not_drop_the_event(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """SQL NOT of NULL is NULL; Sigma treats a missing field as not matching the filter."""
    rule = (
        "detection:\n  sel:\n    EventID: 4625\n  filter:\n    IpAddress: '-'\n"
        "  condition: sel and not filter\n"
    )
    assert matches(con, rule) >= {"nxlog", "beat", "evtx"}  # none of them has IpAddress


def test_regex_is_re2_and_case_flags_work(con: duckdb.DuckDBPyConnection) -> None:
    rule = "detection:\n  s:\n    TargetUserName|re|i: '^admin.*'\n  condition: s\n"
    assert matches(con, rule) == {"nxlog", "beat", "evtx", "other_event"}
    with pytest.raises(RuleRejectedError):  # lookbehind: not RE2, refused at conversion
        convert("detection:\n  s:\n    TargetUserName|re: '(?<=a)b'\n  condition: s\n")


@pytest.mark.parametrize(
    "field",
    ["Target'UserName", 'a"b', "a\\b", "$x", "a b", "x" * 200],
)
def test_unsafe_field_names_refuse_the_rule(field: str) -> None:
    body = f"detection:\n  s:\n    {json.dumps(field)}: v\n  condition: s\n"
    with pytest.raises(RuleRejectedError):
        convert(body)


def test_values_cannot_break_out_of_the_literal(con: duckdb.DuckDBPyConnection) -> None:
    hostile = "x' OR 1=1 --"
    rule = f"detection:\n  s:\n    TargetUserName: {json.dumps(hostile)}\n  condition: s\n"
    assert matches(con, rule) == set()
    assert "'x'' OR 1=1 --'" in convert(rule)


def test_compiled_conditions_pass_the_query_guard() -> None:
    for body in (
        "detection:\n  s:\n    EventID: 4625\n    TargetUserName|contains: adm\n  condition: s\n",
        "detection:\n  s:\n    CommandLine|re: 'a.*b'\n  k:\n    - x\n  condition: s or k\n",
        "detection:\n  s:\n    EventID|gt: 4000\n  f:\n    Image: null\n  condition: s and not f\n",
    ):
        guarded = guard(
            f"SELECT event_id FROM events WHERE {convert(body)}", frozenset({"events"}), 101, 101
        )
        assert "events" in guarded.sql


def test_dns_query_field_reads_where_dns_templates_keep_it() -> None:
    # QA F9: `query|contains` ran on DNS events with 0 matches; the name is in qname.
    from app.detect.pipelines.compat import field_expression

    c = duckdb.connect(":memory:")
    c.execute("CREATE TABLE events (dst_endpoint_hostname VARCHAR, unmapped VARCHAR)")
    c.executemany(
        "INSERT INTO events VALUES (?, ?)",
        [
            (None, json.dumps({"qname": "chat.deepseek.com"})),
            (None, json.dumps({"query": "api.openai.com"})),
            ("claude.ai", "{}"),
            (None, json.dumps({"qname": "example.com"})),
        ],
    )
    expr = field_expression("query")
    got = c.execute(f"SELECT {expr} FROM events").fetchall()  # fixed expression
    assert [g[0] for g in got] == [
        "chat.deepseek.com",
        "api.openai.com",
        "claude.ai",
        "example.com",
    ]
