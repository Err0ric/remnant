"""ADR-0038 section 6: Agents > Overview and Tools from the hooks plugin's records."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.ai.agents_overview import overview
from app.ingest.writer import LakeWriter
from tests.integration.test_m365_consents import _row
from tests.integration.test_schedules import make_lab

NOW = datetime(2026, 10, 30, tzinfo=UTC)
HOOK = "a failed tool call from the Windows plugin names the Claude account"


def _hook(event: str, session: str, when: str, **attr: Any) -> dict[str, Any]:
    a = {"event_name": event, "session_id": session, "tool_name": "Bash"} | attr
    return _row("claude_hooks", HOOK, "hooks", time=when, event=event, attr=a)


def test_overview_counts_and_tools(tmp_path: Path) -> None:
    lab = make_lab(tmp_path)
    engine, catalog = lab["app"].state.engine, lab["app"].state.ai_catalog
    catalog.set_mcp_rule("evil-mcp", "not_approved", "", "admin")
    rows = [
        _hook("claude_hooks.pre_tool_use", "s-1", "2026-10-29T10:00:00+00:00"),
        _hook("claude_hooks.pre_tool_use", "s-1", "2026-10-29T10:01:00+00:00"),
        _hook("claude_hooks.post_tool_use_failure", "s-1", "2026-10-29T10:01:05+00:00"),
        _hook(
            "claude_hooks.pre_tool_use", "s-2", "2026-10-29T11:00:00+00:00",
            tool_name="mcp__evil-mcp__read", mcp_server_name="evil-mcp",
        ),
        # The week before: one session, one call.
        _hook("claude_hooks.pre_tool_use", "s-0", "2026-10-20T09:00:00+00:00"),
    ]  # fmt: skip
    LakeWriter(engine._lake).write(rows)
    out = overview(engine, catalog, ["hooks"], NOW, 7)
    assert out.sessions is not None and (out.sessions.value, out.sessions.before) == (2, 1)
    assert out.calls is not None and (out.calls.value, out.calls.before) == (3, 1)
    assert out.failed is not None and out.failed.value == 1
    assert out.mcp_not_approved is not None and out.mcp_not_approved.value == 1
    assert out.mcp_not_approved.drill and "evil-mcp" in out.mcp_not_approved.drill
    tools = {t.tool: t for t in out.tools}
    assert tools["Bash"].status == "built_in" and tools["Bash"].calls == 2
    assert tools["Bash"].failed == 1
    assert tools["evil-mcp"].mcp and tools["evil-mcp"].status == "not_approved"
    assert all(t.drill for t in out.tools)


def test_no_hooks_source_says_so(tmp_path: Path) -> None:
    lab = make_lab(tmp_path)
    out = overview(lab["app"].state.engine, lab["app"].state.ai_catalog, [], NOW, 7)
    assert not out.has_source and out.sessions is None and out.tools == []
