"""Every path that runs saved or library SQL resolves {{person:...}} the same way Ask does
(owner, 2026-11-04; D205, D208): Logs SQL, CSV export, facets, saved searches, schedules
and the dashboard panels that show their runs, the CLI, and the MCP server. Show events
is covered in test_person_placeholder.py. One person with two linked accounts, one
unlinked colleague, and a session with no name: the same three rows everywhere."""

import csv
import io
import json
from typing import Any

import pytest
from typer.testing import CliRunner

from app.cli import main as cli
from tests.integration.test_person_placeholder import RANGE, Q, lab  # noqa: F401  # fixture

ASK = {  # what Ask answers: person -> accounts
    "dana": "dana@example.com (work), dana@example.org (personal)",
    "erin": "erin@example.com (work)",
    "(no account reported)": "(no account reported)",
}


@pytest.fixture
def linked(lab: dict[str, Any]) -> dict[str, Any]:  # noqa: F811
    lab["app"].state.identities.set_alias("dana@example.org", "dana", "admin")
    return lab


def _people(columns: list[str], rows: list[list[Any]]) -> dict[str, str]:
    p, a = columns.index("person"), columns.index("accounts")
    return {r[p]: r[a] for r in rows}


def test_logs_sql_is_the_reference(linked: dict[str, Any]) -> None:
    res = linked["c"].post("/api/query", json={"sql": Q.sql, **RANGE}).json()
    assert _people(res["columns"], res["rows"]) == ASK


def test_csv_export(linked: dict[str, Any]) -> None:
    res = linked["c"].post("/api/query/export", json={"sql": Q.sql, **RANGE})
    assert res.status_code == 200, res.text
    table = list(csv.reader(io.StringIO(res.text)))
    assert _people(table[0], table[1:]) == ASK


def test_facets(linked: dict[str, Any]) -> None:
    sql = (
        "SELECT * FROM events WHERE template_id = 'claude_hooks'"
        " AND {{person:actor_user_name}} = 'dana'"
    )
    res = linked["c"].post(
        "/api/search/facets", json={"sql": sql, **RANGE, "columns": ["actor_user_name"]}
    )
    assert res.status_code == 200, res.text
    users = next(f for f in res.json()["facets"] if f["field"] == "actor_user_name")
    assert {v["value"] for v in users["values"]} == {"dana@example.com", "dana@example.org"}


def _saved(lab: dict[str, Any]) -> str:  # noqa: F811
    body = {"id": "claude_code_people", "name": "Who uses Claude Code", "sql": Q.sql}
    res = lab["c"].post("/api/searches", json=body)
    assert res.status_code == 201, res.text
    return str(res.json()["id"])


def test_saved_search(linked: dict[str, Any]) -> None:
    sid = _saved(linked)
    res = linked["c"].post(f"/api/searches/{sid}/run", json=RANGE)
    assert res.status_code == 200, res.text
    assert _people(res.json()["columns"], res.json()["rows"]) == ASK


def test_schedule_and_its_dashboard_panel(linked: dict[str, Any]) -> None:
    c = linked["c"]
    sid = _saved(linked)
    made = c.post(
        "/api/schedules",
        json={"kind": "search", "target_id": sid, "cron": "daily", "lookback_minutes": 527_040},
    )
    assert made.status_code == 201, made.text
    sched = made.json()["schedule_id"]
    run = c.post(f"/api/schedules/{sched}/run")
    assert run.status_code == 200, run.text
    assert _people(run.json()["columns"], run.json()["sample"]) == ASK
    # The panel shows that run, read back the way the dashboard reads it.
    boards = c.get("/api/dashboards").json()
    assert any(p["schedule_id"] == sched for d in boards for p in d["panels"])
    shown = c.get(f"/api/schedules/{sched}/runs/{run.json()['run_id']}").json()
    assert _people(shown["columns"], shown["sample"]) == ASK


def test_cli_query(linked: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    from fastapi.testclient import TestClient

    def factory(creds: Any) -> TestClient:
        client = TestClient(linked["app"])
        client.headers["Accept"] = "application/json"
        return client

    monkeypatch.setattr(cli, "client_factory", factory)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("REMNANT_TOKEN", raising=False)
    monkeypatch.delenv("REMNANT_SERVER", raising=False)
    res = CliRunner().invoke(cli.app, ["query", "--since", "3650d", "--format", "json", Q.sql])
    assert res.exit_code == 0, res.stdout + res.stderr
    rows = [json.loads(line) for line in res.stdout.splitlines() if line.strip()]
    assert {r["person"]: r["accounts"] for r in rows} == ASK


def _mcp(c: Any, sql: str) -> tuple[bool, Any]:
    body = {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "run_query", "arguments": {"sql": sql, "since_hours": 24 * 3650}},
    }  # fmt: skip
    res = c.post("/api/mcp", json=body)
    assert res.status_code == 200, res.text
    out = res.json()["result"]
    return bool(out["isError"]), json.loads(out["content"][0]["text"])


def test_mcp_run_query(linked: dict[str, Any]) -> None:
    c = linked["c"]
    res = c.put("/api/mcp/settings", json={"enabled": True, "endpoint_local": True})
    assert res.status_code == 200, res.text
    err, out = _mcp(c, Q.sql)
    assert not err, out
    assert _people(out["columns"], out["rows"]) == ASK
    # Any other {{name}} has no value over MCP: refused with a reason, not a wrong answer.
    err, out = _mcp(c, "SELECT * FROM events WHERE actor_user_name = {{who}}")
    assert err and "{{who}}" in out["error"]
