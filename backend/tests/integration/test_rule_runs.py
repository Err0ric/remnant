"""Sigma rule runs: logsource scope, caller scope, versions, visibility (ADR-0006)."""

import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.main import create_app

FIX = Path(__file__).parent.parent / "fixtures" / "logs"
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
ADMIN_PW = "correct horse battery"
USER_PW = "another long passphrase"
BASE = "https://siem.example.internal"
RANGE = {"start": "2026-10-01T00:00:00Z", "end": "2026-10-31T00:00:00Z"}

WIN = """title: Failed logon
id: 22222222-2222-4222-8222-222222222222
author: Jane Doe
logsource: {product: windows, service: security}
detection:
  s: {EventID: 4625}
  condition: s
"""
LINUX = """title: SSH failed password
id: 11111111-1111-4111-8111-111111111111
logsource: {product: linux}
detection:
  k: ['Failed password']
  condition: k
"""
MAC = """title: Mac only
id: 33333333-3333-4333-8333-333333333333
logsource: {product: macos}
detection:
  k: ['x']
  condition: k
"""
WIN_ID, LINUX_ID, MAC_ID = (
    "22222222-2222-4222-8222-222222222222",
    "11111111-1111-4111-8111-111111111111",
    "33333333-3333-4333-8333-333333333333",
)


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    logs = tmp_path / "logs"
    (logs / "win").mkdir(parents=True)
    (logs / "lin").mkdir()
    shutil.copy(FIX / "windows_nxlog_json" / "sample.log", logs / "win" / "dc.log")
    shutil.copy(FIX / "linux_sshd" / "sample.log", logs / "lin" / "auth.log")
    rules = tmp_path / "rules"
    rules.mkdir()
    for name, text in (("win.yml", WIN), ("lin.yml", LINUX), ("mac.yml", MAC)):
        (rules / name).write_text(text)
    config = load_config(
        Path("missing.yaml"),
        {
            "APP__PATHS__DATA_DIR": str(tmp_path / "data"),
            "APP__PATHS__ALLOWED_ROOTS": str(logs),
            "APP__PATHS__RULE_ROOTS": str(rules),
            "APP__SERVER__HOST": "0.0.0.0",
        },
    )
    app = create_app(config)
    app.state.ingest._clock = lambda: NOW
    admin = TestClient(app, base_url=BASE)
    token = app.state.auth.setup_url("siem.example.internal", 8080).split("#", 1)[1]
    csrf = admin.post(
        "/api/setup", json={"token": token, "username": "admin", "password": ADMIN_PW}
    ).json()["csrf_token"]
    h = {"X-CSRF-Token": csrf}
    for sid, tid, sub in (
        ("win_dc", "windows_nxlog_json", "win"),
        ("lin_auth", "linux_sshd", "lin"),
    ):
        res = admin.post(
            "/api/sources",
            json={
                "source_id": sid,
                "format": "syslog",
                "path": str(logs / sub),
                "template_id": tid,
            },
            headers=h,
        )
        assert res.status_code == 201, res.text
    app.state.ingest.run_once()
    assert admin.post("/api/rules/import", json={"path": str(rules)}, headers=h).status_code == 200
    admin.post(
        "/api/rules/enabled",
        json={"rule_ids": [WIN_ID, LINUX_ID, MAC_ID], "enabled": True},
        headers=h,
    )
    clients = {}
    ids = {}
    for name, role in (("ana", "analyst"), ("aud", "auditor")):
        res = admin.post("/api/users", json={"username": name, "role": role}, headers=h)
        ids[name] = res.json()["user"]["user_id"]
        admin.post(
            "/api/account/password", json={"token": res.json()["invite_token"], "password": USER_PW}
        )
        login = TestClient(app, base_url=BASE).post(
            "/api/auth/login", json={"username": name, "password": USER_PW, "client": "cli"}
        )
        clients[name] = TestClient(
            app, base_url=BASE, headers={"Authorization": f"Bearer {login.json()['token']}"}
        )
    gid = admin.post("/api/groups", json={"name": "Linux"}, headers=h).json()["group_id"]
    admin.put(f"/api/groups/{gid}/sources", json={"source_ids": ["lin_auth"]}, headers=h)
    admin.put(f"/api/groups/{gid}/members", json={"user_ids": [ids["ana"], ids["aud"]]}, headers=h)
    return {"app": app, "admin": admin, "h": h, **clients, "db": tmp_path / "data" / "meta.sqlite"}


def run(client: TestClient, rule_id: str, h: dict[str, str] | None = None, **body: Any) -> Any:
    return client.post(f"/api/rules/{rule_id}/run", json={**RANGE, **body}, headers=h or {})


def test_a_windows_rule_reads_only_windows_sources_and_finds_every_match(
    lab: dict[str, Any],
) -> None:
    res = run(lab["admin"], WIN_ID, lab["h"])
    assert res.status_code == 200, res.text
    out = res.json()
    assert (out["status"], out["match_count"], out["sources_in_scope"]) == ("ok", 6, ["win_dc"])
    assert (out["title"], out["author"]) == ("Failed logon", "Jane Doe")  # DRL attribution
    matches = lab["admin"].get(f"/api/rules/runs/{out['run_id']}/matches").json()
    assert len(matches) == 6 and {m["source_id"] for m in matches} == {"win_dc"}
    ids = ", ".join(f"'{m['event_id']}'" for m in matches)
    rows = (
        lab["admin"]
        .post(
            "/api/query",
            json={
                "sql": f"SELECT DISTINCT raw LIKE '%\"EventID\": 4625%' FROM events WHERE event_id IN ({ids})"
            },
            headers=lab["h"],
        )
        .json()["rows"]
    )
    assert rows == [[True]]


