"""POST /api/sources/discover: admin only, audited, read-only (SPEC 3.6)."""

import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.main import create_app

LOGS = Path(__file__).parent.parent / "fixtures" / "logs"
ADMIN_PW = "correct horse battery"
USER_PW = "another long passphrase"
BASE = "https://siem.example.internal"


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    root = tmp_path / "logs"
    (root / "192.0.2.10").mkdir(parents=True)
    shutil.copy(LOGS / "linux_sshd" / "sample.log", root / "192.0.2.10" / "sshd.log")
    config = load_config(
        Path("missing.yaml"),
        {
            "APP__PATHS__DATA_DIR": str(tmp_path / "data"),
            "APP__PATHS__ALLOWED_ROOTS": str(root),
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
        "analyst": {"Authorization": f"Bearer {login.json()['token']}"},
        "root": root,
        "tmp": tmp_path,
    }


def _audit(lab: dict[str, Any]) -> list[tuple[str, str]]:
    db = sqlite3.connect(lab["tmp"] / "data" / "meta.sqlite")
    return db.execute(
        "SELECT action, outcome FROM audit_log WHERE action = 'source.discover' ORDER BY audit_id"
    ).fetchall()


def test_admin_discovers_and_nothing_is_created(lab: dict[str, Any]) -> None:
    res = lab["admin"].post(
        "/api/sources/discover", json={"path": str(lab["root"])}, headers=lab["h"]
    )
    assert res.status_code == 200, res.text
    body = res.json()
    (cand,) = body["candidates"]
    assert cand["glob"] == "*/sshd.log" and cand["hosts"] == ["192.0.2.10"]
    best = cand["matches"][0]
    assert best["template_id"] == "linux_sshd" and best["passes"] is True
    assert cand["sniff"]["format"] == "plain" and cand["preview"]
    assert lab["admin"].get("/api/sources").json() == []  # suggestions only
    assert _audit(lab) == [("source.discover", "success")]


def test_outside_the_roots_is_refused_and_audited(lab: dict[str, Any]) -> None:
    res = lab["admin"].post(
        "/api/sources/discover", json={"path": str(lab["tmp"])}, headers=lab["h"]
    )
    assert res.status_code == 400
    assert _audit(lab) == [("source.discover", "failure")]


def test_analysts_cannot_discover(lab: dict[str, Any]) -> None:
    c = TestClient(lab["app"], base_url=BASE)
    res = c.post("/api/sources/discover", json={"path": str(lab["root"])}, headers=lab["analyst"])
    assert res.status_code == 403


def test_discover_needs_csrf(lab: dict[str, Any]) -> None:
    res = lab["admin"].post("/api/sources/discover", json={"path": str(lab["root"])})
    assert res.status_code == 403


def test_analysts_cannot_touch_template_drafts(lab: dict[str, Any]) -> None:
    c = TestClient(lab["app"], base_url=BASE)
    h = lab["analyst"]
    assert c.get("/api/templates/drafts", headers=h).status_code == 403
    body = {"template_id": "x_app", "sample": {"kind": "pasted", "text": "a\n"}}
    assert c.post("/api/templates/drafts", json=body, headers=h).status_code == 403
    assert c.get("/api/templates/linux_sshd/source", headers=h).status_code == 403
    assert c.delete("/api/templates/linux_sshd", headers=h).status_code == 403
    assert c.get("/api/templates", headers=h).status_code == 200  # listing stays open
