"""Recommended rules for the caller's sources: logsource match, compile check, access
scope, and approve-only enabling (review item 10)."""

import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.core.errors import RuleRejectedError
from app.detect import runner as runner_module
from app.main import create_app

FIX = Path(__file__).parent.parent / "fixtures" / "logs"
ADMIN_PW = "correct horse battery"
USER_PW = "another long passphrase"
BASE = "https://siem.example.internal"

WIN_ID = "22222222-2222-4222-8222-222222222222"
WIN2_ID = "44444444-4444-4444-8444-444444444444"
LINUX_ID = "11111111-1111-4111-8111-111111111111"
MAC_ID = "33333333-3333-4333-8333-333333333333"
RULES = {
    "win.yml": f"""title: Failed logon
id: {WIN_ID}
author: Jane Doe
level: medium
tags: [attack.credential-access, attack.t1110, cve.2026-0001]
logsource: {{product: windows, service: security}}
detection:
  s: {{EventID: 4625}}
  condition: s
""",
    "win2.yml": f"""title: Account locked
id: {WIN2_ID}
level: high
logsource: {{product: windows, service: security}}
detection:
  s: {{EventID: 4740}}
  condition: s
""",
    "lin.yml": f"""title: SSH failed password
id: {LINUX_ID}
level: low
logsource: {{product: linux}}
detection:
  k: ['Failed password']
  condition: k
""",
    "mac.yml": f"""title: Mac only
id: {MAC_ID}
logsource: {{product: macos}}
detection:
  k: ['x']
  condition: k
""",
}


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    logs = tmp_path / "logs"
    (logs / "win").mkdir(parents=True)
    (logs / "lin").mkdir()
    shutil.copy(FIX / "windows_nxlog_json" / "sample.log", logs / "win" / "dc.log")
    shutil.copy(FIX / "linux_sshd" / "sample.log", logs / "lin" / "auth.log")
    rules = tmp_path / "rules"
    rules.mkdir()
    for name, text in RULES.items():
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
    assert admin.post("/api/rules/import", json={"path": str(rules)}, headers=h).status_code == 200
    res = admin.post("/api/users", json={"username": "ana", "role": "analyst"}, headers=h)
    ana_id = res.json()["user"]["user_id"]
    admin.post(
        "/api/account/password", json={"token": res.json()["invite_token"], "password": USER_PW}
    )
    login = TestClient(app, base_url=BASE).post(
        "/api/auth/login", json={"username": "ana", "password": USER_PW, "client": "cli"}
    )
    ana = TestClient(
        app, base_url=BASE, headers={"Authorization": f"Bearer {login.json()['token']}"}
    )
    gid = admin.post("/api/groups", json={"name": "Linux"}, headers=h).json()["group_id"]
    admin.put(f"/api/groups/{gid}/sources", json={"source_ids": ["lin_auth"]}, headers=h)
    admin.put(f"/api/groups/{gid}/members", json={"user_ids": [ana_id]}, headers=h)
    return {"app": app, "admin": admin, "ana": ana, "h": h, "db": tmp_path / "data" / "meta.sqlite"}


def recommended(client: TestClient) -> list[dict[str, Any]]:
    res = client.get("/api/rules/recommended")
    assert res.status_code == 200, res.text
    rows: list[dict[str, Any]] = res.json()
    return rows


def audit_actions(db: Path) -> list[tuple[str, str | None]]:
    with sqlite3.connect(db) as con:
        return [
            (str(a), u)
            for a, u in con.execute("SELECT action, user_id FROM audit_log ORDER BY audit_id")
        ]


def test_rules_are_recommended_by_logsource_with_their_sources_and_attack_tags(
    lab: dict[str, Any],
) -> None:
    rows = recommended(lab["admin"])
    # Highest level first; the macOS rule matches no source and is not listed.
    assert [r["rule_id"] for r in rows] == [WIN2_ID, WIN_ID, LINUX_ID]
    by_id = {r["rule_id"]: r for r in rows}
    assert by_id[WIN_ID]["source_ids"] == ["win_dc"]
    assert by_id[LINUX_ID]["source_ids"] == ["lin_auth"]
    assert by_id[WIN_ID]["attack_tags"] == ["attack.credential-access", "attack.t1110"]
    assert by_id[WIN_ID]["level"] == "medium"
    assert (by_id[WIN_ID]["product"], by_id[WIN_ID]["service"]) == ("windows", "security")
    assert all(r["enabled"] is False for r in rows)


def test_a_restricted_source_never_produces_recommendations(lab: dict[str, Any]) -> None:
    """ana may read lin_auth only: the Windows source's logsource must not show up."""
    rows = recommended(lab["ana"])
    assert [r["rule_id"] for r in rows] == [LINUX_ID]
    assert rows[0]["source_ids"] == ["lin_auth"]


def test_rules_that_do_not_compile_now_are_not_listed(
    lab: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    real = runner_module.compile_rule

    def compile_rule(data: bytes) -> Any:
        if b"Account locked" in data:
            raise RuleRejectedError("Windows service 'security' is not supported yet")
        return real(data)

    monkeypatch.setattr(runner_module, "compile_rule", compile_rule)
    assert WIN2_ID not in [r["rule_id"] for r in recommended(lab["admin"])]


def test_listing_enables_nothing_and_writes_no_audit_row(lab: dict[str, Any]) -> None:
    before = audit_actions(lab["db"])
    recommended(lab["admin"])
    recommended(lab["ana"])
    assert audit_actions(lab["db"]) == before
    assert not any(r["enabled"] for r in lab["admin"].get("/api/rules").json())


def test_an_admin_enables_a_recommended_rule_through_the_audited_enable_path(
    lab: dict[str, Any],
) -> None:
    res = lab["ana"].post("/api/rules/enabled", json={"rule_ids": [LINUX_ID], "enabled": True})
    assert res.status_code == 403
    res = lab["admin"].post(
        "/api/rules/enabled", json={"rule_ids": [WIN_ID], "enabled": True}, headers=lab["h"]
    )
    assert res.json() == {"changed": 1}
    with sqlite3.connect(lab["db"]) as con:
        (admin_id,) = con.execute("SELECT user_id FROM users WHERE username = 'admin'").fetchone()
    assert ("rule.enable", admin_id) in audit_actions(lab["db"])
    # Enabled rules leave the list; the rest stay disabled.
    assert [r["rule_id"] for r in recommended(lab["admin"])] == [WIN2_ID, LINUX_ID]
    enabled = {r["rule_id"] for r in lab["admin"].get("/api/rules").json() if r["enabled"]}
    assert enabled == {WIN_ID}
