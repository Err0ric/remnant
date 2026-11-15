"""One agent session in numbers (BACKLOG P1, the session detail's KPI row):
`GET /api/ai/sessions/{id}/summary`, counted on the server over the whole session, and the
steps of `GET /api/ai/sessions/{id}` with their type. Synthetic data."""

import json
import sqlite3
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ai.sessions import MAX_STEPS
from app.ingest.writer import LakeWriter
from tests.integration.test_ai_usage import lab  # noqa: F401  # the fixture
from tests.integration.test_m365_consents import _row
from tests.integration.test_schedules import BASE, NOW

HOOK = "a failed tool call from the Windows plugin names the Claude account"
MIDNIGHT = NOW.replace(hour=0)  # the session runs from 23:50 to 00:20 UTC
START = MIDNIGHT - timedelta(minutes=10)
CALL, OK, FAIL = (
    "claude_hooks.pre_tool_use",
    "claude_hooks.post_tool_use",
    "claude_hooks.post_tool_use_failure",
)


def _h(event: str, session: str, at: datetime, **attr: Any) -> dict[str, Any]:
    a = {"event_name": event, "session_id": session, "claude_account_email": "alice@example.com",
         "os_user": "alice", **attr}  # fmt: skip
    return _row(
        "claude_hooks", HOOK, "claude", time=at.isoformat(), event=event, attr=a,
        resource={"service_name": "claude-hooks", "host_name": "ws-0040"},
    )  # fmt: skip


def _tokens(session: str, at: datetime, kind: str, value: float) -> dict[str, Any]:
    return _row(
        "claude_code_otel", "cost metric data point", "claude", time=at.isoformat(),
        metric="claude_code.token.usage", unit="tokens", value=value,
        attr={"user_email": "alice@example.com", "session_id": session, "type": kind},
    )  # fmt: skip


def _session(seq: bool = False) -> list[dict[str, Any]]:
    """Two prompts and eight tool calls across midnight UTC, in /home/alice/app. With `seq`,
    each record carries the plugin's install id and sequence number (ADR-0026 offline
    queue), so a second send of the same batch is the same records again."""
    rows = _records()
    if seq:
        for i, r in enumerate(rows):
            attr = json.loads(r["unmapped"])["attr"]
            attr.update(install_id="inst-0040", seq=str(i + 1))
            r["unmapped"] = json.dumps({**json.loads(r["unmapped"]), "attr": attr})
    return rows


def _records() -> list[dict[str, Any]]:
    t = iter(START + timedelta(minutes=m) for m in range(0, 31))
    rows = [
        _h("claude_hooks.session_start", "s-sum", next(t), cwd="/home/alice/app"),
        _h("claude_hooks.user_prompt_submit", "s-sum", next(t), prompt_chars="40"),
    ]
    for tool, extra, result in (
        ("Read", {"path": "/home/alice/app/a.py"}, OK),
        ("Write", {"path": "/etc/hosts"}, OK),  # outside the folder
        ("Edit", {"path": "src/b.py"}, OK),  # relative: inside
        ("Write", {"path": "/home/alice/app/c.py"}, OK),
        ("Bash", {"program": "git"}, FAIL),
        ("WebFetch", {"web_host": "docs.example.com"}, OK),
        ("mcp__notes__add", {"mcp_server_name": "notes", "mcp_tool_name": "add"}, None),
        ("SubagentHandback", {}, OK),  # Claude Code bookkeeping (D186)
    ):
        when = next(t)
        rows.append(_h(CALL, "s-sum", when, tool_name=tool, **extra))
        if result:
            rows.append(_h(result, "s-sum", when, tool_name=tool, **extra))
        if tool == "Bash":
            rows.append(_h("claude_hooks.user_prompt_submit", "s-sum", next(t)))
    rows.append(_h("claude_hooks.stop", "s-sum", next(t)))
    rows.append(_h("claude_hooks.session_end", "s-sum", START + timedelta(minutes=30)))
    return rows


@pytest.fixture
def summary_lab(lab: dict[str, Any], pin_now: Callable[[datetime], None]) -> dict[str, Any]:  # noqa: F811
    pin_now(NOW)
    LakeWriter(lab["app"].state.engine._lake).write(_session())
    return lab


def _get(client: Any, session: str = "s-sum", **params: Any) -> Any:
    res = client.get(f"/api/ai/sessions/{session}/summary", params=params)
    assert res.status_code == 200, res.text
    return res.json()


def test_the_summary_counts_the_whole_session(summary_lab: dict[str, Any]) -> None:
    s = _get(summary_lab["admin"])
    end = START + timedelta(minutes=30)
    assert (s["started"], s["last"]) == (START.isoformat(), end.isoformat())
    assert s["length_s"] == 1800 and s["state"] == "ended"
    assert (s["prompts"], s["tool_calls"], s["failed"], s["unanswered"]) == (2, 7, 1, 1)
    assert (s["files"], s["files_outside"]) == (4, 1)
    assert s["new_mcp"] == ["notes"]
    assert (s["tokens_in"], s["tokens_out"]) == (None, None)  # "Not reported", never 0
    assert s["types"] == {
        "prompt": 2, "tool_call": 2, "file_access": 4, "access": 2, "tool_result": 7, "other": 3,
    }  # fmt: skip
    assert (s["steps"], s["steps_cut"]) == (20, False)
    # Show events in Logs: the session's records, the window bound by Logs.
    assert "template_id = 'claude_hooks'" in s["sql"] and "'s-sum'" in s["sql"]
    res = summary_lab["admin"].post(
        "/api/query",
        json={
            "sql": s["sql"]
            .replace("{from}", START.isoformat())
            .replace("{to}", (end + timedelta(seconds=1)).isoformat())
        },
        headers=summary_lab["h"],
    )
    assert res.status_code == 200, res.text
    assert len(res.json()["rows"]) == 20
    assert (s["person"], s["account"], s["machine"], s["masked"]) == (
        "alice@example.com", "alice@example.com", "ws-0040", False,
    )  # fmt: skip
    # The steps carry the same types the summary counts.
    t = summary_lab["admin"].get("/api/ai/sessions/s-sum").json()
    assert Counter(x["type"] for x in t["steps"]) == {k: v for k, v in s["types"].items() if v}
    # Bookkeeping is marked by the same rule the counts use, so the page never flags it.
    assert {x["tool"] for x in t["steps"] if not x["counted"]} == {"SubagentHandback"}
    first = {x["event"]: x["type"] for x in t["steps"]}
    assert first["user_prompt_submit"] == "prompt" and first["session_start"] == "other"


