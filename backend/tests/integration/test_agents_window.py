"""Agents reads one window, the time chosen (PR 639 review), through the endpoints: an exact
start and end on the server's clock, an open or missing side clamped to 90 days, an
explicit pair wider than that refused, each caller on their own sources, and the audit
row naming every source the overview's request read."""

import json
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from app.ingest.writer import LakeWriter
from tests.integration.test_ai_usage import lab  # noqa: F401  # the fixture
from tests.integration.test_m365_consents import _row
from tests.integration.test_schedules import NOW

HOOK = "a failed tool call from the Windows plugin names the Claude account"
PATHS = ("/api/agents/overview", "/api/ai/sessions", "/api/agents/accounts")


def _h(session: str, when: datetime, who: str = "erin@example.com") -> dict[str, Any]:
    a = {"event_name": "claude_hooks.pre_tool_use", "session_id": session,
         "claude_account_email": who, "os_user": who.split("@")[0], "tool_name": "Bash"}  # fmt: skip
    return _row(
        "claude_hooks", HOOK, "claude",
        time=when.isoformat(), event="claude_hooks.pre_tool_use", attr=a,
    )  # fmt: skip


def _get(client: Any, path: str, **params: Any) -> Any:
    return client.get(path, params={k: v.isoformat() if isinstance(v, datetime) else v
                                    for k, v in params.items()})  # fmt: skip


def _sessions(env: dict[str, Any], **params: Any) -> list[str]:
    res = _get(env["admin"], "/api/ai/sessions", **params)
    assert res.status_code == 200, res.text
    return sorted(s["session_id"] for s in res.json() if s["session_id"].startswith("w-"))


def test_the_window_on_the_servers_clock(
    lab: dict[str, Any],  # noqa: F811
    pin_now: Callable[[datetime], None],
) -> None:
    pin_now(NOW)
    LakeWriter(lab["app"].state.engine._lake).write([
        _h("w-hour", NOW - timedelta(minutes=30)),
        _h("w-week", NOW - timedelta(days=5)),
        _h("w-old", NOW - timedelta(days=89, hours=12)),
    ])  # fmt: skip
    a = lab["admin"]
    # A start exactly 90 days back and an open end: read, never refused for the clock.
    for path in PATHS:
        assert _get(a, path, start=NOW - timedelta(days=90)).status_code == 200, path
    assert _sessions(lab, start=NOW - timedelta(days=90)) == ["w-hour", "w-old", "w-week"]
    # An open end and a start further back than 90 days: clamped to 90, not refused.
    for path in PATHS:
        assert _get(a, path, start=NOW - timedelta(days=200)).status_code == 200, path
    # A missing start: `days` before the end asked for.
    assert _sessions(lab, days=7, end=NOW - timedelta(days=1)) == ["w-week"]
    # Exactly an hour.
    assert _sessions(lab, start=NOW - timedelta(hours=1)) == ["w-hour"]
    o = _get(a, "/api/agents/overview", start=NOW - timedelta(hours=1)).json()
    assert o["sessions"]["value"] >= 1 and o["end"] == NOW.isoformat()
    # An explicit pair wider than 90 days: its last 90 days are read, and said; only an end
    # before the start is refused.
    lo, hi = NOW - timedelta(days=120), NOW - timedelta(days=10)
    want = ((hi - timedelta(days=90)).isoformat(), hi.isoformat())
    o = _get(a, "/api/agents/overview", start=lo, end=hi).json()
    assert (o["read_start"], o["read_end"]) == want
    acc = _get(a, "/api/agents/accounts", start=lo, end=hi).json()
    assert (acc["read_start"], acc["read_end"]) == want
    assert _get(a, "/api/ai/sessions", start=lo, end=hi).status_code == 200
    rows = _get(a, "/api/ai/sessions", start=NOW - timedelta(days=200)).json()
    assert {(r["read_start"], r["read_end"]) for r in rows} == {
        ((NOW - timedelta(days=90)).isoformat(), NOW.isoformat())
    }
    for path in PATHS:
        back = _get(a, path, start=NOW, end=NOW - timedelta(days=1))
        assert back.status_code == 400, path
    # The list says its own total before the cap, the same on every row.
    rows = _get(a, "/api/ai/sessions", start=NOW - timedelta(days=90)).json()
    assert {(r["total"], r["with_steps"]) for r in rows} == {(len(rows), len(rows))}
    # With a person, the totals count that person's sessions only.
    LakeWriter(lab["app"].state.engine._lake).write([
        _h("w-frank", NOW - timedelta(minutes=20), who="frank@example.com"),
    ])  # fmt: skip
    mine = _get(a, "/api/ai/sessions", start=NOW - timedelta(days=90), person="erin@example.com")
    assert mine.status_code == 200, mine.text
    got = mine.json()
    assert "w-frank" not in {r["session_id"] for r in got}
    assert {(r["total"], r["with_steps"]) for r in got} == {(len(got), len(got))}


