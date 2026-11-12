"""Messages to alert targets for AI Watch name no one (D242, replaces ADR-0029 G5's
per-target checkbox), and the alert count is not an AI view."""

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from app.ai import watch as watch_mod
from app.ai.agents import AgentStatus
from app.alerts.items import AlertItems
from app.alerts.render import Alert, email_parts, slack_payload, teams_payload, webhook_body
from app.meta.audit import AuditLog
from app.meta.db import MetaDB
from tests.integration.test_ai_people_masking import _audit, ai_lab  # noqa: F401  # fixture
from tests.integration.test_ai_usage import lab  # noqa: F401  # the fixture ai_lab uses
from tests.integration.test_alert_grouping import NOW, Clock

NAMES = ("alice", "bob", "carol", "dave", "dana", "erin")


class _Dispatch:
    def __init__(self) -> None:
        self.sent: list[Alert] = []

    def enqueue(self, alert: Alert, *a: Any) -> None:
        self.sent.append(alert)


def _watch(meta: MetaDB, items: AlertItems, rows: dict[str, list[Any]]) -> Any:
    class Engine:
        def run(self, sql: str, *a: Any, **k: Any) -> Any:
            key = next((k for k in rows if k in sql), None)
            return type("R", (), {"rows": rows.get(key, []) if key else [], "sources": []})()

    dispatch = _Dispatch()
    w = watch_mod.AiWatch(
        meta, Engine(), None, dispatch, AuditLog(meta), "https://siem.example.com",  # type: ignore[arg-type]  # fakes with only what is used
        clock=Clock(), items=items, domains=lambda: ["example.com"], blocked_burst=10,
    )  # fmt: skip
    return w, dispatch


def _agent() -> AgentStatus:
    return AgentStatus(
        kind="Claude Code", agent="cc|dana@example.com", label="Claude Code, dana: ws-alpha",
        owners=["dana@example.com"], machine="ws-alpha", first_seen=NOW.isoformat(),
        last_seen=NOW.isoformat(), events_24h=5, state="new", new_items=[],
    )  # fmt: skip


