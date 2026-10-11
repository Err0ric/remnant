"""Template schema, runtime, tester, and loader (SPEC 4, CLAUDE.md rules 5, 6, 9)."""

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.ingest.records import DecodedLine
from app.templates.loader import load_all, load_dir, parse_template
from app.templates.runtime import TemplateNormalizer
from app.templates.tester import parse_rate, run_tests
from app.templates.validator import Template

FIXTURES = Path(__file__).parent.parent / "fixtures" / "templates"
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def doc(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load((FIXTURES / f"{name}.yaml").read_text())
    return loaded


def sshd() -> Template:
    return Template.model_validate(doc("linux_sshd"))


def line(text: str, truncated: bool = False) -> DecodedLine:
    return DecodedLine(text=text, bytes_invalid=False, truncated=truncated)


def norm(t: Template) -> TemplateNormalizer:
    return TemplateNormalizer(t, "linux_auth", "local_only", clock=lambda: NOW)


# --- the SPEC examples load and pass their own tests -------------------------------------


@pytest.mark.parametrize("name", ["linux_sshd", "nginx_access_combined"])
def test_spec_examples_pass_inline_tests(name: str) -> None:
    template = parse_template((FIXTURES / f"{name}.yaml").read_text())
    outcomes = run_tests(template)
    assert len(outcomes) == 3 and all(o.passed for o in outcomes), outcomes


# --- validation --------------------------------------------------------------------------


def invalid(change: dict[str, Any], *path: str) -> str:
    d = doc("linux_sshd")
    target = d
    for key in path:
        target = target[key]
    target.update(change)
    with pytest.raises(ValueError) as err:
        parse_template(yaml.safe_dump(d))
    return str(err.value)


@pytest.mark.parametrize("column", ["raw", "classification", "event_id", "source_id", "unmapped"])
def test_server_columns_cannot_be_mapped(column: str) -> None:
    msg = invalid({column: {"from": "user"}}, "mapping", "fields")
    assert "set by the server" in msg and column in msg


def test_unknown_column_unknown_envelope_field_and_bad_id() -> None:
    assert "not a column" in invalid({"nope": {"from": "user"}}, "mapping", "fields")
    assert "unknown envelope field" in invalid(
        {"message": {"from": "envelope.secret"}}, "mapping", "fields"
    )
    assert "snake_case" in invalid({"id": "Bad-Id"})
    assert "semver" in invalid({"version": "1.0"})


def test_needs_three_tests_and_valid_regex() -> None:
    d = doc("linux_sshd")
    d["tests"] = d["tests"][:2]
    with pytest.raises(ValueError, match="tests"):
        parse_template(yaml.safe_dump(d))
    msg = invalid({"patterns": ["(?P<x>unclosed"]}, "payload", "regex")
    assert "pattern 1" in msg


def test_format_blocks_are_required() -> None:
    assert "payload.regex block" in invalid({"format": "regex", "regex": None}, "payload")
    assert "columns" in invalid({"format": "csv"}, "payload")
    assert "fields" in invalid({"format": "xml"}, "payload")


def test_unknown_keys_and_unsafe_yaml_rejected() -> None:
    assert "Extra inputs" in invalid({"run_command": "rm -rf /"})
    with pytest.raises(ValueError, match="YAML"):
        parse_template("!!python/object/apply:os.system ['id']")


# --- runtime -----------------------------------------------------------------------------


def test_parsed_fields_map_to_columns_and_leftovers_go_to_unmapped() -> None:
    row = norm(sshd()).normalize(
        line(
            "<38>Oct  9 20:41:15 bastion sshd[2240]: Failed password for invalid user admin"
            " from 203.0.113.9 port 40022 ssh2"
        )
    )
    assert row["parse_status"] == "ok" and row["parse_errors"] is None
    assert (row["class_uid"], row["category_uid"]) == (3002, 3)
    assert row["actor_user_name"] == "admin" and row["src_endpoint_port"] == 40022
    assert row["status_id"] == 2 and row["severity_id"] == 3
    assert row["device_hostname"] == "bastion" and row["actor_process_pid"] == 2240
    assert json.loads(row["unmapped"]) == {"method": "password"}
    assert row["template_id"] == "linux_sshd" and row["template_version"] == "1.0.0"
    assert row["classification"] == "local_only"


def test_raw_is_never_modified() -> None:
    text = "<38>Oct  9 20:41:15 bastion sshd[1]: Accepted publickey for jordan from 10.0.0.1 port 1 x  "
    assert norm(sshd()).normalize(line(text))["raw"] == text


def test_payload_miss_with_envelope_is_envelope_only() -> None:
    row = norm(sshd()).normalize(line("<38>Oct  9 20:41:15 bastion sshd[7]: Connection closed"))
    assert row["parse_status"] == "envelope_only"
    assert row["device_hostname"] == "bastion" and row["message"] == "Connection closed"
    assert "payload:no pattern matched" in row["parse_errors"]


def test_headerless_line_still_parses_payload_but_is_partial() -> None:
    row = norm(sshd()).normalize(line("Accepted publickey for jordan from 10.0.0.1 port 22 ssh2"))
    assert row["parse_status"] == "partial" and "no_syslog_header" in row["parse_errors"]
    assert row["actor_user_name"] == "jordan"


def test_truncated_and_bad_values_are_partial() -> None:
    t = norm(sshd())
    cut = t.normalize(
        line("<38>Oct  9 20:41:15 h sshd[1]: Accepted publickey for e from 10.0.0.1 port 2 x", True)
    )
    assert cut["parse_status"] == "partial" and cut["parse_errors"].startswith("truncated")
    big = t.normalize(
        line(
            "<38>Oct  9 20:41:15 h sshd[1]: Accepted pk for e from 10.0.0.1 port 99999999999999999999"
        )
    )
    assert big["parse_status"] == "partial" and big["src_endpoint_port"] is None


def test_class_by_severity_and_transforms() -> None:
    d = doc("linux_sshd")
    d["mapping"]["class_by"] = {"field": "outcome", "values": {"Failed": 3003}}
    d["transforms"] = [
        {"field": "user", "op": "to_upper"},
        {
            "field": "src_ip",
            "op": "regex_extract",
            "args": {"pattern": r"^(\d+)\.", "into": "octet"},
        },
    ]
    d["mapping"]["fields"]["actor_user_name"] = {"from": "user"}
    d["mapping"]["fields"]["dst_endpoint_hostname"] = {"from": "octet"}
    d["tests"] = [d["tests"][0]] * 3
    d["tests"][0]["expect"]["fields"]["actor_user_name"] = "JORDAN"
    t = Template.model_validate(d)
    row = norm(t).normalize(
        line("<38>Oct  9 20:41:15 h sshd[1]: Failed password for bob from 203.0.113.9 port 22 ssh2")
    )
    assert row["class_uid"] == 3003 and row["category_uid"] == 3
    assert row["actor_user_name"] == "BOB" and row["dst_endpoint_hostname"] == "203"


def test_hostile_lines_never_raise_and_stay_fast() -> None:
    t = norm(sshd())
    started = time.monotonic()
    for text in ("", "\x00" * 100, "a" * 10_240, "<" * 10_240, "<38>" + "x " * 5000):
        row = t.normalize(line(text))
        assert row["raw"] == text
    assert time.monotonic() - started < 2


def test_parse_rate_counts() -> None:
    t = sshd()
    rate = parse_rate(
        t,
        [
            "<38>Oct  9 20:41:15 h sshd[1]: Accepted publickey for e from 10.0.0.1 port 2 x",
            "<38>Oct  9 20:41:15 h sshd[1]: Connection closed",
            "garbage",
        ],
    )
    assert (rate.lines, rate.ok, rate.failed) == (3, 1, 2)
    assert rate.errors["payload:no pattern matched"] == 2


# --- loader ------------------------------------------------------------------------------


def test_loader_reports_problems_and_skips_drafts(tmp_path: Path) -> None:
    starter, user = tmp_path / "starter", tmp_path / "user"
    starter.mkdir()
    (user / "drafts").mkdir(parents=True)
    text = (FIXTURES / "linux_sshd.yaml").read_text()
    (starter / "linux_sshd.yaml").write_text(text)
    (starter / "wrong_name.yaml").write_text((FIXTURES / "nginx_access_combined.yaml").read_text())
    (user / "linux_sshd.yaml").write_text(text)  # duplicate id
    (user / "drafts" / "draft_one.yaml").write_text("not even yaml: [")
    failing = yaml.safe_load(text)
    failing["id"] = "sshd_failing"
    failing["tests"][0]["expect"]["fields"]["actor_user_name"] = "someone_else"
    (user / "sshd_failing.yaml").write_text(yaml.safe_dump(failing))

    found, problems = load_all(starter, user)
    assert list(found) == ["linux_sshd"]
    messages = {p.file: p.message for p in problems}
    assert messages["wrong_name.yaml"] == "file name must be nginx_access_combined.yaml"
    assert "already used by a starter" in messages["linux_sshd.yaml"]
    assert "accepted publickey 3164" in messages["sshd_failing.yaml"]
    assert "draft_one.yaml" not in messages


def test_missing_directories_are_empty(tmp_path: Path) -> None:
    assert load_dir(tmp_path / "nope") == ({}, [])


# --- review findings: hostile values, template mistakes, writer safety ----------------------


def custom(**changes: Any) -> dict[str, Any]:
    d = doc("linux_sshd")
    for path, value in changes.items():
        target = d
        keys = path.split("__")
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = value
    return d


def test_odd_severity_values_never_raise() -> None:
    d = custom(mapping__severity={"from": "user", "map": {}})
    t = norm(Template.model_validate(d))
    for user in ("²", "9" * 5000, "7", "-1"):
        row = t.normalize(
            line(
                f"<38>Oct  9 20:41:15 h sshd[1]: Failed password for {user} from 10.0.0.1 port 2 x"
            )
        )
        assert row["severity_id"] is None or 0 <= row["severity_id"] <= 6


def test_huge_ints_and_non_finite_json_stay_safe(tmp_path: Path) -> None:
    from app.ingest.writer import LakeWriter

    d = doc("nginx_access_combined")
    d["transforms"].append({"field": "user", "op": "to_int", "args": {"base": "auto"}})
    t = TemplateNormalizer(Template.model_validate(d), "web", clock=lambda: NOW)
    row = t.normalize(
        line(
            "10.0.0.5 - 0x"
            + "f" * 20000
            + ' [09/Oct/2026:20:41:12 -0700] "GET / HTTP/1.1" 200 1 "-" "x"'
        )
    )
    assert row["parse_status"] == "partial" and "transform_to_int:user" in row["parse_errors"]

    j = doc("linux_sshd")
    j.update(envelope={"type": "none"}, payload={"format": "json"})
    j["mapping"]["fields"] = {"message": {"from": "msg"}}
    j["mapping"].pop("severity")
    j["transforms"] = []
    for test in j["tests"]:
        test.update(input='{"msg": "x"}', expect={"parse_status": "ok"})
    jt = TemplateNormalizer(Template.model_validate(j), "app", clock=lambda: NOW)
    rows = [
        jt.normalize(line('{"msg": "a\\ud800b", "n": NaN, "m": Infinity, "time": 1}')),
        jt.normalize(line('{"msg": "' + "\\ud83d" * 3 + '"}')),
    ]
    assert json.loads(rows[0]["unmapped"]) == {"n": "NaN", "m": "Infinity", "time": 1}
    LakeWriter(tmp_path / "lake").write(rows)  # lone surrogates must not fail the batch


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"mapping__class_by": {"field": "outcome", "values": {"x": 2**70}}}, "less than or equal"),
        ({"mapping__class_by": {"field": "envelope.__class__", "values": {}}}, "envelope field"),
        ({"mapping__severity": {"from": "envelope.to_column"}}, "envelope field"),
        ({"payload__kv": {"pair_sep": "=", "kv_sep": "="}}, "distinct"),
        ({"match__regex": "(unclosed"}, "match.regex"),
        ({"framing__multiline": {"start": "[z-a]"}}, "multiline"),
        (
            {"transforms": [{"field": "user", "op": "regex_extract", "args": {"pattern": "abc"}}]},
            "group 1",
        ),
        (
            {
                "transforms": [
                    {
                        "field": "user",
                        "op": "regex_extract",
                        "args": {"pattern": "(?P<a>x)", "group": "b"},
                    }
                ]
            },
            "group 'b'",
        ),
        ({"mapping__fields__message": {"default": {"nested": [1, 2]}}}, "plain"),
        ({"mapping__fields__class_uid": {"default": 1}}, "class_uid"),
    ],
)
def test_template_mistakes_are_caught_at_load(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_template(yaml.safe_dump(custom(**changes)))


def test_xml_descendant_paths_rejected() -> None:
    d = custom(payload={"format": "xml", "xml": {"fields": {"a": ".//a//b"}}})
    with pytest.raises(ValueError, match="child paths"):
        parse_template(yaml.safe_dump(d))


def test_unexpected_errors_become_failed_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    t = norm(sshd())

    def boom(*_: object) -> None:
        raise RuntimeError("bug")

    monkeypatch.setattr(t, "_map", boom)
    text = "<38>Oct  9 20:41:15 h sshd[1]: Accepted publickey for e from 10.0.0.1 port 2 x"
    row = t.normalize(line(text))
    assert row["parse_status"] == "failed" and row["parse_errors"] == "internal:RuntimeError"
    assert row["raw"] == text and row["source_id"] == "linux_auth"


def test_unmapped_json_is_strict_value_by_value() -> None:
    from app.core import jsonsafe

    text = jsonsafe.dumps(
        {"a": "\udc00", "big": float("inf"), "keep": 1, "\ud800k": [float("nan")]}
    )
    assert json.loads(text) == {"a": "�", "big": "inf", "keep": 1, "�k": ["nan"]}
    assert text.isascii() and "\\ud" not in text


def test_clark_namespace_paths_are_allowed() -> None:
    d = custom(
        payload={
            "format": "xml",
            "xml": {
                "fields": {"id": "{http://schemas.microsoft.com/win/2004/08/events/event}System"}
            },
        }
    )
    d["tests"] = [
        {"name": f"t{i}", "input": "<Event/>", "expect": {"parse_status": "ok"}} for i in range(3)
    ]
    d["mapping"] = {"class_uid": 0, "fields": {"message": {"from": "id"}}}
    d["envelope"] = {"type": "none"}
    d["transforms"] = []
    parse_template(yaml.safe_dump(d))


def test_tester_fails_a_template_that_crashes(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.templates import runtime

    def boom(*_: object) -> None:
        raise RuntimeError("bug")

    monkeypatch.setattr(runtime.TemplateNormalizer, "_map", boom)
    outcomes = run_tests(sshd())
    assert not any(o.passed for o in outcomes)
    assert "crashed" in outcomes[0].problems[0]


def test_optional_extract_leaves_target_alone_and_empty_values_are_missing() -> None:
    from app.templates.transforms import TransformRunner
    from app.templates.validator import Transform

    steps = [
        Transform.model_validate(
            {
                "field": "rest",
                "op": "regex_extract",
                "args": {"pattern": "u=(\\w+)", "into": "user", "optional": True},
            }
        ),
        Transform.model_validate(
            {
                "field": "rest",
                "op": "regex_extract",
                "args": {"pattern": "h=(\\w+)", "into": "host"},
            }
        ),
    ]
    fields = {"user": "kept", "rest": "nothing here"}
    errors = TransformRunner(steps, UTC).apply(fields)
    assert fields["user"] == "kept"  # optional miss: untouched, no error
    assert fields["host"] is None and errors == ["transform_regex_extract:rest"]

    row = norm(sshd()).normalize(
        line("<38>Oct  9 20:41:15 h sshd[1]: Accepted publickey for  from 10.0.0.1 port 2 x")
    )
    assert row["actor_user_name"] is None  # empty capture is no value, not ""


@pytest.mark.parametrize(
    ("value", "iso"),
    [
        ("1791578472", "2026-10-09T20:41:12+00:00"),
        ("1791578472123", "2026-10-09T20:41:12.123000+00:00"),
        ("1791578472123456", "2026-10-09T20:41:12.123456+00:00"),
        ("1791578472123456789", "2026-10-09T20:41:12.123456+00:00"),
    ],
)
def test_epoch_auto_picks_the_unit_from_the_digits(value: str, iso: str) -> None:
    from app.templates.transforms import _timestamp

    assert _timestamp(value, "epoch_auto", UTC).isoformat() == iso


def test_epoch_auto_rejects_ambiguous_lengths() -> None:
    from app.templates.transforms import _timestamp

    with pytest.raises(ValueError):
        _timestamp("12345", "epoch_auto", UTC)


# --- shared lookup tables, join, replace, coalesce, optional envelope ----------------------


def _table() -> Any:
    from app.templates.tables import LookupTable

    return LookupTable.model_validate(
        {
            "schema_version": 1,
            "id": "demo_ids",
            "entries": {
                "Security:4625": {
                    "class_uid": 3002,
                    "activity_id": 1,
                    "status_id": 2,
                    "label": "An account failed to log on",
                },
                "Security:4720": {"class_uid": 3001, "activity_id": 1},
            },
        }
    )


def _json_template(**mapping: Any) -> Template:
    d: dict[str, Any] = {
        "schema_version": 1,
        "id": "demo_json",
        "name": "Demo",
        "version": "1.0.0",
        "category": "identity",
        "vendor": "windows",
        "envelope": {"type": "syslog", "optional": True},
        "payload": {"format": "json"},
        "transforms": [
            {"field": "Channel", "op": "join", "args": {"with": ["EventID"], "into": "key"}},
            {"field": "Host", "op": "replace", "args": {"pattern": "\\.corp$", "with": ""}},
        ],
        "mapping": {
            "class_uid": 0,
            "lookup": {"field": "key", "table": "demo_ids"},
            "fields": {
                "device_hostname": {"from": "Host"},
                "actor_user_name": {"from": ["TargetUserName", "SubjectUserName"]},
                "status_id": {"from": "St"},
            },
            **mapping,
        },
        "tests": [
            {"name": f"t{i}", "input": "{}", "expect": {"parse_status": "ok"}} for i in range(3)
        ],
    }
    return Template.model_validate(d)


def test_lookup_table_classifies_and_fills_unset_columns() -> None:
    t = TemplateNormalizer(
        _json_template(), "win", clock=lambda: NOW, tables={"demo_ids": _table()}
    )
    row = t.normalize(
        line(
            '{"Channel":"Security","EventID":4625,"Host":"dc01.corp",'
            '"TargetUserName":"-","SubjectUserName":"svc_backup"}'
        )
    )
    assert (row["class_uid"], row["category_uid"]) == (3002, 3)
    assert (row["activity_id"], row["status_id"]) == (1, 2)
    assert row["message"] == "An account failed to log on"
    assert row["device_hostname"] == "dc01"  # replace
    assert row["actor_user_name"] == "svc_backup"  # "-" is no value, so the next source wins
    assert row["parse_status"] == "ok"  # no syslog header is fine when the envelope is optional
    assert json.loads(row["unmapped"]).get("key") is None  # the lookup key counts as used


def test_lookup_never_overrides_mapped_values_and_unknown_keys_stay_default() -> None:
    t = TemplateNormalizer(
        _json_template(), "win", clock=lambda: NOW, tables={"demo_ids": _table()}
    )
    row = t.normalize(line('{"Channel":"Security","EventID":4625,"St":1}'))
    assert row["status_id"] == 1  # the event's own value wins over the table
    row = t.normalize(line('{"Channel":"Security","EventID":9999}'))
    assert (row["class_uid"], row["activity_id"]) == (0, None)
    row = t.normalize(line('{"EventID":4625}'))  # join of a missing field: key "4625"
    assert row["class_uid"] == 0


def test_class_by_match_beats_the_lookup_table() -> None:
    t = TemplateNormalizer(
        _json_template(class_by={"field": "Kind", "values": {"special": 6003}}),
        "win",
        clock=lambda: NOW,
        tables={"demo_ids": _table()},
    )
    row = t.normalize(line('{"Channel":"Security","EventID":4720,"Kind":"special"}'))
    assert row["class_uid"] == 6003 and row["activity_id"] == 1
    row = t.normalize(line('{"Channel":"Security","EventID":4720,"Kind":"other"}'))
    assert row["class_uid"] == 3001


def test_missing_lookup_table_is_a_load_problem(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="demo_ids"):
        TemplateNormalizer(_json_template(), "win", clock=lambda: NOW)


def test_required_envelope_still_flags_missing_header() -> None:
    d = _json_template().model_dump(by_alias=True)
    d["envelope"]["optional"] = False
    t = TemplateNormalizer(
        Template.model_validate(d), "win", clock=lambda: NOW, tables={"demo_ids": _table()}
    )
    row = t.normalize(line('{"Channel":"Security","EventID":4720}'))
    assert row["parse_status"] == "partial" and "no_syslog_header" in row["parse_errors"]


def test_lookup_tables_validate_strictly(tmp_path: Path) -> None:
    from app.templates.tables import load_tables

    (tmp_path / "good_map.yaml").write_text(
        "schema_version: 1\nid: good_map\nentries: {a: {class_uid: 3002}}\n"
    )
    (tmp_path / "wrong_name.yaml").write_text("schema_version: 1\nid: other\nentries: {}\n")
    (tmp_path / "bad_map.yaml").write_text(
        "schema_version: 1\nid: bad_map\nentries: {a: {class_uid: 3002, extra: 1}}\n"
    )
    (tmp_path / "evil.yaml").write_text("!!python/object/apply:os.system ['true']\n")
    tables, problems = load_tables(tmp_path)
    assert list(tables) == ["good_map"]
    assert sorted(p[0] for p in problems) == ["bad_map.yaml", "evil.yaml", "wrong_name.yaml"]


def test_timestamp_format_list_tries_each_in_order() -> None:
    from app.templates.transforms import TransformRunner
    from app.templates.validator import Transform

    step = Transform.model_validate(
        {"field": "t", "op": "timestamp", "args": {"format": ["iso8601", "%m/%d/%Y %H:%M:%S"]}}
    )
    for value, iso in [
        ("2026-10-09T20:41:12Z", "2026-10-09T20:41:12+00:00"),
        ("10/09/2026 20:41:12", "2026-10-09T20:41:12+00:00"),
    ]:
        fields: dict[str, Any] = {"t": value}
        assert TransformRunner([step], UTC).apply(fields) == []
        assert fields["t"].isoformat() == iso
    fields = {"t": "not a time"}
    assert TransformRunner([step], UTC).apply(fields) == ["transform_timestamp:t"]


@pytest.mark.parametrize(
    "args",
    [
        {"op": "join", "args": {"with": "EventID", "into": "k"}},
        {"op": "join", "args": {"with": ["EventID"]}},
        {"op": "replace", "args": {"pattern": "(", "with": ""}},
        {"op": "replace", "args": {"pattern": "a", "with": 5}},
        {"op": "timestamp", "args": {"format": []}},
        {"op": "timestamp", "args": {"format": ["iso8601", 3]}},
    ],
)
def test_new_transform_args_are_checked(args: dict[str, Any]) -> None:
    from app.templates.validator import Transform

    with pytest.raises(ValueError):
        Transform.model_validate({"field": "x", **args})


def test_replace_is_bounded_on_hostile_input() -> None:
    from app.templates.transforms import TransformRunner
    from app.templates.validator import Transform

    step = Transform.model_validate(
        {"field": "q", "op": "replace", "args": {"pattern": "\\(\\d+\\)", "with": "."}}
    )
    fields: dict[str, Any] = {"q": "(3)www(7)example(3)com(0)"}
    TransformRunner([step], UTC).apply(fields)
    assert fields["q"] == ".www.example.com."
    started = time.monotonic()
    fields = {"q": "(" * 10_000}
    TransformRunner([step], UTC).apply(fields)
    assert time.monotonic() - started < 2


def _actor_template(**envelope: Any) -> Template:
    d = _json_template().model_dump(by_alias=True, exclude_none=True)
    del d["mapping"]["fields"]["actor_user_name"]
    d["mapping"]["lookup"]["actor"] = {"subject": ["SubjectUserName"], "target": ["TargetUserName"]}
    d["envelope"].update(envelope)
    return Template.model_validate(d)


def test_actor_comes_from_the_role_the_table_names() -> None:
    table = _table()
    table.entries["Security:4625"].actor = "target"
    t = TemplateNormalizer(_actor_template(), "win", clock=lambda: NOW, tables={"demo_ids": table})
    logon = '{"Channel":"Security","EventID":4625,"SubjectUserName":"DC01$","TargetUserName":"bob"}'
    assert t.normalize(line(logon))["actor_user_name"] == "bob"
    created = (
        '{"Channel":"Security","EventID":4720,"SubjectUserName":"alice","TargetUserName":"erin"}'
    )
    assert t.normalize(line(created))["actor_user_name"] == "alice"
    # No fallback to the other role: an empty Target never becomes the computer account.
    empty = '{"Channel":"Security","EventID":4625,"SubjectUserName":"DC01$","TargetUserName":"-"}'
    assert t.normalize(line(empty))["actor_user_name"] is None
    unknown = '{"Channel":"System","EventID":1,"SubjectUserName":"carol","TargetUserName":"x"}'
    assert t.normalize(line(unknown))["actor_user_name"] == "carol"


def test_actor_cannot_be_mapped_twice() -> None:
    d = _json_template().model_dump(by_alias=True, exclude_none=True)
    d["mapping"]["lookup"]["actor"] = {"subject": ["S"], "target": ["T"]}
    with pytest.raises(ValueError, match="not both"):
        Template.model_validate(d)


def test_envelope_defaults_can_be_limited() -> None:
    forwarded = '<14>Oct  9 20:41:12 DC01 Microsoft-Windows-Security-Auditing[4]: {"EventID":1}'
    tables = {"demo_ids": _table()}
    every = TemplateNormalizer(_actor_template(), "win", clock=lambda: NOW, tables=tables)
    row = every.normalize(line(forwarded))
    assert row["actor_process_name"] == "Microsoft-Windows-Security-Auditing"
    limited = TemplateNormalizer(
        _actor_template(defaults=["time", "device_hostname"]),
        "win",
        clock=lambda: NOW,
        tables=tables,
    )
    row = limited.normalize(line(forwarded))
    assert row["device_hostname"] == "DC01" and row["time"] is not None
    assert row["actor_process_name"] is None and row["actor_process_pid"] is None
    assert row["message"] is None


def test_pick_copies_the_field_the_value_names() -> None:
    from app.templates.transforms import TransformRunner
    from app.templates.validator import Transform

    steps = [
        Transform.model_validate(
            {
                "field": "dir",
                "op": "pick",
                "args": {"from": {"in": "remote", "out": "local"}, "into": "src"},
            }
        )
    ]
    for direction, want in (("in", "203.0.113.9"), ("out", "10.20.1.5")):
        fields: dict[str, Any] = {"dir": direction, "remote": "203.0.113.9", "local": "10.20.1.5"}
        assert TransformRunner(steps, UTC).apply(fields) == []
        assert fields["src"] == want
    for odd in ("sideways", {"in": 1}, ["in"]):
        fields = {"dir": odd, "remote": "x"}
        assert TransformRunner(steps, UTC).apply(fields) == [] and "src" not in fields


def test_optional_map_leaves_the_target_alone() -> None:
    from app.templates.transforms import TransformRunner
    from app.templates.validator import Transform

    steps = [
        Transform.model_validate(
            {"field": "k", "op": "map", "args": {"into": "o", "values": {"a": 1}, "optional": True}}
        )
    ]
    fields: dict[str, Any] = {"k": "zzz", "o": 2}
    assert TransformRunner(steps, UTC).apply(fields) == [] and fields["o"] == 2
    fields = {"k": "a"}
    TransformRunner(steps, UTC).apply(fields)
    assert fields["o"] == 1
    with pytest.raises(ValueError, match="not both"):
        Transform.model_validate(
            {"field": "k", "op": "map", "args": {"values": {}, "optional": True, "default": 0}}
        )


def test_replace_output_is_capped() -> None:
    from app.templates.transforms import TransformRunner
    from app.templates.validator import Transform

    grow = Transform.model_validate(
        {"field": "q", "op": "replace", "args": {"pattern": "", "with": "x" * 50}}
    )
    fields: dict[str, Any] = {"q": "a" * 2000}
    assert TransformRunner([grow], UTC).apply(fields) == ["transform_replace:q"]
    assert fields["q"] is None


def test_target_account_stays_in_unmapped_when_the_subject_acts() -> None:
    t = TemplateNormalizer(
        _actor_template(), "win", clock=lambda: NOW, tables={"demo_ids": _table()}
    )
    created = (
        '{"Channel":"Security","EventID":4720,"SubjectUserName":"alice","TargetUserName":"erin"}'
    )
    row = t.normalize(line(created))
    assert row["actor_user_name"] == "alice"
    leftover = json.loads(row["unmapped"])
    assert leftover.get("TargetUserName") == "erin" and "SubjectUserName" not in leftover