def test_runs_stay_inside_the_callers_sources(lab: dict[str, Any]) -> None:
    out = run(lab["ana"], LINUX_ID).json()
    assert (out["status"], out["match_count"], out["sources_in_scope"]) == ("ok", 6, ["lin_auth"])
    # The analyst may not read the Windows source, so the Windows rule reads nothing.
    out = run(lab["ana"], WIN_ID).json()
    assert (out["status"], out["match_count"], out["sources_in_scope"]) == ("no_data", 0, [])
    admin_run = run(lab["admin"], WIN_ID, lab["h"]).json()
    # The admin's Windows run is invisible to the analyst; their own runs are listed.
    assert lab["ana"].get(f"/api/rules/runs/{admin_run['run_id']}").status_code == 404
    assert lab["ana"].get(f"/api/rules/runs/{admin_run['run_id']}/matches").status_code == 404
    listed = {r["run_id"] for r in lab["ana"].get("/api/rules/runs").json()}
    assert admin_run["run_id"] not in listed and len(listed) == 2
    assert len(lab["admin"].get(f"/api/rules/runs?rule_id={WIN_ID}").json()) == 2


def test_rules_with_no_matching_template_read_nothing(lab: dict[str, Any]) -> None:
    out = run(lab["admin"], MAC_ID, lab["h"]).json()
    assert (out["status"], out["sources_in_scope"]) == ("no_data", [])


def test_auditors_see_runs_but_cannot_start_them_and_disabled_rules_need_an_admin(
    lab: dict[str, Any],
) -> None:
    assert run(lab["aud"], LINUX_ID).status_code == 403
    out = run(lab["ana"], LINUX_ID).json()
    assert lab["aud"].get(f"/api/rules/runs/{out['run_id']}/matches").status_code == 200
    lab["admin"].post(
        "/api/rules/enabled", json={"rule_ids": [LINUX_ID], "enabled": False}, headers=lab["h"]
    )
    assert run(lab["ana"], LINUX_ID).status_code == 403
    assert run(lab["admin"], LINUX_ID, lab["h"]).json()["status"] == "ok"  # admin may test


def test_ranges_are_checked_and_runs_are_audited_and_not_editable(lab: dict[str, Any]) -> None:
    bad = run(lab["admin"], LINUX_ID, lab["h"], start="2026-10-31T00:00:00Z")
    assert bad.status_code == 400
    assert run(lab["admin"], LINUX_ID, lab["h"], end="2028-01-01T00:00:00Z").status_code == 400
    assert run(lab["admin"], "nope", lab["h"]).status_code == 404
    out = run(lab["admin"], LINUX_ID, lab["h"]).json()
    with sqlite3.connect(lab["db"]) as db:
        actions = db.execute(
            "SELECT outcome, detail FROM audit_log WHERE action = 'rule.run'"
        ).fetchall()
        assert len(actions) == 1 and out["run_id"] in actions[0][1]
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE rule_runs SET match_count = 0")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE rule_matches SET event_id = 'x'")


def test_the_rule_list_says_which_sources_each_rule_would_read(lab: dict[str, Any]) -> None:
    def by_id(client: TestClient) -> dict[str, list[str]]:
        return {r["rule_id"]: r["source_ids"] for r in client.get("/api/rules").json()}

    assert by_id(lab["admin"]) == {WIN_ID: ["win_dc"], LINUX_ID: ["lin_auth"], MAC_ID: []}
    assert by_id(lab["ana"]) == {WIN_ID: [], LINUX_ID: ["lin_auth"], MAC_ID: []}


def test_rules_on_an_automatic_source_read_only_rows_of_matching_templates(
    lab: dict[str, Any], tmp_path: Path
) -> None:
    """ADR-0012: a linux rule runs on an Automatic source, but only over rows a linux
    template read; the same words in a line the generic parser read do not match."""
    mixed = tmp_path / "logs" / "mixed"
    mixed.mkdir()
    (mixed / "syslog").write_text(
        "<38>Oct  9 20:02:25 db-01 sshd[13445]: Failed password for root from 192.0.2.7 port 4 ssh2\n"
        "<13>Oct  9 20:03:05 nas01 smbd[2201]: Failed password for share backup\n"
        '{"winlog": {"event_id": 4625}, "message": "Failed password"}\n'
    )
    res = lab["admin"].post(
        "/api/sources",
        json={"source_id": "mixed", "format": "syslog", "path": str(mixed), "template_id": "auto"},
        headers=lab["h"],
    )
    assert res.status_code == 201, res.text
    lab["app"].state.ingest.run_once()
    out = run(lab["admin"], LINUX_ID, lab["h"]).json()
    assert "mixed" in out["sources_in_scope"]
    matches = lab["admin"].get(f"/api/rules/runs/{out['run_id']}/matches").json()
    from_mixed = [m for m in matches if m["source_id"] == "mixed"]
    assert len(from_mixed) == 1
