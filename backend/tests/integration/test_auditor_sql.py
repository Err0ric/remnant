"""D220: an Auditor runs no SQL until an admin turns on the setting that grants it.

Off (the default): Logs SQL, export, facets, live, saved-search runs, schedule run-now,
Ask, the MCP server, and the CLI `query` refuse an Auditor with a typed 403. On: the
Auditor's SQL runs on the same per-session events view and scope as anyone. The audit log,
dashboards, and integrity report stay open to Auditors either way. Toggling is admin only
and audited with the user id.
"""

import json
import sqlite3
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from app.cli import main as cli
from app.cli.client import Credentials
from tests.integration.test_ask import BASE, USER_PW, answer, make_lab

SQL = "SELECT source_id, count(*) AS n FROM events GROUP BY 1"
CODE = "auditor_sql_off"


@pytest.fixture
def lab(tmp_path: Any) -> dict[str, Any]:
    lab = make_lab(tmp_path)
    admin, h = lab["admin"], lab["h"]
    users = {u["username"]: u["user_id"] for u in admin.get("/api/users").json()}
    gid = admin.get("/api/groups").json()[0]["group_id"]
    res = admin.put(
        f"/api/groups/{gid}/members", json={"user_ids": [users["ana"], users["aud"]]}, headers=h
    )
    assert res.status_code == 200, res.text
    shared = {"id": "by_source", "name": "By source", "sql": SQL, "visibility": "shared"}
    assert admin.post("/api/searches", json=shared, headers=h).status_code == 201
    res = admin.put("/api/mcp/settings", json={"enabled": True, "endpoint_local": True}, headers=h)
    assert res.status_code == 200, res.text
    lab["users"] = users
    return lab


def token_for(lab: dict[str, Any], username: str) -> str:
    c = TestClient(lab["app"], base_url=BASE)
    res = c.post(
        "/api/auth/login", json={"username": username, "password": USER_PW, "client": "cli"}
    )
    token: str = res.json()["token"]
    return token


def client(lab: dict[str, Any], username: str) -> TestClient:
    c = TestClient(lab["app"], base_url=BASE)
    c.headers["Authorization"] = f"Bearer {token_for(lab, username)}"
    return c


def set_auditor_sql(lab: dict[str, Any], enabled: bool) -> Any:
    return lab["admin"].put(
        "/api/settings/auditor-sql", json={"enabled": enabled}, headers=lab["h"]
    )


def surfaces(c: TestClient) -> dict[str, Any]:
    """One call per SQL surface D220 names (live is checked on its own: it streams)."""
    q = {"sql": SQL}
    rpc = {"jsonrpc": "2.0", "id": 1, "method": "tools/call"}
    return {
        "query": c.post("/api/query", json=q),
        "export": c.post("/api/query/export", json=q),
        "facets": c.post("/api/search/facets", json=q),
        "saved_run": c.post("/api/searches/by_source/run", json={}),
        "ask": c.post("/api/ask", json={"question": "events by source"}),
        "mcp": c.post(
            "/api/mcp",
            json={**rpc, "params": {"name": "run_query", "arguments": {"sql": SQL}}},
        ),
    }


def audit_rows(lab: dict[str, Any], action: str) -> list[sqlite3.Row]:
    db = sqlite3.connect(lab["tmp"] / "data" / "meta.sqlite")
    db.row_factory = sqlite3.Row
    return db.execute("SELECT * FROM audit_log WHERE action = ?", (action,)).fetchall()


def test_off_by_default_and_every_surface_refuses_an_auditor(lab: dict[str, Any]) -> None:
    aud = client(lab, "aud")
    assert aud.get("/api/settings/auditor-sql").json()["enabled"] is False
    for name, res in surfaces(aud).items():
        assert res.status_code == 403, name
        assert res.json()["code"] == CODE, name
        assert "administrator" in res.json()["detail"], name
    live = aud.get("/api/search/live", params={"q": "SELECT * FROM events"})
    assert live.status_code == 403 and live.json()["code"] == CODE
    assert lab["script"].seen == []  # Ask never reached a model
    denied = audit_rows(lab, "access.denied")
    assert {r["user_id"] for r in denied} == {lab["users"]["aud"]}


def test_analysts_are_unaffected(lab: dict[str, Any]) -> None:
    lab["script"].replies = [answer(SQL)]
    for name, res in surfaces(client(lab, "ana")).items():
        assert res.status_code == 200, (name, res.text)


def test_on_auditor_runs_sql_in_their_own_scope(lab: dict[str, Any]) -> None:
    assert set_auditor_sql(lab, True).json()["enabled"] is True
    lab["script"].replies = [answer(SQL)]
    aud = client(lab, "aud")
    got = surfaces(aud)
    for name, res in got.items():
        assert res.status_code == 200, (name, res.text)
    # Same per-session view as anyone: the Network group's source only, never hr_payroll.
    assert got["query"].json()["rows"] == [["fw_edge", 8]]
    assert got["saved_run"].json()["sources"] == ["fw_edge"]
    assert "hr_payroll" not in got["export"].text
    # The guard still applies.
    bad = aud.post("/api/query", json={"sql": "DROP TABLE events"})
    assert bad.status_code == 400 and bad.json()["code"] == "query_rejected"


def test_toggle_is_admin_only_and_audited(lab: dict[str, Any]) -> None:
    for name in ("ana", "aud"):
        res = client(lab, name).put("/api/settings/auditor-sql", json={"enabled": True})
        assert res.status_code == 403
    assert client(lab, "aud").get("/api/settings/auditor-sql").json()["enabled"] is False
    set_auditor_sql(lab, True)
    set_auditor_sql(lab, False)
    rows = audit_rows(lab, "settings.auditor_sql")
    admin_id = lab["admin"].get("/api/auth/state").json()["user"]["user_id"]
    assert [r["user_id"] for r in rows] == [admin_id, admin_id]
    details = [json.loads(r["detail"]) for r in rows]
    assert details == [{"from": False, "to": True}, {"from": True, "to": False}]
    assert surfaces(client(lab, "aud"))["query"].status_code == 403  # off again


def test_auditor_keeps_audit_log_dashboards_and_reports(lab: dict[str, Any]) -> None:
    aud = client(lab, "aud")
    assert aud.get("/api/audit/events").status_code == 200
    assert aud.get("/api/dashboards").status_code == 200
    assert aud.get("/api/schedules").status_code == 200
    assert aud.get("/api/integrity").status_code == 200
    assert aud.get("/api/searches").status_code == 200  # the list, not a run


def test_cli_query_shows_the_refusal(lab: dict[str, Any], monkeypatch: Any) -> None:
    token = token_for(lab, "aud")

    def factory(creds: Credentials) -> TestClient:
        c = TestClient(lab["app"], base_url=BASE)
        c.headers["Accept"] = "application/json"
        return c

    monkeypatch.setattr(cli, "client_factory", factory)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(lab["tmp"] / "cfg"))
    monkeypatch.setenv("REMNANT_SERVER", BASE)
    monkeypatch.setenv("REMNANT_TOKEN", token)
    res = CliRunner().invoke(cli.app, ["query", SQL])
    assert res.exit_code == 1
    assert "Auditors cannot run SQL" in res.stderr
