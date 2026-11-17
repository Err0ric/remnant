"""ADR-0038 section 6: Agents > Overview and Tools from the hooks plugin's records."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.ai.agents_overview import overview
from app.ai.usage import McpUse
from app.engine.duckdb import QueryScope
from app.ingest.writer import LakeWriter
from tests.integration.test_m365_consents import _row
from tests.integration.test_schedules import make_lab

NOW = datetime(2026, 10, 30, tzinfo=UTC)
HOOK = "a failed tool call from the Windows plugin names the Claude account"


def _mcp(lab: dict[str, Any], days: int = 7) -> list[McpUse]:
    """The MCP servers table's own rows for the window (`Usage.mcp`), as the endpoint
    passes them to the overview."""
    rows: list[McpUse] = lab["app"].state.ai_usage.mcp(
        QueryScope(None, NOW - timedelta(days=days), NOW)
    )
    return rows


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
        _hook(
            "claude_hooks.pre_tool_use", "s-2", "2026-10-29T11:05:00+00:00",
            tool_name="mcp__notes__add", mcp_server_name="notes",
        ),
        # The week before: one session, one call.
        _hook("claude_hooks.pre_tool_use", "s-0", "2026-10-20T09:00:00+00:00"),
        # The hooks' data starts as the week before does, so that week is covered and
        # compared (fix list item 9: a partly covered week has no earlier values).
        _hook("claude_hooks.session_start", "s-0", "2026-10-16T01:00:00+00:00"),
    ]  # fmt: skip
    LakeWriter(engine._lake).write(rows)
    out = overview(engine, catalog, ["hooks"], NOW, 7, _mcp(lab))
    # Agents' Needs attention (fix list item 15): the not-approved and the unreviewed MCP
    # servers of the window, by the same names and rules.
    assert out.mcp_unreviewed == 1  # notes; evil-mcp is Not approved
    # The Sessions tile in parts that add up to it (PR 639): both sessions have steps.
    parts = out.session_parts
    assert out.sessions is not None
    assert parts.listed + parts.empty + parts.telemetry_only == out.sessions.value
    assert (parts.listed, parts.empty, parts.telemetry_only) == (2, 0, 0)
    assert out.sessions is not None and (out.sessions.value, out.sessions.before) == (2, 1)
    assert out.calls is not None and (out.calls.value, out.calls.before) == (4, 1)
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


def _otel(event: str, session: str, when: str, who: str, **attr: Any) -> dict[str, Any]:
    a = {"event_name": event.removeprefix("claude_code."), "user_email": who,
         "session_id": session} | attr  # fmt: skip
    return _row(
        "claude_code_otel", "tool result from an MCP server", "claude",
        time=when, event=event, attr=a,
    )  # fmt: skip


def test_overview_counts_every_agent_source(tmp_path: Path) -> None:
    """Owner, 2026-11-08: Overview counted the hooks plugin only (26 sessions, 2 people
    against AI usage's 58 and 4). Telemetry and the MCP inventory count too, a session both
    report counted once."""
    lab = make_lab(tmp_path)
    engine, catalog = lab["app"].state.engine, lab["app"].state.ai_catalog
    catalog.set_mcp_rule("evil-mcp", "not_approved", "", "admin")
    inv = _row(
        "mcp_inventory", "local stdio server from a file", "inv",
        time="2026-10-29T08:00:00+00:00", os_user="dave", server="evil-mcp",
    )  # fmt: skip
    rows = [
        _hook("claude_hooks.pre_tool_use", "s-1", "2026-10-29T10:00:00+00:00"),
        # Telemetry saw s-1 too: its calls come from telemetry, not twice.
        _otel("claude_code.tool_result", "s-1", "2026-10-29T10:00:01+00:00", "erin@example.com",
              tool_name="Bash", success="true"),
        # A session only telemetry saw, one call failed.
        _otel("claude_code.tool_result", "t-9", "2026-10-29T12:00:00+00:00", "carol@example.com",
              tool_name="Read", success="true"),
        _otel("claude_code.tool_result", "t-9", "2026-10-29T12:01:00+00:00", "carol@example.com",
              tool_name="Bash", success="false"),
        inv,
    ]  # fmt: skip
    LakeWriter(engine._lake).write(rows)
    LakeWriter(engine._lake).write([
        # A session the plugin started and nothing else: empty, hidden from the list.
        _hook("claude_hooks.session_start", "s-empty", "2026-10-29T13:00:00+00:00"),
    ])  # fmt: skip
    out = overview(engine, catalog, ["hooks", "claude", "inv"], NOW, 7, _mcp(lab))
    assert out.sessions is not None and out.sessions.value == 3  # s-1, t-9, s-empty
    # In parts that add up to the tile (PR 639): s-1 listed, s-empty empty, t-9 only in
    # telemetry; the Sessions list shows the listed one and hides the empty one.
    parts = out.session_parts
    assert (parts.listed, parts.empty, parts.telemetry_only) == (1, 1, 1)
    assert parts.listed + parts.empty + parts.telemetry_only == out.sessions.value
    from app.ai.sessions import sessions as listed

    rows = listed(engine, None, NOW, 7)
    assert sum(1 for r in rows if r.tool_calls or r.prompts) == parts.listed
    assert sum(1 for r in rows if not (r.tool_calls or r.prompts)) == parts.empty
    people = out.people
    assert people is not None and people.value >= 3  # the hooks user, carol, dave
    assert out.calls is not None and out.calls.value == 3  # s-1 once, t-9 twice
    assert out.failed is not None and out.failed.value == 1
    # An MCP server only the inventory reported counts as not approved too.
    assert out.mcp_not_approved is not None and out.mcp_not_approved.value == 1
    assert set(out.sources) >= {"hooks", "claude", "inv"}
    # Each number opens the rows it counted (ADR-0039), through the guard.
    from app.engine.duckdb import QueryScope
    from app.engine.guard import guard

    def rows(sql: str | None) -> int:
        assert sql
        filled = sql.replace("{from}", "2026-10-23T00:00:00+00:00").replace("{to}", NOW.isoformat())
        return len(engine.run(guard(filled, {"events"}).sql, QueryScope(None)).rows)

    assert rows(out.calls.drill) == out.calls.value
    assert rows(out.failed.drill) == out.failed.value
    assert rows(out.sessions.drill) == out.sessions.value
    assert rows(out.mcp_not_approved.drill) == out.mcp_not_approved.value


def test_mcp_counts_are_the_tables_rows_by_review_state(tmp_path: Path) -> None:
    """PR 639 review: a placeholder name (`custom`) is no MCP server in the table, so it is
    never "1 unreviewed MCP server" either; every count equals the table's rows."""
    lab = make_lab(tmp_path)
    engine, catalog = lab["app"].state.engine, lab["app"].state.ai_catalog
    catalog.set_mcp_rule("evil-mcp", "not_approved", "", "admin")
    LakeWriter(engine._lake).write([
        _hook("claude_hooks.pre_tool_use", "s-1", "2026-10-29T10:00:00+00:00",
              tool_name="mcp__custom__x", mcp_server_name="custom"),
        _hook("claude_hooks.pre_tool_use", "s-1", "2026-10-29T10:01:00+00:00",
              tool_name="mcp__evil-mcp__read", mcp_server_name="evil-mcp"),
        _hook("claude_hooks.pre_tool_use", "s-1", "2026-10-29T10:02:00+00:00",
              tool_name="mcp__notes__add", mcp_server_name="notes"),
    ])  # fmt: skip
    table = _mcp(lab)
    assert "custom" not in {m.name for m in table}
    out = overview(engine, catalog, ["hooks"], NOW, 7, table)
    assert out.mcp_not_approved is not None
    assert out.mcp_not_approved.value == sum(m.status == "not_approved" for m in table) == 1
    assert out.mcp_unreviewed == sum(m.status == "unreviewed" for m in table) == 1  # notes
    # Only the placeholder: nothing to review, so no Needs attention entry.
    lab2 = make_lab(tmp_path / "only-custom")
    LakeWriter(lab2["app"].state.engine._lake).write([
        _hook("claude_hooks.pre_tool_use", "s-2", "2026-10-29T10:00:00+00:00",
              tool_name="mcp__custom__x", mcp_server_name="custom"),
    ])  # fmt: skip
    out = overview(
        lab2["app"].state.engine, lab2["app"].state.ai_catalog, ["hooks"], NOW, 7, _mcp(lab2)
    )
    assert out.mcp_unreviewed == 0
    assert out.mcp_not_approved is not None and out.mcp_not_approved.value == 0


def test_the_overview_reads_exactly_the_window_asked(tmp_path: Path) -> None:
    """PR 639 review: the page's time, exactly (an hour, or a custom range in the past),
    compared with the window of the same length before it."""
    lab = make_lab(tmp_path)
    engine, catalog = lab["app"].state.engine, lab["app"].state.ai_catalog
    LakeWriter(engine._lake).write([
        _hook("claude_hooks.pre_tool_use", "s-in", "2026-10-29T23:30:00+00:00"),
        _hook("claude_hooks.pre_tool_use", "s-before", "2026-10-29T22:30:00+00:00"),
        # Data from the start of the hour before, so it is covered and compared (#638).
        _hook("claude_hooks.session_start", "s-before", "2026-10-29T22:01:00+00:00"),
        _hook("claude_hooks.pre_tool_use", "s-old", "2026-10-20T12:00:00+00:00"),
    ])  # fmt: skip
    hour = overview(engine, catalog, ["hooks"], NOW, 1, None, NOW - timedelta(hours=1))
    assert hour.sessions is not None and (hour.sessions.value, hour.sessions.before) == (1, 1)
    past = overview(
        engine, catalog, ["hooks"], NOW, 1, None,
        datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 21, tzinfo=UTC),
    )  # fmt: skip
    assert past.sessions is not None and past.sessions.value == 1  # s-old only
    assert past.end == datetime(2026, 10, 21, tzinfo=UTC).isoformat()


