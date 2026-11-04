"""D186 (owner, 2026-11-03): Claude Code's own bookkeeping (a subagent handing back its
result) came in as a tool call and showed as a "New tool" and in tool counts. It is left
out of new items, tool lists, and every tool count; the records stay in the timeline."""

from datetime import timedelta
from typing import Any

from app.ai.agents import agents
from app.ai.agents_overview import overview
from app.ai.sessions import sessions, timeline
from app.ingest.writer import LakeWriter
from tests.integration.test_ai_usage import lab, usage  # noqa: F401  # the fixture
from tests.integration.test_m365_consents import _row
from tests.integration.test_schedules import NOW

HOOK = "a failed tool call from the Windows plugin names the Claude account"


def _hook(event: str, tool: str | None, minutes: int, session: str = "h-9") -> dict[str, Any]:
    attr = {"event_name": event, "session_id": session, "claude_account_email": "erin@example.com",
            "os_user": "erin"}  # fmt: skip
    if tool:
        attr["tool_name"] = tool
    when = (NOW - timedelta(minutes=minutes)).isoformat()
    return _row("claude_hooks", HOOK, "claude", time=when, event=event, attr=attr)


def test_claude_code_bookkeeping_is_not_a_tool(lab: dict[str, Any]) -> None:  # noqa: F811
    old = 60 * 24 * 5  # five days ago: the baseline
    LakeWriter(lab["app"].state.engine._lake).write(
        [
            _hook("claude_hooks.session_start", None, old, "h-old"),
            _hook("claude_hooks.pre_tool_use", "Read", old - 1, "h-old"),
            _hook("claude_hooks.session_start", None, 30),
            _hook("claude_hooks.pre_tool_use", "Bash", 29),
            _hook("claude_hooks.pre_tool_use", "SubagentHandback", 28),
            _hook("claude_hooks.post_tool_use_failure", "SubagentHandback", 27),
        ]
    )
    a = lab["admin"]
    erin = next(
        x for x in agents(lab["app"].state.engine, None, NOW + timedelta(hours=1))
        if x.agent == "cc|erin@example.com"
    )  # fmt: skip
    assert {"kind": "Tool", "name": "Bash"} in erin.new_items
    assert not any(i["name"] == "SubagentHandback" for i in erin.new_items)
    engine, later = lab["app"].state.engine, NOW + timedelta(hours=1)
    session = next(x for x in sessions(engine, None, later, 7) if x.session_id == "h-9")
    assert session.tools == ["Bash"] and session.tool_calls == 1 and session.failed == 0
    over = overview(engine, lab["app"].state.ai_catalog, ["claude"], later, 7)
    tools = {t.tool for t in over.tools}
    assert "Bash" in tools and "SubagentHandback" not in tools
    person = next(p for p in usage(a)["people"] if p["person"] == "erin@example.com")
    assert (person["tool_calls"], person["errors"]) == (2, 0)  # Read and Bash
    # Still in the session's timeline: the records are kept.
    steps = timeline(engine, None, "h-9", later, 7).steps
    assert any(x.tool == "SubagentHandback" for x in steps)