def test_tokens_only_when_telemetry_reported_them(summary_lab: dict[str, Any]) -> None:
    near = START + timedelta(minutes=35)  # sent after the last hook record
    LakeWriter(summary_lab["app"].state.engine._lake).write([
        _tokens("s-sum", near, "input", 1000), _tokens("s-sum", near, "cacheRead", 500),
        _tokens("s-sum", near, "output", 300), _tokens("s-other", near, "output", 9999),
    ])  # fmt: skip
    s = _get(summary_lab["admin"])
    assert (s["tokens_in"], s["tokens_out"]) == (1500, 300)


def test_a_session_longer_than_the_steps_list(summary_lab: dict[str, Any]) -> None:
    n = MAX_STEPS + 5
    LakeWriter(summary_lab["app"].state.engine._lake).write(
        [_h(CALL, "s-long", START + timedelta(seconds=i), tool_name="Bash") for i in range(n)]
    )
    s = _get(summary_lab["admin"], "s-long")
    assert (s["steps"], s["steps_cut"], s["tool_calls"], s["types"]["tool_call"]) == (
        n, True, n, n,
    )  # fmt: skip
    assert s["state"] == "idle"  # no stop and nothing for the idle time
    t = summary_lab["admin"].get("/api/ai/sessions/s-long").json()
    assert len(t["steps"]) == MAX_STEPS


def _types_on_steps(client: Any, session: str) -> dict[str, int]:
    steps = client.get(f"/api/ai/sessions/{session}").json()["steps"]
    return dict(Counter(x["type"] for x in steps))


def test_a_batch_sent_twice_counts_once(summary_lab: dict[str, Any]) -> None:
    once = _get(summary_lab["admin"])
    lake = LakeWriter(summary_lab["app"].state.engine._lake)
    for _ in range(2):  # the same batch twice, as the plugin resends one whose answer was lost
        lake.write([
            {**r, "unmapped": r["unmapped"].replace('"s-sum"', '"s-again"')}
            for r in _session(seq=True)
        ])  # fmt: skip
    again = _get(summary_lab["admin"], "s-again")
    # The same numbers; the id and the Logs query name the other session.
    assert {**again, "session_id": "s-sum", "sql": once["sql"]} == once
    assert _types_on_steps(summary_lab["admin"], "s-again") == {
        k: v for k, v in again["types"].items() if v
    }


def test_empty_fields_type_alike_in_the_summary_and_the_steps(
    summary_lab: dict[str, Any],
) -> None:
    at = START + timedelta(hours=2)
    LakeWriter(summary_lab["app"].state.engine._lake).write([
        _h(CALL, "s-empty", at, tool_name="WebFetch", web_host=""),
        _h(CALL, "s-empty", at, tool_name="Read", path=""),
        _h(CALL, "s-empty", at, tool_name="mcp__x__y", mcp_server_name=""),
        _h(CALL, "s-empty", at, tool_name="Read", path="/home/alice/app/a.py"),
    ])  # fmt: skip
    s = _get(summary_lab["admin"], "s-empty")
    assert (s["types"]["tool_call"], s["types"]["file_access"], s["types"]["access"]) == (3, 1, 0)
    assert _types_on_steps(summary_lab["admin"], "s-empty") == {"tool_call": 3, "file_access": 1}


def test_sign_in_and_sources(summary_lab: dict[str, Any]) -> None:
    res = TestClient(summary_lab["app"], base_url=BASE).get("/api/ai/sessions/s-sum/summary")
    assert res.status_code == 401
    # ana reads only the Linux source here: the session is not one she can read.
    res = summary_lab["ana"].get("/api/ai/sessions/s-sum/summary")
    assert res.status_code == 404
    assert "alice" not in res.text
    assert summary_lab["admin"].get("/api/ai/sessions/s-none/summary").status_code == 404
    assert summary_lab["admin"].get(f"/api/ai/sessions/{'x' * 201}/summary").status_code == 400


def test_the_summary_is_audited_as_one_session(summary_lab: dict[str, Any]) -> None:
    _get(summary_lab["admin"], days=7)
    with sqlite3.connect(summary_lab["db"]) as con:
        rows = [
            (a, json.loads(d))
            for a, d in con.execute("SELECT action, detail FROM audit_log ORDER BY audit_id")
        ]
    (row,) = [(a, d) for a, d in rows if d.get("surface") == "ai.session_summary"]
    assert row[0] == "ai.view_people"
    assert row[1]["session_id"] == "s-sum" and row[1]["sources_in_scope"] is None
    assert row[1]["start"] == (NOW - timedelta(days=7)).isoformat()
