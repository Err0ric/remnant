"""/api/rules: admin imports pinned rule snapshots; enable is audited (ADR-0006)."""

import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.main import create_app

ADMIN_PW = "correct horse battery"
USER_PW = "another long passphrase"
BASE = "https://siem.example.internal"

LINUX = """title: Linux keyword
id: 11111111-1111-4111-8111-111111111111
author: Jane Doe
level: medium
logsource: {product: linux}
detection:
  k: ['session opened']
  condition: k
"""
WIN = """title: Failed logon
id: 22222222-2222-4222-8222-222222222222
author: A One, B Two
logsource: {product: windows, service: security}
detection:
  s: {EventID: 4625}
  condition: s
"""
BAD = """title: Unknown service
logsource: {product: windows, service: nosuchthing}
detection:
  s: {EventID: 1}
  condition: s
"""


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    rules = tmp_path / "rules"
    (rules / "linux").mkdir(parents=True)
    (rules / "windows").mkdir()
    (rules / ".git").mkdir()
    (rules / "linux" / "a.yml").write_text(LINUX)
    (rules / "windows" / "b.yaml").write_text(WIN)
    (rules / "windows" / "bad.yml").write_text(BAD)
    (rules / "windows" / "dup.yml").write_text(WIN.replace("Failed logon", "Copy"))
    (rules / ".git" / "hidden.yml").write_text(LINUX.replace("1111", "3333"))
    (rules / "README.md").write_text("not a rule")
    outside = tmp_path / "outside.yml"
    outside.write_text(LINUX.replace("1111", "4444"))
    os.symlink(outside, rules / "linux" / "escape.yml")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "c.yml").write_text(LINUX)
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
    res = admin.post("/api/users", json={"username": "ana", "role": "analyst"}, headers=h)
    admin.post(
        "/api/account/password", json={"token": res.json()["invite_token"], "password": USER_PW}
    )
    login = TestClient(app, base_url=BASE).post(
        "/api/auth/login", json={"username": "ana", "password": USER_PW, "client": "cli"}
    )
    return {
        "app": app,
        "admin": admin,
        "h": h,
        "analyst": TestClient(
            app, base_url=BASE, headers={"Authorization": f"Bearer {login.json()['token']}"}
        ),
        "rules": rules,
        "logs": logs,
        "db": tmp_path / "data" / "meta.sqlite",
    }


def audit(lab: dict[str, Any], prefix: str = "rule.") -> list[tuple[str, str]]:
    db = sqlite3.connect(lab["db"])
    return db.execute(
        "SELECT action, outcome FROM audit_log WHERE action LIKE ? ORDER BY audit_id",
        (prefix + "%",),
    ).fetchall()


def do_import(lab: dict[str, Any], path: Path) -> Any:
    return lab["admin"].post("/api/rules/import", json={"path": str(path)}, headers=lab["h"])


def test_import_pins_accepted_rules_disabled_and_reports_refusals(lab: dict[str, Any]) -> None:
    res = do_import(lab, lab["rules"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["files"], body["accepted"], body["new_rules"], body["refused"]) == (5, 2, 2, 3)
    reasons = {r["path"]: r["reason"] for r in body["refusals"]}
    assert "nosuchthing" in reasons["windows/bad.yml"]
    assert "Same rule id" in reasons["windows/dup.yml"]
    assert reasons["linux/escape.yml"] == "File could not be opened"  # symlink out of roots
    rules = lab["analyst"].get("/api/rules").json()  # every role can list
    assert [(r["title"], r["enabled"], r["author"]) for r in rules] == [
        ("Failed logon", False, "A One, B Two"),
        ("Linux keyword", False, "Jane Doe"),
    ]
    assert rules[0]["service"] == "security" and len(rules[0]["sha256"]) == 64
    assert audit(lab) == [("rule.import", "success")]
    detail = lab["analyst"].get(f"/api/rules/{rules[1]['rule_id']}").json()
    assert detail["yaml"] == LINUX


def test_reimport_keeps_enabled_state_and_moves_changed_rules(lab: dict[str, Any]) -> None:
    do_import(lab, lab["rules"])
    rid = "11111111-1111-4111-8111-111111111111"
    res = lab["admin"].post(
        "/api/rules/enabled", json={"rule_ids": [rid], "enabled": True}, headers=lab["h"]
    )
    assert res.json() == {"changed": 1}
    first = lab["admin"].get(f"/api/rules/{rid}").json()
    (lab["rules"] / "linux" / "a.yml").write_text(LINUX.replace("medium", "high"))
    body = do_import(lab, lab["rules"]).json()
    assert (body["new_rules"], body["updated"], body["unchanged"]) == (0, 1, 1)
    second = lab["admin"].get(f"/api/rules/{rid}").json()
    assert second["enabled"] is True and second["level"] == "high"
    assert second["sha256"] != first["sha256"]
    with sqlite3.connect(lab["db"]) as db:  # the old snapshot is still there, unchanged
        old = db.execute("SELECT yaml FROM rule_versions WHERE sha256 = ?", (first["sha256"],))
        assert old.fetchone()[0] == LINUX
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE rule_versions SET yaml = 'x'")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM rule_versions")
    assert audit(lab) == [
        ("rule.import", "success"),
        ("rule.enable", "success"),
        ("rule.import", "success"),
    ]


def test_only_admins_import_or_enable(lab: dict[str, Any]) -> None:
    ana = lab["analyst"]
    assert ana.post("/api/rules/import", json={"path": str(lab["rules"])}).status_code == 403
    assert (
        ana.post("/api/rules/enabled", json={"rule_ids": ["x"], "enabled": True}).status_code == 403
    )
    assert ana.get("/api/rules/imports").status_code == 403
    assert audit(lab) == []


def test_log_folders_and_paths_outside_rule_roots_are_refused(lab: dict[str, Any]) -> None:
    for path in (lab["logs"], lab["rules"] / ".." / "outside.yml", Path("/etc")):
        res = do_import(lab, path)
        assert res.status_code == 400, res.text
    assert audit(lab) == [("rule.import", "denied")] * 3
    assert lab["admin"].get("/api/rules").json() == []


def test_one_file_can_be_imported_and_history_is_kept(lab: dict[str, Any]) -> None:
    body = do_import(lab, lab["rules"] / "windows" / "b.yaml").json()
    assert (body["files"], body["accepted"]) == (1, 1)
    (imp,) = lab["admin"].get("/api/rules/imports").json()
    assert imp["accepted"] == 1 and imp["imported_by"]
    assert lab["admin"].get(f"/api/rules/imports/{imp['import_id']}/refusals").json() == []
    assert lab["admin"].get("/api/rules/nope").status_code == 404


def test_without_rule_roots_import_explains_the_setting(tmp_path: Path) -> None:
    config = load_config(Path("missing.yaml"), {"APP__PATHS__DATA_DIR": str(tmp_path / "d")})
    c = TestClient(create_app(config))
    res = c.post("/api/rules/import", json={"path": str(tmp_path)})
    assert res.status_code == 400 and "rule_roots" in res.text