def test_messages_to_targets_carry_only_a_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every target's payload (Slack, Teams, email, webhook) carries only the kind, the
    severity, how many items, and a link to Alerts: no person, machine, service, or MCP
    name, and no line of the item (D242, replaces ADR-0029 G5's per-target checkbox)."""
    meta = MetaDB(tmp_path / "t.sqlite")
    items = AlertItems(meta, AuditLog(meta), clock=Clock())
    w, dispatch = _watch(meta, items, {
        "post_tool_use_failure": [
            ("cc|dana@example.com", 12, False), ("cc|erin", 11, False), ("cc|ws-0042", 10, True),
        ],
        "claude_account_email": [("alice@example.org", "ws-alpha")],
    })  # fmt: skip
    monkeypatch.setattr(watch_mod, "agents", lambda *a, **k: [_agent()])
    on = type("S", (), {"enabled": True, "agents": True, "target_ids": ["t1"]})()
    assert w._agents(on, NOW) == 1
    w._alert("ai_new", ["ChatGPT by alice@example.com", "MCP github by ALICELAPTOP"], ["t1"],
             NOW, NOW)  # fmt: skip
    w._alert("ai_sensitive", ["ALICELAPTOP: aws_access_key x1"], ["t1"], NOW, NOW, "high")
    assert len(dispatch.sent) == 3
    leaks = (*NAMES, "alicelaptop", "ws-0042", "ws-alpha", "chatgpt", "github", "aws_access")
    for alert in dispatch.sent:
        for build in (slack_payload, teams_payload, email_parts, webhook_body):
            out = json.dumps(build(alert), default=str).lower()
            assert not [n for n in leaks if n in out], (build.__name__, out)
            assert "ai watch alert" in out and "siem.example.com/alerts" in out
        assert alert.link == "https://siem.example.com/alerts"
        assert alert.title == "AI watch alert"
    agent, new, sens = dispatch.sent
    assert agent.count == 5 and agent.severity == "high"  # a burst of blocked calls
    assert agent.detail == "5 new or changed items; open Alerts to see them"
    assert (new.count, new.severity) == (2, "medium")
    assert (sens.count, sens.severity) == (1, "high")
    assert sens.detail == "1 new or changed item; open Alerts to see them"
    # The audit row keeps what the watch saw, as before.
    with meta.connect() as con:
        (row,) = con.execute("SELECT detail FROM audit_log WHERE action = 'ai.agent_change'")
    assert "dana" in row[0]


def test_the_alert_count_is_not_an_ai_view(ai_lab: dict[str, Any]) -> None:  # noqa: F811
    """Owner, 2026-11-11: the alert badge and the Dashboard's count write no audit row;
    an answer with AI Watch items always does (ai.view, or ai.view_people with names)."""
    seen = (len(_audit(ai_lab, "ai.view")), len(_audit(ai_lab, "ai.view_people")))
    for who in ("admin", "ana"):
        res = ai_lab[who].get("/api/alerts/count")
        assert res.status_code == 200, res.text
        assert set(res.json()) == {"open", "restricted", "by_severity"}
        assert res.json()["open"] >= 1 and "alice" not in res.text
    assert (len(_audit(ai_lab, "ai.view")), len(_audit(ai_lab, "ai.view_people"))) == seen
    # The count matches the list's.
    listed = ai_lab["ana"].get("/api/alerts").json()
    counted = ai_lab["ana"].get("/api/alerts/count").json()
    assert (counted["open"], counted["restricted"], counted["by_severity"]) == (
        listed["open"], listed["restricted"], listed["by_severity"],
    )  # fmt: skip
    assert _audit(ai_lab, "ai.view")[-1]["surface"] == "alerts"
    assert ai_lab["admin"].get("/api/alerts").status_code == 200
    assert _audit(ai_lab, "ai.view_people")[-1]["surface"] == "alerts"
    with sqlite3.connect(ai_lab["db"]) as con:
        assert (
            con.execute("SELECT count(*) FROM audit_log WHERE action LIKE 'ai.view%'").fetchone()[0]
            == sum(seen) + 2
        )


def test_summary_lines_are_audited_only_when_they_name_someone(
    ai_lab: dict[str, Any],  # noqa: F811
) -> None:
    """Owner, 2026-11-11: the audit log records access, not page loads. The Dashboard's
    "Needs you" and Health's newest alert read only the lines they show; a row only when a
    shown line names someone to a viewer with the permission. Alerts is audited as before."""

    def rows() -> tuple[int, int]:
        return len(_audit(ai_lab, "ai.view")), len(_audit(ai_lab, "ai.view_people"))

    before = rows()
    # An analyst without the permission, with an AI watch item open: the line is masked.
    res = ai_lab["ana"].get("/api/alerts/lines?limit=5")
    assert res.status_code == 200, res.text
    body = res.json()
    assert [i["item_id"] for i in body["items"]] == [ai_lab["item"]]
    assert "alice" not in res.text and body["runs"] == {ai_lab["item"]: 1}
    assert ai_lab["ana"].get("/api/alerts/lines?limit=1&by=newest").status_code == 200
    assert rows() == before
    # An admin sees the name on the line: one ai.view_people row, no ai.view.
    res = ai_lab["admin"].get("/api/alerts/lines?limit=5")
    assert "alice" in res.text
    assert rows() == (before[0], before[1] + 1)
    assert _audit(ai_lab, "ai.view_people")[-1]["surface"] == "alert_lines"
    # A line that is not shown is not access: older than the newest it is left out.
    ai_lab["app"].state.alert_items.raise_item(
        "rule", "rule:r1", "Rule: brute force", ref_id="r1", sources=["dns"], severity="high"
    )
    res = ai_lab["admin"].get("/api/alerts/lines?limit=1")
    assert [i["kind"] for i in res.json()["items"]] == ["rule"]
    assert res.json()["groups"] == 2
    assert rows() == (before[0], before[1] + 1)
    # Order: by severity puts the High line first even when a Medium one is newer; newest
    # puts the newest first whatever its severity.
    ai_lab["app"].state.alert_items.raise_item(
        "rule", "rule:r2", "Rule: odd hours", ref_id="r2", sources=["dns"], severity="medium"
    )

    def first(path: str) -> str:
        return str(ai_lab["admin"].get(path).json()["items"][0]["subject"])

    assert first("/api/alerts/lines?limit=1&by=severity") == "rule:r1"
    assert first("/api/alerts/lines?limit=1&by=newest") == "rule:r2"
    assert first("/api/alerts/lines?limit=1") == "rule:r1"  # severity is the default
    assert rows() == (before[0], before[1] + 1)
    # The Alerts list still writes ai.view for the analyst, as before (G3).
    assert ai_lab["ana"].get("/api/alerts").status_code == 200
    assert rows() == (before[0] + 1, before[1] + 1)
    assert _audit(ai_lab, "ai.view")[-1]["surface"] == "alerts"
