"""ADR-0027: behind trusted proxies, the client address comes from X-Forwarded-For."""

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import load_config
from app.main import create_app
from tests.integration.test_auth import PASSWORD, do_setup

NODE = "192.0.2.11"  # one node of an HA proxy pair (the VIP is .20)
A, B = "198.51.100.7", "198.51.100.8"
WRONG = {"username": "admin", "password": "wrong password!"}


def make(tmp_path: Path, peer: str, trusted: str = "") -> tuple[TestClient, Path]:
    env = {"APP__PATHS__DATA_DIR": str(tmp_path / "data"), "APP__SERVER__HOST": "0.0.0.0"}
    if trusted:
        env["APP__SERVER__TRUSTED_PROXIES"] = trusted
    app = create_app(load_config(Path("missing.yaml"), env))
    client = TestClient(app, base_url="https://testserver", client=(peer, 50000))
    return client, tmp_path / "data" / "meta.sqlite"


def login_ips(db: Path) -> list[tuple[str, str]]:
    with sqlite3.connect(db) as con:
        rows = con.execute(
            "SELECT outcome, ip FROM audit_log WHERE action = 'auth.login' ORDER BY audit_id"
        )
        return [(r[0], r[1]) for r in rows]


def test_failed_logins_through_the_proxy_lock_out_only_that_client(tmp_path: Path) -> None:
    c, db = make(tmp_path, NODE, "192.0.2.10, 192.0.2.11, 192.0.2.20")
    do_setup(c)
    c.cookies.clear()
    for _ in range(5):
        c.post("/api/auth/login", json=WRONG, headers={"X-Forwarded-For": A})
    blocked = c.post(
        "/api/auth/login",
        json={"username": "admin", "password": PASSWORD},
        headers={"X-Forwarded-For": A},
    )
    assert blocked.status_code == 429
    ok = c.post(
        "/api/auth/login",
        json={"username": "admin", "password": PASSWORD},
        headers={"X-Forwarded-For": f"6.6.6.6, {B}"},  # the left entry is the client's own
    )
    assert ok.status_code == 200, ok.text
    ips = login_ips(db)
    assert ("failure", A) in ips and ("success", B) in ips
    assert all(ip != NODE for _, ip in ips)


def test_header_ignored_from_an_untrusted_peer(tmp_path: Path) -> None:
    c, db = make(tmp_path, "203.0.113.9", "192.0.2.10")
    do_setup(c)
    c.cookies.clear()
    c.post("/api/auth/login", json=WRONG, headers={"X-Forwarded-For": A})
    assert login_ips(db)[-1] == ("failure", "203.0.113.9")


def test_default_empty_list_ignores_the_header(tmp_path: Path) -> None:
    c, db = make(tmp_path, NODE)
    do_setup(c)
    c.cookies.clear()
    c.post("/api/auth/login", json=WRONG, headers={"X-Forwarded-For": A})
    assert login_ips(db)[-1] == ("failure", NODE)
