"""D188 (owner, 2026-11-03): each session row says how long it ran, its prompts and tool
calls, its top three tools, files touched, web domains, and flags (a blocked or failed
call, a new MCP server, the Claude account for a personal-account check)."""

from datetime import timedelta
from typing import Any

from app.ai.sessions import sessions
from app.ingest.writer import LakeWriter
from tests.integration.test_ai_usage import lab  # noqa: F401  # the fixture
from tests.integration.test_m365_consents import _row
from tests.integration.test_schedules import NOW

HOOK = "a failed tool call from the Windows plugin names the Claude account"


def _h(event: str, session: str, minutes: int, **attr: Any) -> dict[str, Any]:
    a = {"event_name": event, "session_id": session, "claude_account_email": "Erin@Example.com",
         "os_user": "erin", **attr}  # fmt: skip
    when = (NOW - timedelta(minutes=minutes)).isoformat()
    return _row("claude_hooks", HOOK, "claude", time=when, event=event, attr=a)


CALL, OK, FAIL = (
    "claude_hooks.pre_tool_use",
    "claude_hooks.post_tool_use",
    "claude_hooks.post_tool_use_failure",
)


def test_session_rows_carry_top_tools_files_and_flags(lab: dict[str, Any]) -> None:  # noqa: F811
    rows = [_h("claude_hooks.user_prompt_submit", "s-a", 60)]
    m = 59
    for tool, extra in (
        ("Bash", {}), ("Bash", {}), ("Bash", {}),
        ("Read", {"path": "/home/erin/app/a.py"}), ("Read", {"path": "/home/erin/app/a.py"}),
        ("Edit", {"path": "/home/erin/app/b.py"}), ("Grep", {}),
    ):  # fmt: skip
        rows.append(_h(CALL, "s-a", m, tool_name=tool, **extra))
        rows.append(_h(OK, "s-a", m, tool_name=tool, **extra))
        m -= 1
    rows += [
        _h(CALL, "s-a", 40, tool_name="mcp__notes__add", mcp_server_name="notes"),  # no result
        _h(CALL, "s-a", 39, tool_name="WebFetch", web_host="docs.example.com"),
        _h(FAIL, "s-a", 39, tool_name="WebFetch", web_host="docs.example.com"),
        # A later session uses the same MCP server: not new there.
        _h(CALL, "s-b", 10, tool_name="mcp__notes__add", mcp_server_name="notes"),
        _h(OK, "s-b", 10, tool_name="mcp__notes__add", mcp_server_name="notes"),
    ]
    LakeWriter(lab["app"].state.engine._lake).write(rows)
    got = {s.session_id: s for s in sessions(lab["app"].state.engine, None, NOW, 7)}
    a, b = got["s-a"], got["s-b"]
    assert a.top_tools == ["Bash", "Read", "Edit"]  # most used; a tie goes by name
    assert a.tool_calls == 9 and a.prompts == 1
    assert a.files == 2  # distinct paths
    assert a.hosts == ["docs.example.com"]
    assert a.failed == 1 and a.unanswered == 1  # the MCP call never returned
    assert a.new_mcp == ["notes"] and b.new_mcp == []
    assert a.account == "erin@example.com"
    res = lab["admin"].get("/api/ai/sessions", params={"days": 90})
    assert res.status_code == 200, res.text
