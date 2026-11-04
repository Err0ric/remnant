"""The ai_agents library pack on hooks records built for the cases the shared fixture lacks:
a personal account, a company account confirmed by a sign-in, a call with no result, a
failed call, and Claude Code bookkeeping (SubagentHandback), which is never a tool."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.core.config import load_config
from app.engine.duckdb import QueryScope
from app.ingest.records import DecodedLine
from app.ingest.writer import LakeWriter
from app.main import create_app
from app.search.identity import identity_values
from app.search.library import LIBRARY_DIR, load
from app.search.params import bind, compile_sql
from app.templates.loader import parse_template
from app.templates.runtime import TemplateNormalizer

ROOT = Path(__file__).resolve().parents[3]
PACK = load(LIBRARY_DIR / "ai_agents" / "pack.yaml")
START, END = datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC)


def _hook(t: str, event: str, session: str, host: str, **attr: Any) -> str:
    return json.dumps({
        "signal": "log", "time": t, "service": "claude-hooks", "event": event,
        "attr": {"event_name": event, "session_id": session, **attr},
        "body": event, "resource": {"service_name": "claude-hooks", "host_name": host},
        "content": "dropped",
    })  # fmt: skip


def _signin(t: str, who: str) -> str:
    return json.dumps({
        "id": "0b1c", "createdDateTime": t, "userPrincipalName": who, "appDisplayName": "Claude",
        "ipAddress": "203.0.113.9", "status": {"errorCode": 0},
    })  # fmt: skip


PRE, POST, FAIL = (
    "claude_hooks.pre_tool_use", "claude_hooks.post_tool_use", "claude_hooks.post_tool_use_failure",
)  # fmt: skip
DANA = {"claude_account_email": "dana@example.org", "os_user": "dana"}  # personal
ERIN = {"claude_account_email": "erin@example.com", "os_user": "erin"}  # company, signed in
HOOKS = [
    _hook("2026-10-20T10:00:00Z", PRE, "s1", "ws-alpha", tool_name="Bash", program="git", **DANA),
    _hook("2026-10-20T10:00:01Z", POST, "s1", "ws-alpha", tool_name="Bash", **DANA),
    _hook("2026-10-20T10:01:00Z", PRE, "s1", "ws-alpha", tool_name="Bash", program="rm", **DANA),
    _hook("2026-10-20T10:02:00Z", PRE, "s1", "ws-alpha", tool_name="SubagentHandback", **DANA),
    _hook(
        "2026-10-20T10:03:00Z",
        PRE,
        "s1",
        "ws-alpha",
        tool_name="Write",
        path="/home/dana/notes.md",
        **DANA,
    ),
    _hook("2026-10-20T10:03:01Z", FAIL, "s1", "ws-alpha", tool_name="Write", **DANA),
    _hook("2026-10-21T09:00:00Z", PRE, "s2", "ws-zulu", tool_name="Read", **ERIN),
    _hook("2026-10-21T09:00:01Z", POST, "s2", "ws-zulu", tool_name="Read", **ERIN),
    # Test records (installer doctor, Send a test record): no person, no machine.
    *[
        json.dumps(
            {
                "signal": "log",
                "time": "2026-10-22T08:00:00Z",
                "service": "claude-hooks",
                "event": "claude_hooks.session_start",
                "attr": {
                    "event_name": "claude_hooks.session_start",
                    "session_id": sid,
                    "plugin_variant": variant,
                    "test_record": "true",
                },
                "body": "claude_hooks.session_start",
                "resource": {"service_name": "claude-hooks"},
            }
        )
        for sid, variant in (("doctor-1", "doctor"), ("server-test-1", "server_test"))
    ],
]


@pytest.fixture(scope="module")
def engine(tmp_path_factory: pytest.TempPathFactory) -> Any:
    tmp = tmp_path_factory.mktemp("agents")
    config = load_config(Path("missing.yaml"), {"APP__PATHS__DATA_DIR": str(tmp / "data")})
    app = create_app(config)
    rows = []
    for template, lines in (("claude_hooks", HOOKS), ("m365_signin", [_signin(
        "2026-10-15T08:00:00Z", "erin@example.com"
    )])):  # fmt: skip
        spec = parse_template((ROOT / "templates" / "starter" / f"{template}.yaml").read_text())
        norm = TemplateNormalizer(spec, template)
        rows += [norm.normalize(DecodedLine(text=x, bytes_invalid=False, truncated=False))
                 for x in lines]  # fmt: skip
    LakeWriter(app.state.engine._lake).write(rows)
    return app.state.engine


def _run(engine: Any, qid: str, **params: Any) -> list[dict[str, Any]]:
    q = next(x for x in PACK.queries if x.id == qid)
    values = bind(q.params, params, START, END, q.sql) | identity_values(q.sql, None)
    res = engine.run(compile_sql(q.sql), QueryScope(None, START, END), values)
    return [dict(zip(res.columns, r, strict=True)) for r in res.rows]


def test_bookkeeping_is_not_a_tool(engine: Any) -> None:
    tools = {r["tool"] for r in _run(engine, "agents_tools_by_person")}
    assert tools == {"Bash", "Write", "Read"}
    s1 = next(r for r in _run(engine, "agents_sessions_for_person") if r["session_id"] == "s1")
    assert s1["tool_calls"] == 3


def test_personal_account_listed_and_confirmed_company_left_out(engine: Any) -> None:
    rows = _run(engine, "agents_accounts_by_machine", company_domain="example.com")
    assert [(r["machine"], r["account"], r["status"]) for r in rows] == [
        ("ws-alpha", "dana@example.org", "Personal")
    ]


def test_calls_with_no_result_and_failures(engine: Any) -> None:
    rows = {r["tool"]: r for r in _run(engine, "agents_calls_without_result")}
    assert rows["Bash"]["no_result"] == 1 and rows["Write"]["failed"] == 1
    assert "SubagentHandback" not in rows and "Read" not in rows


def test_person_and_path_filters(engine: Any) -> None:
    assert [r["path"] for r in _run(engine, "agents_files_by_person", path_contains="notes")] == [
        "/home/dana/notes.md"
    ]
    assert _run(engine, "agents_files_by_person", person="erin") == []
    assert {r["command"] for r in _run(engine, "agents_commands_by_person", person="dana")} == {
        "git", "rm"
    }  # fmt: skip


def test_test_records_are_in_no_query(engine: Any) -> None:
    """Owner, 2026-11-04: the doctor's record was counted as a person with a blank name.
    No query in the pack returns a test record's session or a blank person."""
    for q in PACK.queries:
        defaults = {p.name: p.default for p in q.params if p.default is not None}
        for r in _run(engine, q.id, **defaults):
            assert r.get("person", "x") not in (None, ""), (q.id, r)
            assert not str(r.get("session_id") or "").startswith(("doctor-", "server-test-"))
    people = [r["person"] for r in _run(engine, "agents_claude_code_users")]
    assert sorted(people) == ["dana@example.org", "erin@example.com"]
