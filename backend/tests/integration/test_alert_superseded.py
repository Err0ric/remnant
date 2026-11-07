"""D213 (proposed): on upgrade, open alerts the current rules would no longer raise close as
Superseded by rule change, one audit row each; alerts still raised, or that someone acted
on, stay open; running twice changes nothing."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.alerts.items import AlertItems
from app.alerts.supersede import Rules, still_raised
from app.auth.users import User
from app.meta.audit import AuditLog
from app.meta.db import MetaDB

NOW = datetime(2026, 11, 6, 18, 0, tzinfo=UTC)
AGENT = "agent:cc|dana@example.com"
RULES = Rules(sources=frozenset({"lin_auth", "otel_cc"}), watched=frozenset({"lin_auth"}))


@pytest.fixture
def store(tmp_path: Path) -> tuple[AlertItems, MetaDB]:
    meta = MetaDB(tmp_path / "meta.sqlite")
    return AlertItems(meta, AuditLog(meta), clock=lambda: NOW), meta


def _change(items: AlertItems, agent: str, *lines: str) -> str:
    item = None
    for line in lines:
        item = items.raise_item(
            "ai_watch", agent, "AI agent changed: Claude Code on ws-alpha", why=line,
            severity="medium", group=(agent, "agent_change"), change=line,
        )  # fmt: skip
    assert item is not None
    return item.item_id


def _gap(items: AlertItems, source: str) -> str:
    return items.raise_item(
        "gap", source, f"{source} stopped sending", ref_id=f"{source}@1",
        sources=[source], group=(source, "gap"), severity="medium",
    ).item_id  # fmt: skip


def _close_rows(meta: MetaDB) -> list[dict[str, Any]]:
    with meta.connect() as con:
        rows = con.execute(
            "SELECT user_id, detail FROM audit_log WHERE action = 'alert.close'"
        ).fetchall()
    return [{"user_id": r["user_id"], **json.loads(r["detail"])} for r in rows]


def test_removed_rules_close_with_the_reason_and_an_audit_row(store: Any) -> None:
    items, meta = store
    built_in = _change(items, AGENT, "Claude Code on ws-alpha: new Tool Bash")
    other = "agent:cc|erin@example.com"
    legacy = items.raise_item(  # how alerts from before ADR-0043 were raised
        "ai_watch", other, "AI agent changed: ws-beta", ref_id=f"{other}:Tool:Write",
        why="new Tool Write", severity="medium",
    ).item_id  # fmt: skip
    unwatched = _gap(items, "otel_cc")  # its quiet alert was turned off (D168)
    gone = _gap(items, "old_src")  # the source was removed

    closed = items.close_superseded(lambda i: still_raised(i, RULES), "fix-a")
    assert sorted(closed) == sorted([built_in, legacy, unwatched, gone])
    with meta.connect() as con:
        rows = {
            r["item_id"]: r
            for r in con.execute("SELECT * FROM alert_items WHERE item_id IN (?, ?, ?, ?)",
                                 (built_in, legacy, unwatched, gone))
        }  # fmt: skip
    for r in rows.values():
        assert (r["state"], r["close_reason"], r["closed_by"]) == ("closed", "superseded", None)
        assert r["note"] == "Superseded by rule change"
    shown = items.get(built_in, User("u1", "ana", "admin"))
    assert shown.history[-1].reason == "superseded" and shown.history[-1].user_id is None
    audits = _close_rows(meta)
    assert sorted(a["item_id"] for a in audits) == sorted(closed)
    assert all(a["user_id"] is None and a["reason"] == "superseded" for a in audits)
    # A later run (another upgrade) finds nothing left to close and writes nothing.
    assert items.close_superseded(lambda i: still_raised(i, RULES), "fix-a2") == []
    assert len(_close_rows(meta)) == len(closed)


def test_still_raised_or_acted_on_stays_open_and_twice_changes_nothing(store: Any) -> None:
    items, meta = store
    mcp = _change(
        items,
        AGENT,
        "Claude Code on ws-alpha: new Tool Bash",
        "Claude Code on ws-alpha: new MCP server wiki",  # still raises "changed"
    )
    watched = _gap(items, "lin_auth")
    blocked = items.raise_item(
        "ai_watch", AGENT, "AI agent: blocked or failed calls, dana", why="12 blocked",
        severity="high", group=(AGENT, "blocked_calls"),
    ).item_id  # fmt: skip
    review = items.raise_item(
        "ai_watch", AGENT, "AI agent not reviewed: dana", ref_id=f"{AGENT}:agent"
    ).item_id
    # Someone acted on this one (closed it, then reopened it): left alone.
    touched = _change(items, "agent:cc|grace@example.com", "Claude Code on ws-beta: new Tool Read")
    with meta.connect() as con:
        con.execute(
            "INSERT INTO alert_item_history (item_id, at, user_id, action)"
            " VALUES (?, '2026-11-06T18:00:00+00:00', 'u1', 'reopen')",
            (touched,),
        )
    unreadable = items.raise_item(
        "ai_watch", "agent:cc|frank@example.com", "AI agent changed: x",
        ref_id="agent:cc|frank@example.com:Tool:Bash", why="something else",
    ).item_id  # fmt: skip

    assert items.close_superseded(lambda i: still_raised(i, RULES), "fix-b") == []
    with meta.connect() as con:
        states = dict(con.execute("SELECT item_id, state FROM alert_items").fetchall())
    for item_id in (mcp, watched, blocked, review, touched, unreadable):
        assert states[item_id] == "open"

    # Once per fix id: a second run with the same id reads nothing, even with an alert a
    # rule would now retire.
    later = _change(items, "agent:cc|heidi@example.com", "Claude Code on ws-gamma: new Tool Grep")
    assert items.close_superseded(lambda i: still_raised(i, RULES), "fix-b") == []
    with meta.connect() as con:
        assert (
            con.execute("SELECT state FROM alert_items WHERE item_id = ?", (later,)).fetchone()[0]
            == "open"
        )
    assert _close_rows(meta) == []
