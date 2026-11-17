"""Every query over the hooks plugin's records pins its template, so the engine reads only the
sources that can hold them, never every source of the window (fix list item 15)."""

from __future__ import annotations

import pytest

from app.ai import accounts, agents_overview, session_summary, sessions
from app.engine.narrow import pinned_templates


@pytest.mark.parametrize(
    ("name", "sql"),
    [
        ("sessions", sessions.SESSIONS_SQL),
        ("steps", sessions.STEPS_SQL),
        ("summary", session_summary.SUMMARY_SQL),
        ("accounts", accounts.ACCOUNTS_SQL),
        ("tools", agents_overview.TOOLS_SQL),
        ("missing", agents_overview.MISSING_SQL),
    ],
)
def test_hook_queries_read_only_hook_records(name: str, sql: str) -> None:
    assert pinned_templates(sql) == {"claude_hooks"}, name


def test_the_overview_reads_the_three_agent_templates() -> None:
    want = {"claude_hooks", "claude_code_otel", "mcp_inventory"}
    assert pinned_templates(agents_overview.OVERVIEW_SQL) == want


def test_one_copy_still_leaves_test_records_out() -> None:
    cte = sessions.one_copy()
    assert "template_id = 'claude_hooks' AND NOT" in cte and "(template_id" not in cte