def test_each_caller_reads_their_own_sources_and_the_audit_names_them(
    lab: dict[str, Any],  # noqa: F811
    pin_now: Callable[[datetime], None],
) -> None:
    pin_now(NOW)
    LakeWriter(lab["app"].state.engine._lake).write([_h("w-hour", NOW - timedelta(minutes=30))])
    start = NOW - timedelta(days=7)
    # ana reads the Linux source only: no agent source, no MCP server, no session.
    o = _get(lab["ana"], "/api/agents/overview", start=start).json()
    assert o["has_source"] is False and o["mcp_unreviewed"] == 0
    assert o["mcp_not_approved"] is None or o["mcp_not_approved"]["value"] == 0
    assert [s["session_id"] for s in _get(lab["ana"], "/api/ai/sessions", start=start).json()] == []
    # The admin's overview reads the telemetry source and the MCP table's sources.
    o = _get(lab["admin"], "/api/agents/overview", start=start).json()
    assert o["has_source"] is True and o["mcp_unreviewed"] >= 1  # paste-share, unreviewed
    with sqlite3.connect(lab["db"]) as db:
        rows = [
            json.loads(r[0])
            for r in db.execute("SELECT detail FROM audit_log WHERE action = 'ai.view'")
        ]
    views = [r for r in rows if r.get("view") == "agents_overview"]
    mine, admins = views[0], views[-1]
    assert "claude" not in mine["sources_in_scope"]
    # The MCP read's sources are named too (the union of every read of the request).
    from app.engine.duckdb import QueryScope

    _, read = lab["app"].state.ai_usage.mcp_and_sources(QueryScope(None, start, NOW))
    assert set(read) <= set(admins["sources_in_scope"]) and "claude" in admins["sources_in_scope"]


def _mcp_call(server: str, when: datetime) -> dict[str, Any]:
    a = {"event_name": "claude_hooks.pre_tool_use", "session_id": f"m-{server}",
         "claude_account_email": "erin@example.com", "os_user": "erin",
         "tool_name": f"mcp__{server}__x", "mcp_server_name": server}  # fmt: skip
    return _row(
        "claude_hooks", HOOK, "claude",
        time=when.isoformat(), event="claude_hooks.pre_tool_use", attr=a,
    )  # fmt: skip


def test_mcp_counts_equal_the_tables_rows_for_the_same_bounds(
    lab: dict[str, Any],  # noqa: F811
    pin_now: Callable[[datetime], None],
) -> None:
    """PR 639 final review: the overview reads its MCP rows with the bounds the page asks
    AI usage for (start to the minute; a chosen end taken to the next minute, or open), so
    a server seen in the last minute before the end is in both, and the counts by review
    state equal the table's rows."""
    pin_now(NOW)
    end = NOW - timedelta(hours=1, seconds=-20)  # 20 s into a minute
    LakeWriter(lab["app"].state.engine._lake).write([
        _mcp_call("late-mcp", end - timedelta(seconds=10)),  # in the last minute
        _mcp_call("after-mcp", end + timedelta(minutes=2)),  # after the end
    ])  # fmt: skip
    a, start = lab["admin"], NOW - timedelta(days=7)
    up = end.replace(second=0) + timedelta(minutes=1)  # what the page sends AI usage
    for asked_end, table_end in ((end, up), (None, None)):
        o = _get(
            a, "/api/agents/overview", start=start, **({"end": asked_end} if asked_end else {})
        )
        t = _get(a, "/api/ai/usage", start=start, **({"end": table_end} if table_end else {}))
        assert o.status_code == 200 and t.status_code == 200, (o.text, t.text)
        rows = t.json()["mcp"]
        names = {m["name"] for m in rows}
        assert "late-mcp" in names
        assert ("after-mcp" in names) is (asked_end is None)
        body = o.json()
        assert body["mcp_unreviewed"] == sum(m["status"] == "unreviewed" for m in rows)
        approved_no = body["mcp_not_approved"]["value"] if body["mcp_not_approved"] else 0
        assert approved_no == sum(m["status"] == "not_approved" for m in rows)
