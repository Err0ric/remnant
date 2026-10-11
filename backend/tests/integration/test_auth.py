"""Accounts: first-run setup link, login, sessions, CSRF, rate limit, roles, audit (ADR-0001)."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth.passwords import hash_password
from app.core.config import load_config
from app.main import create_app

PASSWORD = "correct horse battery"
QUERY = {"sql": "SELECT 1 AS one"}


def make(tmp_path: Path, host: str = "0.0.0.0") -> TestClient:
    config = load_config(
        Path("missing.yaml"),
        {"APP__PATHS__DATA_DIR": str(tmp_path / "data"), "APP__SERVER__HOST": host},
    )
    base = "http://127.0.0.1" if host == "127.0.0.1" else "https://testserver"
    return TestClient(create_app(config), base_url=base)


def setup_token(client: TestClient) -> str:
    url: str = client.app.state.auth.setup_url("siem.example.internal", 8080)  # type: ignore[attr-defined]  # Starlette app typed loosely
    assert "#" in url  # token travels in the fragment, so it never reaches access logs
    return url.split("#", 1)[1]


def do_setup(client: TestClient) -> dict[str, str]:
    res = client.post(
        "/api/setup",
        json={"token": setup_token(client), "username": "admin", "password": PASSWORD},
    )
    assert res.status_code == 201, res.text
    return {"X-CSRF-Token": res.json()["csrf_token"]}


def add_user(client: TestClient, username: str, role: str, disabled: bool = False) -> None:
    client.app.state.auth.users.create(username, PASSWORD, role, disabled=disabled)  # type: ignore[attr-defined]


# --- modes --------------------------------------------------------------------------


def test_loopback_without_users_is_open(tmp_path: Path) -> None:
    c = make(tmp_path, "127.0.0.1")
    assert c.get("/api/auth/state").json()["mode"] == "open"
    assert c.post("/api/query", json=QUERY).status_code == 200


def test_network_bind_without_users_is_setup_only(tmp_path: Path) -> None:
    c = make(tmp_path)
    state = c.get("/api/auth/state").json()
    assert state["mode"] == "setup"
    for method, path in [
        ("post", "/api/query"),
        ("get", "/api/sources"),
        ("get", "/api/schema/columns"),
    ]:
        res = getattr(c, method)(path, **({"json": QUERY} if method == "post" else {}))
        assert res.status_code == 403
        assert res.json()["code"] == "setup_required"
    assert c.get("/api/meta").status_code == 200


def test_setup_creates_admin_and_signs_in(tmp_path: Path) -> None:
    c = make(tmp_path)
    csrf = do_setup(c)
    state = c.get("/api/auth/state").json()
    assert state["mode"] == "login"
    assert state["user"]["username"] == "admin"
    assert state["user"]["role"] == "admin"
    assert c.post("/api/query", json=QUERY, headers=csrf).status_code == 200


def test_setup_link_is_single_use(tmp_path: Path) -> None:
    c = make(tmp_path)
    token = setup_token(c)
    body = {"token": token, "username": "admin", "password": PASSWORD}
    assert c.post("/api/setup", json=body).status_code == 201
    again = c.post("/api/setup", json=body | {"username": "second"})
    assert again.status_code == 409
    assert again.json()["code"] == "setup_closed"


def test_setup_rejects_wrong_token(tmp_path: Path) -> None:
    c = make(tmp_path)
    setup_token(c)
    res = c.post("/api/setup", json={"token": "x" * 43, "username": "admin", "password": PASSWORD})
    assert res.status_code == 403
    assert res.json()["code"] == "setup_invalid"


def test_setup_link_expires_after_30_minutes(tmp_path: Path) -> None:
    c = make(tmp_path)
    token = setup_token(c)
    auth = c.app.state.auth  # type: ignore[attr-defined]
    auth.clock = lambda: datetime.now(UTC) + timedelta(minutes=31)
    res = c.post("/api/setup", json={"token": token, "username": "admin", "password": PASSWORD})
    assert res.status_code == 403


def test_new_setup_link_invalidates_old(tmp_path: Path) -> None:
    c = make(tmp_path)
    old = setup_token(c)
    setup_token(c)  # a restart issues a fresh link
    res = c.post("/api/setup", json={"token": old, "username": "admin", "password": PASSWORD})
    assert res.status_code == 403


def test_short_password_rejected(tmp_path: Path) -> None:
    c = make(tmp_path)
    res = c.post(
        "/api/setup", json={"token": setup_token(c), "username": "admin", "password": "short"}
    )
    assert res.status_code == 422


def test_passwords_stored_as_argon2id(tmp_path: Path) -> None:
    c = make(tmp_path)
    do_setup(c)
    db = tmp_path / "data" / "meta.sqlite"
    (stored,) = sqlite3.connect(db).execute("SELECT password_hash FROM users").fetchone()
    assert stored.startswith("$argon2id$")
    assert PASSWORD not in stored


# --- login, sessions, CSRF ----------------------------------------------------------


def test_users_exist_on_loopback_requires_login(tmp_path: Path) -> None:
    c = make(tmp_path, "127.0.0.1")
    add_user(c, "jordan", "analyst")
    assert c.get("/api/auth/state").json()["mode"] == "login"
    res = c.post("/api/query", json=QUERY)
    assert res.status_code == 401
    assert res.json()["code"] == "auth_required"


def test_login_cookie_flags(tmp_path: Path) -> None:
    c = make(tmp_path)
    do_setup(c)
    c.post(
        "/api/auth/logout", headers={"X-CSRF-Token": c.get("/api/auth/state").json()["csrf_token"]}
    )
    res = c.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert res.status_code == 200
    cookie = res.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "secure" in cookie


def test_loopback_cookie_not_secure(tmp_path: Path) -> None:
    c = make(tmp_path, "127.0.0.1")
    add_user(c, "jordan", "analyst")
    res = c.post("/api/auth/login", json={"username": "jordan", "password": PASSWORD})
    assert "secure" not in res.headers["set-cookie"].lower()


def test_csrf_required_for_cookie_posts(tmp_path: Path) -> None:
    c = make(tmp_path)
    csrf = do_setup(c)
    res = c.post("/api/query", json=QUERY)
    assert res.status_code == 403
    assert res.json()["code"] == "csrf_failed"
    assert c.post("/api/query", json=QUERY, headers={"X-CSRF-Token": "nope"}).status_code == 403
    assert c.post("/api/query", json=QUERY, headers=csrf).status_code == 200


def test_wrong_password_and_unknown_user_look_the_same(tmp_path: Path) -> None:
    c = make(tmp_path)
    do_setup(c)
    c.cookies.clear()
    a = c.post("/api/auth/login", json={"username": "admin", "password": "wrong password!"})
    b = c.post("/api/auth/login", json={"username": "ghost", "password": "wrong password!"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_login_rate_limited(tmp_path: Path) -> None:
    c = make(tmp_path)
    do_setup(c)
    c.cookies.clear()
    for _ in range(5):
        c.post("/api/auth/login", json={"username": "admin", "password": "wrong password!"})
    res = c.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert res.status_code == 429
    assert res.json()["code"] == "rate_limited"
    assert "retry-after" in res.headers


def test_disabled_user_cannot_login(tmp_path: Path) -> None:
    c = make(tmp_path, "127.0.0.1")
    add_user(c, "kelly", "analyst", disabled=True)
    assert (
        c.post("/api/auth/login", json={"username": "kelly", "password": PASSWORD}).status_code
        == 401
    )


def test_cli_login_returns_bearer_token(tmp_path: Path) -> None:
    c = make(tmp_path)
    do_setup(c)
    c.cookies.clear()
    res = c.post(
        "/api/auth/login", json={"username": "admin", "password": PASSWORD, "client": "cli"}
    )
    assert res.status_code == 200
    assert "set-cookie" not in res.headers
    bearer = {"Authorization": f"Bearer {res.json()['token']}"}
    assert c.post("/api/query", json=QUERY, headers=bearer).status_code == 200  # no CSRF for bearer
    assert c.post("/api/auth/logout", headers=bearer).status_code == 204
    assert c.post("/api/query", json=QUERY, headers=bearer).status_code == 401


def test_session_expires(tmp_path: Path) -> None:
    c = make(tmp_path)
    csrf = do_setup(c)
    c.app.state.auth.clock = lambda: datetime.now(UTC) + timedelta(hours=13)  # type: ignore[attr-defined]
    assert c.post("/api/query", json=QUERY, headers=csrf).status_code == 401


# --- roles and audit ----------------------------------------------------------------


def test_analyst_cannot_manage_sources(tmp_path: Path) -> None:
    c = make(tmp_path, "127.0.0.1")
    add_user(c, "jordan", "analyst")
    res = c.post(
        "/api/auth/login", json={"username": "jordan", "password": PASSWORD, "client": "cli"}
    )
    bearer = {"Authorization": f"Bearer {res.json()['token']}"}
    assert c.get("/api/sources", headers=bearer).status_code == 200
    denied = c.post(
        "/api/sources", json={"source_id": "x", "format": "syslog", "path": "/tmp"}, headers=bearer
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "forbidden"


def test_audit_rows_carry_user_and_cannot_be_changed(tmp_path: Path) -> None:
    c = make(tmp_path)
    csrf = do_setup(c)
    c.post("/api/query", json=QUERY, headers=csrf)
    c.cookies.clear()
    c.post("/api/auth/login", json={"username": "admin", "password": "wrong password!"})

    db = sqlite3.connect(tmp_path / "data" / "meta.sqlite")
    rows = db.execute("SELECT action, outcome, user_id FROM audit_log ORDER BY audit_id").fetchall()
    actions = [(a, o) for a, o, _ in rows]
    assert ("setup.admin_created", "success") in actions
    assert ("query.run", "success") in actions
    assert ("auth.login", "failure") in actions
    assert all(u for a, _, u in rows if a == "query.run")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        db.execute("DELETE FROM audit_log")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        db.execute("UPDATE audit_log SET outcome = 'success'")


def test_reset_password_from_server_cli(tmp_path: Path) -> None:
    from app.auth.users import UserStore
    from app.meta.db import MetaDB

    c = make(tmp_path)
    do_setup(c)
    store = UserStore(MetaDB(tmp_path / "data" / "meta.sqlite"))
    store.set_password("admin", "a brand new passphrase")
    c.cookies.clear()
    ok = c.post("/api/auth/login", json={"username": "admin", "password": "a brand new passphrase"})
    assert ok.status_code == 200
    assert hash_password("x").startswith("$argon2id$")
