"""/api/alert-targets: admin-managed, secrets never returned, real signed delivery (ADR-0007)."""

import hashlib
import hmac
import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.main import create_app

ADMIN_PW = "correct horse battery"
USER_PW = "another long passphrase"
BASE = "https://siem.example.internal"


class Receiver:
    def __init__(self) -> None:
        self.got: list[tuple[dict[str, str], bytes]] = []
        self.status = 200
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers["Content-Length"]))
                outer.got.append(({k.lower(): v for k, v in self.headers.items()}, body))
                self.send_response(outer.status)
                self.end_headers()

            def log_message(self, *a: Any) -> None:
                pass

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    config = load_config(
        Path("missing.yaml"),
        {"APP__PATHS__DATA_DIR": str(tmp_path / "data"), "APP__SERVER__HOST": "0.0.0.0",
         "APP__SERVER__PUBLIC_NAMES": "siem.example.internal"},
    )  # fmt: skip
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
    ana = TestClient(
        app, base_url=BASE, headers={"Authorization": f"Bearer {login.json()['token']}"}
    )
    rx = Receiver()
    yield {
        "app": app,
        "admin": admin,
        "h": h,
        "ana": ana,
        "rx": rx,
        "db": tmp_path / "data" / "meta.sqlite",
    }
    rx.server.shutdown()


def webhook(lab: dict[str, Any], path: str = "/hook/TOKEN123") -> Any:
    url = f"http://127.0.0.1:{lab['rx'].port}{path}"
    return lab["admin"].post(
        "/api/alert-targets",
        json={"name": "Relay", "kind": "webhook", "url": url},
        headers=lab["h"],
    )


def test_webhook_target_signs_and_never_returns_its_url(lab: dict[str, Any]) -> None:
    res = webhook(lab)
    assert res.status_code == 201, res.text
    created = res.json()
    key = created["signing_key"]
    assert key and created["display"] == "127.0.0.1"
    listed = lab["ana"].get("/api/alert-targets")  # analysts can pick targets
    assert listed.status_code == 200 and "TOKEN123" not in listed.text and key not in listed.text
    assert "signing_key" not in listed.json()[0]
    test = lab["admin"].post(f"/api/alert-targets/{created['target_id']}/test", headers=lab["h"])
    assert test.json() == {"ok": True, "detail": "Delivered"}
    ((headers, body),) = lab["rx"].got
    expected = hmac.new(
        key.encode(), headers["x-signature-timestamp"].encode() + b"." + body, hashlib.sha256
    )
    assert headers["x-signature-256"] == "sha256=" + expected.hexdigest()
    doc = json.loads(body)
    assert doc["kind"] == "test" and doc["link"] == "https://siem.example.internal:8080"
    with sqlite3.connect(lab["db"]) as db:
        (enc,) = db.execute("SELECT secret_enc FROM alert_targets").fetchone()
        actions = [
            a
            for (a,) in db.execute(
                "SELECT action FROM audit_log WHERE action LIKE 'alert_target.%'"
            )
        ]
    assert "TOKEN123" not in enc and key not in enc  # encrypted at rest
    assert actions == ["alert_target.create", "alert_target.test"]


def test_failures_are_counted_and_never_leak_the_url(lab: dict[str, Any]) -> None:
    tid = webhook(lab).json()["target_id"]
    lab["rx"].status = 500
    res = lab["admin"].post(f"/api/alert-targets/{tid}/test", headers=lab["h"]).json()
    assert res == {"ok": False, "detail": "The destination answered HTTP 500"}
    (t,) = lab["admin"].get("/api/alert-targets").json()
    assert t["consecutive_failures"] == 1 and "TOKEN123" not in (t["last_error"] or "")


@pytest.mark.parametrize(
    ("kind", "url", "reason"),
    [
        ("slack", "https://example.net/services/x", "hooks.slack.com"),
        ("teams", "https://outlook.office.com/webhook/x", "Workflows"),
        ("webhook", "http://169.254.169.254/latest/meta-data/", "not allowed"),
        ("webhook", "https://user:pw@127.0.0.1/x", "credentials"),
    ],
)
def test_bad_destinations_are_refused(
    lab: dict[str, Any], kind: str, url: str, reason: str
) -> None:
    res = lab["admin"].post(
        "/api/alert-targets", json={"name": "x", "kind": kind, "url": url}, headers=lab["h"]
    )
    assert res.status_code == 400 and reason in res.text


def test_only_admins_change_targets(lab: dict[str, Any]) -> None:
    tid = webhook(lab).json()["target_id"]
    ana = lab["ana"]
    assert (
        ana.post(
            "/api/alert-targets", json={"name": "y", "kind": "webhook", "url": "http://127.0.0.1/"}
        ).status_code
        == 403
    )
    assert ana.patch(f"/api/alert-targets/{tid}", json={"name": "z"}).status_code == 403
    assert ana.post(f"/api/alert-targets/{tid}/test").status_code == 403
    assert ana.delete(f"/api/alert-targets/{tid}").status_code == 403
    moved = lab["admin"].patch(
        f"/api/alert-targets/{tid}", json={"url": "http://169.254.169.254/"}, headers=lab["h"]
    )
    assert moved.status_code == 400  # the new URL is checked too
    assert (
        lab["admin"]
        .patch(f"/api/alert-targets/{tid}", json={"name": "Renamed"}, headers=lab["h"])
        .json()["name"]
        == "Renamed"
    )
    assert lab["admin"].delete(f"/api/alert-targets/{tid}", headers=lab["h"]).status_code == 204
    assert lab["admin"].get("/api/alert-targets").json() == []


def test_email_targets_keep_the_password_secret(lab: dict[str, Any]) -> None:
    body = {
        "name": "SOC mail",
        "kind": "email",
        "email": {"host": "127.0.0.1", "port": 2525, "security": "none", "username": "siem",
                  "from_addr": "siem@example.net", "to_addrs": ["soc@example.net"]},
        "password": "hunter2-long",
    }  # fmt: skip
    res = lab["admin"].post("/api/alert-targets", json=body, headers=lab["h"])
    assert res.status_code == 201, res.text
    out = lab["admin"].get("/api/alert-targets").text
    assert "hunter2-long" not in out and "soc@example.net" in out
    bad = {**body, "name": "Bad", "email": {**body["email"], "to_addrs": ["a@b.c\r\nBcc: x@y.z"]}}
    assert lab["admin"].post("/api/alert-targets", json=bad, headers=lab["h"]).status_code == 422
