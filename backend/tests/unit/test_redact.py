"""Opt-in redaction (ADR-0010, D36): tokens, text, tables, reverse map."""

import json

from app.llm.gate import data_message
from app.llm.provider import ChatMessage, ProviderResponse, ToolCall
from app.llm.redact import Redactor, derive_key

KEY = derive_key(b"install-key-for-tests")


def payload(m: ChatMessage) -> object:
    return json.loads(m.content)["data"]


def test_tokens_are_stable_kind_prefixed_8_hex_and_keyed() -> None:
    a, b = Redactor(KEY), Redactor(KEY)
    t = a.token("IP", "203.0.113.9")
    assert t.startswith("IP_") and len(t) == 11 and t == b.token("IP", "203.0.113.9")
    assert a.token("USER", "Admin") == a.token("USER", "admin")  # names ignore case
    assert a.token("IP", "2001:DB8::1") == a.token("IP", "2001:db8:0::1")  # canonical form
    assert Redactor(derive_key(b"other")).token("IP", "203.0.113.9") != t


def test_columns_and_the_raw_line_hide_the_same_values() -> None:
    r = Redactor(KEY)
    event = {
        "event_id": "01a126d0-7c4f-7012-b6b0-e17359887d5f",
        "time": "2026-10-10T12:30:01Z",
        "actor_user_name": "jdoe",
        "device_hostname": "bastion-01",
        "src_endpoint_ip": "203.0.113.9",
        "src_endpoint_port": 51234,
        "raw": "<38>Oct 10 12:30:01 bastion-01 sshd[7]: Failed password for jdoe from"
        " 203.0.113.9 port 51234 ssh2; contact JDoe@example.com, peer 2001:db8::7",
    }
    (out,) = r.messages([data_message({"events": [event]}, ["auth"])])
    sent = payload(out)["events"][0]  # type: ignore[index]  # test data
    text = json.dumps(sent)
    for secret in ("jdoe", "bastion-01", "203.0.113.9", "example.com", "2001:db8::7"):
        assert secret not in text.lower()
    assert sent["event_id"] == event["event_id"] and sent["src_endpoint_port"] == 51234
    assert "12:30:01" in sent["raw"]  # times are not addresses
    assert sent["actor_user_name"] in sent["raw"] and sent["device_hostname"] in sent["raw"]
    assert r.counts == {"USER": 2, "HOST": 1, "IP": 2}


def test_preview_tables_sample_values_questions_and_earlier_sql() -> None:
    r = Redactor(KEY)
    msgs = [
        data_message(
            {"sample_values": {"actor_user_name": ["root", "svc_backup"], "status_id": [1, 2]}},
            ["auth"],
        ),
        ChatMessage("user", "Why did 198.51.100.4 log in as svc_backup?"),
        ChatMessage(
            "assistant",
            "",
            tool_calls=(
                ToolCall(
                    "t1", "preview_query", '{"sql": "WHERE src_endpoint_ip = \'198.51.100.4\'"}'
                ),
            ),
        ),
        data_message(
            {"columns": ["src_endpoint_ip", "n"], "rows": [["198.51.100.4", 3]]},
            ["auth"],
            role="tool",
            tool_call_id="t1",
        ),
    ]
    sample, question, ask, table = r.messages(msgs)
    assert payload(sample) == {
        "sample_values": {
            "actor_user_name": [r.token("USER", "root"), r.token("USER", "svc_backup")],
            "status_id": [1, 2],
        }
    }
    ip = r.token("IP", "198.51.100.4")
    assert question.content == f"Why did {ip} log in as {r.token('USER', 'svc_backup')}?"
    assert ip in ask.tool_calls[0].arguments and "198.51" not in ask.tool_calls[0].arguments
    assert payload(table) == {"columns": ["src_endpoint_ip", "n"], "rows": [[ip, 3]]}


def test_short_names_are_not_hunted_in_text() -> None:
    r = Redactor(KEY)
    (_, text) = r.messages(
        [data_message({"actor_user_name": "bo"}, ["a"]), ChatMessage("user", "bob bo boat")]
    )
    assert text.content == "bob bo boat"


def test_the_reply_gets_real_values_back_and_unknown_tokens_stay() -> None:
    r = Redactor(KEY)
    ip, user = r.token("IP", "203.0.113.9"), r.token("USER", "jdoe")
    reply = ProviderResponse(
        text=f'{{"sql": "SELECT * FROM events WHERE src_endpoint_ip = \'{ip}\'", "note": "{user} and IP_deadbeef"}}',
        model="m",
        tool_calls=[ToolCall("t", "preview_query", json.dumps({"sql": f"WHERE x = '{ip}'"}))],
    )
    back = r.restore(reply)
    assert "203.0.113.9" in back.text and "jdoe" in back.text and "IP_deadbeef" in back.text
    assert "203.0.113.9" in back.tool_calls[0].arguments


def test_system_messages_are_untouched() -> None:
    (out,) = Redactor(KEY).messages([ChatMessage("system", "rules for 10.0.0.1")])
    assert out.content == "rules for 10.0.0.1"
