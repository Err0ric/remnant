"""AI agents and allowed-data labels (ADR-0020 rows 2 to 4)."""

import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from app.ai.agents import agents
from tests.integration.test_ai_usage import lab as ai_lab  # noqa: F401  # fixture
from tests.integration.test_schedules import NOW

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts" / "fixtures"))
from ai_telemetry import logs_payload

BASE = {"user.email": "alice@example.com", "session.id": "s-0"}


@pytest.fixture
def lab(ai_lab: dict[str, Any]) -> dict[str, Any]:  # noqa: F811  # fixture
    """Ten days before the lab's data, alice's Claude Code on ws-0042 only used Read."""
    a, h = ai_lab["admin"], ai_lab["h"]
    token = a.post("/api/sources/claude/otlp-token", headers=h).json()["token"]
    old = NOW - timedelta(days=10)
    logs = logs_payload(
        [
            (old, {**BASE, "event.name": "tool_result", "tool_name": "Read", "success": "true"}),
            (old, {**BASE, "event.name": "api_request", "model": "claude-sonnet-5-5"}),
        ],
        "ws-0042",
    )
    hdr = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    r = a.post("/api/otlp/v1/logs", content=json.dumps(logs).encode(), headers=hdr)
    assert r.status_code == 200, r.text
    ai_lab["app"].state.ingest.run_once()
    return ai_lab


def test_agent_with_a_new_mcp_server_is_changed(lab: dict[str, Any]) -> None:
    rows = agents(lab["app"].state.engine, None, NOW + timedelta(hours=1))
    cc = next(a for a in rows if a.kind == "Claude Code")
    assert cc.label == "Claude Code on ws-0042" and cc.owners == ["alice@example.com"]
    assert cc.state == "changed"
    assert {"kind": "MCP server", "name": "paste-share"} in cc.new_items
    assert {"kind": "Tool", "name": "Read"} not in cc.new_items  # in the baseline
    inv = next(a for a in rows if a.kind == "MCP client")
    assert inv.label == "Cursor MCP setup on ws-0042" and inv.state == "new"


def test_agents_endpoint_is_scoped(lab: dict[str, Any]) -> None:
    res = lab["admin"].get("/api/ai/agents")
    assert res.status_code == 200, res.text
    assert any(a["kind"] == "Claude Code" for a in res.json())
    assert lab["ana"].get("/api/ai/agents").json() == []  # Linux sources only


def test_watch_alerts_agent_changes_once(lab: dict[str, Any]) -> None:
    app, a, h = lab["app"], lab["admin"], lab["h"]
    app.state.ai_watch._clock = lambda: NOW + timedelta(hours=1)
    res = a.put("/api/ai/watch", json={"enabled": True, "agents": True}, headers=h)
    assert res.status_code == 200 and res.json()["agents"] is True
    app.state.ai_watch.tick()
    with app.state.meta.connect() as con:
        (detail,) = con.execute(
            "SELECT detail FROM audit_log WHERE action = 'ai.agent_change'"
        ).fetchone()
    items = json.loads(detail)["items"]
    assert any(
        "Claude Code on ws-0042 (alice@example.com): new MCP server paste-share" in i for i in items
    )
    app.state.ai_watch._clock = lambda: NOW + timedelta(hours=3)
    app.state.ai_watch.tick()
    with app.state.meta.connect() as con:
        n = con.execute("SELECT count(*) FROM audit_log WHERE action = 'ai.agent_change'")
        assert n.fetchone()[0] == 1  # already told


def test_data_level_is_admin_only_audited_and_clears_sensitive_alerts(lab: dict[str, Any]) -> None:
    app, a, h = lab["app"], lab["admin"], lab["h"]
    body = {"data_level": "confidential"}
    assert lab["ana"].put("/api/ai/services/anthropic_api/data-level", json=body).status_code == 403
    assert a.put("/api/ai/services/nope/data-level", json=body, headers=h).status_code == 404
    assert (
        a.put(
            "/api/ai/services/anthropic_api/data-level", json={"data_level": "secret"}, headers=h
        ).status_code
        == 422
    )
    res = a.put("/api/ai/services/anthropic_api/data-level", json=body, headers=h)
    assert res.status_code == 200 and res.json()["data_level"] == "confidential"
    cat = {s["id"]: s for s in a.get("/api/ai/catalog").json()}
    assert cat["anthropic_api"]["data_level"] == "confidential"
    # Sensitive data from Claude Code goes to a service cleared for it: no alert.
    app.state.ai_watch._clock = lambda: NOW - timedelta(days=1)
    a.put("/api/ai/watch", json={"enabled": True, "include_unreviewed": True}, headers=h)
    app.state.ai_watch.tick()
    with app.state.meta.connect() as con:
        n = con.execute("SELECT count(*) FROM audit_log WHERE action = 'ai.sensitive'").fetchone()
    assert n[0] == 0
    a.put("/api/ai/services/anthropic_api/data-level", json={"data_level": None}, headers=h)
    assert {s["id"]: s for s in a.get("/api/ai/catalog").json()}["anthropic_api"][
        "data_level"
    ] is None
