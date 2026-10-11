"""Suggested source groups (SPEC 3.6, D22): suggestions only, approved one by one, audited,
never granting access to anyone."""

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.main import create_app

ADMIN_PW = "correct horse battery"


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    logs = tmp_path / "logs"
    for name in ("sshd", "sudo", "fw", "misc"):
        (logs / name).mkdir(parents=True)
    config = load_config(
        Path("missing.yaml"),
        {
            "APP__PATHS__DATA_DIR": str(tmp_path / "data"),
            "APP__PATHS__ALLOWED_ROOTS": str(logs),
            "APP__SERVER__HOST": "0.0.0.0",
        },
    )
    app = create_app(config)
    c = TestClient(app, base_url="https://siem.example.internal")
    token = app.state.auth.setup_url("siem.example.internal", 8080).split("#", 1)[1]
    csrf = c.post(
        "/api/setup", json={"token": token, "username": "admin", "password": ADMIN_PW}
    ).json()["csrf_token"]
    c.headers["X-CSRF-Token"] = csrf
    for sid, tid in (("sshd", "linux_sshd"), ("sudo", "linux_sudo"), ("fw", "paloalto_traffic")):
        body = {"source_id": sid, "format": "syslog", "path": str(logs / sid), "template_id": tid}
        assert c.post("/api/sources", json=body).status_code == 201
    generic = {"source_id": "misc", "format": "syslog", "path": str(logs / "misc")}
    assert c.post("/api/sources", json=generic).status_code == 201
    return {"c": c, "app": app, "tmp": tmp_path}


def _suggestions(lab: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    res = lab["c"].get("/api/groups/suggestions")
    assert res.status_code == 200, res.text
    return {(s["kind"], s["key"]): s for s in res.json()}


def test_categories_and_vendors_with_sources_are_suggested(lab: dict[str, Any]) -> None:
    s = _suggestions(lab)
    assert set(s) == {
        ("category", "identity"),
        ("category", "network"),
        ("vendor", "linux"),
        ("vendor", "paloalto"),
    }  # nothing for the generic source, nothing for empty categories
    identity = s[("category", "identity")]
    assert identity["name"] == "Identity" and identity["group_id"] is None
    assert identity["source_ids"] == ["sshd", "sudo"] and identity["missing"] == ["sshd", "sudo"]
    assert lab["c"].get("/api/groups").json() == []  # listing suggests, it creates nothing


def test_accepting_creates_the_group_adds_only_ticked_sources_and_grants_nobody(
    lab: dict[str, Any],
) -> None:
    c = lab["c"]
    res = c.post(
        "/api/groups/suggestions/accept",
        json={"kind": "category", "key": "identity", "source_ids": ["sshd"]},
    )
    assert res.status_code == 200, res.text
    group = res.json()
    assert group["name"] == "Identity"
    assert group["source_ids"] == ["sshd"] and group["user_ids"] == []
    assert _suggestions(lab)[("category", "identity")]["missing"] == ["sudo"]
    again = c.post(
        "/api/groups/suggestions/accept",
        json={"kind": "category", "key": "identity", "source_ids": ["sudo"]},
    ).json()
    assert again["group_id"] == group["group_id"]  # the same group, extended
    assert again["source_ids"] == ["sshd", "sudo"]  # never removes what is there
    with sqlite3.connect(lab["tmp"] / "data" / "meta.sqlite") as db:
        actions = [r[0] for r in db.execute("SELECT action FROM audit_log ORDER BY rowid")]
    assert actions.count("group.suggestion_accept") == 2


def test_only_sources_the_suggestion_lists_can_be_added(lab: dict[str, Any]) -> None:
    for bad in (["fw"], ["misc"], ["nope"], []):
        res = lab["c"].post(
            "/api/groups/suggestions/accept",
            json={"kind": "category", "key": "identity", "source_ids": bad},
        )
        assert res.status_code in (409, 422), (bad, res.status_code)
    res = lab["c"].post(
        "/api/groups/suggestions/accept",
        json={"kind": "category", "key": "findings", "source_ids": ["sshd"]},
    )
    assert res.status_code == 409  # no such suggestion
    assert lab["c"].get("/api/groups").json() == []
