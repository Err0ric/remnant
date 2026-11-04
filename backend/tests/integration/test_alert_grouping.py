"""ADR-0043: one open alert per entity, rule, and day; repeats update it; open duplicates
from before merge once, audited; the install's time zone draws the day; built-in Claude
Code tools never raise "changed"; a new agent's changes wait out the learning period
except MCP servers and tools."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.ai import watch as watch_mod
from app.ai.agents import AgentStatus
from app.ai.watch import is_mcp_item
from app.alerts.items import AlertItems
from app.meta.audit import AuditLog
from app.meta.db import MetaDB

NOW = datetime(2026, 11, 3, 18, 0, tzinfo=UTC)  # 10:00 in Los Angeles


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def store(tmp_path: Path) -> tuple[AlertItems, MetaDB, Clock]:
    meta, clock = MetaDB(tmp_path / "meta.sqlite"), Clock()
    return AlertItems(meta, AuditLog(meta), clock=clock, tz="America/Los_Angeles"), meta, clock


def _agent(items: AlertItems, line: str, severity: str = "medium") -> Any:
    return items.raise_item(
        "ai_watch", "agent:cc|dana@example.com", "AI agent changed: dana",
        why=line, severity=severity, group=("agent:cc|dana@example.com", "agent_change"),
        change=line,
    )  # fmt: skip


def test_repeats_the_same_day_update_one_item(store: Any) -> None:
    items, _, clock = store
    first = _agent(items, "new MCP server wiki")
    assert first.fresh and first.count is None
    clock.now += timedelta(minutes=1)
    again = _agent(items, "new MCP tool mcp__wiki__search")
    assert again.item_id == first.item_id and not again.fresh and not again.rose
    assert again.count == 2
    assert again.changes == ["new MCP tool mcp__wiki__search", "new MCP server wiki"]
    assert again.last_seen == clock.now.isoformat()
    worse = _agent(items, "new MCP server paste", severity="high")
    assert worse.item_id == first.item_id and worse.rose and worse.severity == "high"


def test_closed_today_gives_a_new_item_tomorrow_another(store: Any) -> None:
    items, meta, clock = store
    first = _agent(items, "new MCP server wiki")
    with meta.connect() as con:
        items._set_closed(con, first.item_id, None, "benign", None, clock().isoformat())
    second = _agent(items, "new MCP server paste")
    assert second.item_id != first.item_id and second.fresh
    assert second.detail.startswith("Closed earlier today as Expected.")
    # 08:30 UTC next day is still the 3rd in Los Angeles: the same day, the same item.
    clock.now = datetime(2026, 11, 4, 7, 30, tzinfo=UTC)
    assert _agent(items, "new MCP server x").item_id == second.item_id
    clock.now = datetime(2026, 11, 4, 8, 30, tzinfo=UTC)  # 00:30 on the 4th there
    third = _agent(items, "new MCP server y")
    assert third.item_id != second.item_id and third.day == "2026-11-04"


def test_open_duplicates_from_before_merge_once_and_are_audited(store: Any) -> None:
    items, meta, clock = store
    agent = "agent:cc|dana@example.com"
    tools = ["Agent", "Bash", "Write", "WebSearch", "ToolSearch", "SubagentHandback"]
    ids = []
    for i, tool in enumerate(tools):  # how the old rule raised them: one per tool
        clock.now = NOW + timedelta(seconds=i)
        it = items.raise_item("ai_watch", agent, "AI agent changed: dana",
                              ref_id=f"{agent}:Tool:{tool}", why=f"new Tool {tool}",
                              severity="medium")  # fmt: skip
        ids.append(it.item_id)
    review = items.raise_item("ai_watch", agent, "AI agent not reviewed: dana",
                              ref_id=f"{agent}:agent")  # fmt: skip
    assert items.merge_open_duplicates() == 5
    with meta.connect() as con:
        rows = {r["item_id"]: r for r in con.execute("SELECT * FROM alert_items")}
        audits = [json.loads(r["detail"]) for r in con.execute(
            "SELECT detail FROM audit_log WHERE action = 'alert.merge'")]  # fmt: skip
    kept = rows[ids[0]]
    assert kept["state"] == "open" and kept["count"] == 6 and kept["rule"] == "agent_change"
    assert json.loads(kept["changes"])["lines"][0] == "new Tool Agent"
    assert all(rows[i]["close_reason"] == "merged" for i in ids[1:])
    assert rows[ids[1]]["note"] == f"Merged into alert {ids[0]}"
    assert sorted(a["item_id"] for a in audits) == sorted(ids[1:])
    assert rows[review.item_id]["state"] == "open"  # a standing review item stays itself
    assert items.merge_open_duplicates() == 0  # once


@pytest.mark.parametrize(
    ("kind", "name", "mcp"),
    [
        ("Tool", "Bash", False),
        ("Tool", "ToolSearch", False),  # a built-in added by a Claude Code update
        ("Tool", "SomeFutureBuiltin", False),
        ("Tool", "mcp__wiki__search", True),
        ("MCP server", "wiki", True),
        ("Model", "claude-sonnet-5-5", False),
    ],
)
def test_built_in_is_any_tool_without_the_mcp_prefix(kind: str, name: str, mcp: bool) -> None:
    assert is_mcp_item(kind, name) is mcp


def _status(first: datetime, items: list[tuple[str, str]]) -> AgentStatus:
    return AgentStatus(
        kind="Claude Code", agent="cc|dana@example.com", label="Claude Code, dana: ws-alpha",
        owners=["dana@example.com"], machine="ws-alpha", first_seen=first.isoformat(),
        last_seen=NOW.isoformat(), events_24h=5, state="changed",
        new_items=[{"kind": k, "name": n} for k, n in items],
    )  # fmt: skip


def _watch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: AgentStatus) -> Any:
    meta, clock = MetaDB(tmp_path / "w.sqlite"), Clock()
    items = AlertItems(meta, AuditLog(meta), clock=clock)

    class Engine:
        def run(self, *a: Any, **k: Any) -> Any:
            return type("R", (), {"rows": [], "sources": []})()

    w = watch_mod.AiWatch(meta, Engine(), None, None, AuditLog(meta), None,  # type: ignore[arg-type]  # fakes with only what _agents uses
                          clock=clock, items=items, learning_days=14)  # fmt: skip
    monkeypatch.setattr(watch_mod, "agents", lambda *a, **k: [status])
    w._agents(_settings(), NOW)
    with meta.connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM alert_items")]


def _settings() -> Any:
    return type("S", (), {"enabled": False, "agents": False, "target_ids": []})()


def test_built_in_tools_never_alert_and_learning_waits_but_mcp_does_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    learning = _status(NOW - timedelta(days=3), [
        ("Tool", "ToolSearch"), ("Model", "claude-opus-5-5"), ("Tool", "mcp__wiki__search"),
        ("MCP server", "wiki"),
    ])  # fmt: skip
    rows = _watch(tmp_path / "a", monkeypatch, learning)
    (item,) = [r for r in rows if r["rule"] == "agent_change"]
    lines = json.loads(item["changes"])["lines"]
    assert any("mcp__wiki__search" in x for x in lines) and any(
        "MCP server wiki" in x for x in lines
    )
    assert not any("ToolSearch" in x or "claude-opus" in x for x in lines)
    settled = _status(NOW - timedelta(days=20), [("Tool", "ToolSearch"), ("Model", "m2")])
    rows = _watch(tmp_path / "b", monkeypatch, settled)
    (item,) = [r for r in rows if r["rule"] == "agent_change"]
    assert json.loads(item["changes"])["lines"] == ["Claude Code, dana: ws-alpha: new Model m2"]


def test_personal_account_is_medium_once_and_blocked_burst_is_high(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta, clock = MetaDB(tmp_path / "p.sqlite"), Clock()
    items = AlertItems(meta, AuditLog(meta), clock=clock)

    class Engine:
        def run(self, sql: str, *a: Any, **k: Any) -> Any:
            if "post_tool_use_failure" in sql:
                rows = [("cc|dana@example.com", 12)]
            elif "claude_account_email" in sql:
                rows = [("dana@example.org", "ws-alpha"), ("erin@example.com", "ws-zulu")]
            else:
                rows = []
            return type("R", (), {"rows": rows, "sources": []})()

    w = watch_mod.AiWatch(
        meta, Engine(), None, None, AuditLog(meta), None,  # type: ignore[arg-type]  # fakes with only what _agents uses
        clock=clock, items=items, domains=lambda: ["example.com"], blocked_burst=10,
    )  # fmt: skip
    monkeypatch.setattr(watch_mod, "agents", lambda *a, **k: [])
    assert len(w._account_and_blocked(NOW)) == 2
    assert w._account_and_blocked(NOW + timedelta(minutes=5)) == []  # once; then counted
    with meta.connect() as con:
        rows = {r["subject"]: dict(r) for r in con.execute("SELECT * FROM alert_items")}
    personal = rows["account:dana@example.org"]
    assert personal["severity"] == "medium" and "ws-alpha" in personal["devices"]
    assert "account:erin@example.com" not in rows  # a company account
    burst = rows["agent:cc|dana@example.com"]
    assert (burst["severity"], burst["rule"], burst["count"]) == ("high", "blocked_calls", 24)


def test_a_flapping_source_notifies_at_most_three_times_a_day(store: Any) -> None:
    """Owner, 2026-11-03: a gap notifies again only when the source was back 15 minutes,
    at most three notifications a day; then it keeps counting and says flapping."""
    items, _, clock = store

    def gap(at: int) -> Any:
        clock.now = NOW + timedelta(minutes=at)
        return items.raise_item(
            "gap", "fw01", "fw01 stopped sending", ref_id=f"fw01@{at}",
            group=("fw01", "gap"), change=f"quiet at {at}", severity="medium",
        )  # fmt: skip

    def back(at: int, episode: int) -> None:
        clock.now = NOW + timedelta(minutes=at)
        items.resolve("gap", f"fw01@{episode}", "Events arriving again", group=("fw01", "gap"))

    first = gap(0)
    assert first.fresh
    back(1, 0)
    short = gap(5)  # back only 4 minutes: counted, not sent
    assert short.item_id == first.item_id and not short.rose and short.resolved is None
    back(10, 5)
    assert gap(30).rose  # back 20 minutes: the second notification
    back(31, 30)
    assert gap(50).rose  # the third
    back(51, 50)
    fourth = gap(70)
    assert not fourth.rose and fourth.title == "fw01 stopped sending (flapping)"
    assert fourth.count == 5
    back(71, 70)
    assert gap(90).title.count("(flapping)") == 1