def test_mcp_servers_tied_on_calls_keep_their_order(tmp_path: Path) -> None:
    """PR 639: servers with the same calls and people swapped places between loads. The
    old order (calls, then the people list) put z-notes (bob) before a-notes (alice);
    ties now go by name, every time."""
    lab = make_lab(tmp_path)
    LakeWriter(lab["app"].state.engine._lake).write([
        _hook("claude_hooks.pre_tool_use", "s-z", "2026-10-29T10:00:00+00:00",
              tool_name="mcp__z-notes__add", mcp_server_name="z-notes", user="bob"),
        _hook("claude_hooks.pre_tool_use", "s-a", "2026-10-29T10:01:00+00:00",
              tool_name="mcp__a-notes__add", mcp_server_name="a-notes", user="alice"),
    ])  # fmt: skip
    rows = _mcp(lab)
    assert [(m.name, m.calls, m.people) for m in rows] == [("a-notes", 1, 1), ("z-notes", 1, 1)]
    for _ in range(3):
        assert [m.name for m in _mcp(lab)] == ["a-notes", "z-notes"]


def test_a_week_before_without_data_has_no_earlier_values(tmp_path: Path) -> None:
    """Fix list item 9: the hooks start inside the week before, so it is not covered."""
    lab = make_lab(tmp_path)
    engine, catalog = lab["app"].state.engine, lab["app"].state.ai_catalog
    rows = [
        _hook("claude_hooks.pre_tool_use", "s-1", "2026-10-29T10:00:00+00:00"),
        _hook("claude_hooks.pre_tool_use", "s-0", "2026-10-20T09:00:00+00:00"),
    ]
    LakeWriter(engine._lake).write(rows)
    out = overview(engine, catalog, ["hooks"], NOW, 7)
    first = datetime(2026, 10, 20, 9, tzinfo=UTC)
    assert out.history.compared is False and out.history.since == first
    assert out.history.starts == first + timedelta(days=7 * 0.9 + 7)
    assert out.sessions is not None and (out.sessions.value, out.sessions.before) == (1, None)
    assert out.calls is not None and out.calls.before is None
