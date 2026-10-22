"""User administration: invite, roles, disable, reset, last-admin guard (ADR-0004)."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import load_config
from app.main import create_app

ADMIN_PW = "correct horse battery"
USER_PW = "another long passphrase"


def server(tmp_path: Path, host: str = "0.0.0.0") -> TestClient:
    config = load_config(
        Path("missing.yaml"),
        {"APP__PATHS__DATA_DIR": str(tmp_path / "data"), "APP__SERVER__HOST": host},
    )
    base = "http://127.0.0.1" if host == "127.0.0.1" else "https://siem.example.internal"
    return TestClient(create_app(config), base_url=base)


def admin_client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    c = server(tmp_path)
    token = c.app.state.auth.setup_url("siem.example.internal", 8080).split("#", 1)[1]  # type: ignore[attr-defined]
    res = c.post("/api/setup", json={"token": token, "username": "admin", "password": ADMIN_PW})
    return c, {"X-CSRF-Token": res.json()["csrf_token"]}


def invite(
    c: TestClient, h: dict[str, str], username: str, role: str = "analyst"
) -> tuple[str, str]:
    res = c.post("/api/users", json={"username": username, "role": role}, headers=h)
    assert res.status_code == 201, res.text
    body = res.json()
    return body["user"]["user_id"], body["invite_token"]


def accept(c: TestClient, token: str, password: str = USER_PW) -> int:
    return c.post("/api/account/password", json={"token": token, "password": password}).status_code


def login(c: TestClient, username: str, password: str = USER_PW) -> dict[str, str] | None:
    fresh = TestClient(c.app, base_url=str(c.base_url))
    res = fresh.post(
        "/api/auth/login", json={"username": username, "password": password, "client": "cli"}
    )
    return {"Authorization": f"Bearer {res.json()['token']}"} if res.status_code == 200 else None


def audit_actions(tmp_path: Path) -> list[str]:
    db = sqlite3.connect(tmp_path / "data" / "meta.sqlite")
    return [r[0] for r in db.execute("SELECT action FROM audit_log ORDER BY audit_id")]


# --- invites ---------------------------------------------------------------------------


def test_invite_then_user_sets_own_password_and_signs_in(tmp_path: Path) -> None:
    c, h = admin_client(tmp_path)
    _, token = invite(c, h, "jordan")
    assert login(c, "jordan") is None  # no password until the invite is used
    assert accept(c, token) == 204
    assert login(c, "jordan") is not None
    listed = {u["username"]: u for u in c.get("/api/users").json()}
    assert listed["admin"]["last_login_at"] is not None  # setup signs the admin in
    assert listed["jordan"]["role"] == "analyst"
    assert listed["jordan"]["pending"] is False
    assert "user.invite" in audit_actions(tmp_path)
    assert "user.password_set" in audit_actions(tmp_path)


def test_invite_token_is_single_use_and_stored_hashed(tmp_path: Path) -> None:
    c, h = admin_client(tmp_path)
    _, token = invite(c, h, "jordan")
    db = sqlite3.connect(tmp_path / "data" / "meta.sqlite")
    stored = [r[0] for r in db.execute("SELECT token_hash FROM user_tokens")]
    assert token not in stored and len(stored) == 1
    assert accept(c, token) == 204
    assert accept(c, token, "a different passphrase") == 403
    assert login(c, "jordan", "a different passphrase") is None


def test_invite_expires_after_24_hours(tmp_path: Path) -> None:
    c, h = admin_client(tmp_path)
    _, token = invite(c, h, "jordan")
    c.app.state.auth.clock = lambda: datetime.now(UTC) + timedelta(hours=25)  # type: ignore[attr-defined]
    assert accept(c, token) == 403


def test_bad_invite_tokens_are_rate_limited(tmp_path: Path) -> None:
    c, _ = admin_client(tmp_path)
    codes = [accept(c, "x" * 43) for _ in range(7)]
    assert codes[:5] == [403] * 5
    assert codes[-1] == 429


def test_duplicate_username_rejected(tmp_path: Path) -> None:
    c, h = admin_client(tmp_path)
    invite(c, h, "jordan")
    res = c.post("/api/users", json={"username": "JORDAN", "role": "analyst"}, headers=h)
    assert res.status_code == 409


def test_weak_password_on_accept_rejected(tmp_path: Path) -> None:
    c, h = admin_client(tmp_path)
    _, token = invite(c, h, "jordan")
    assert accept(c, token, "short") == 422
    assert accept(c, token) == 204  # token not burned by the rejected attempt


def test_tokenless_and_failed_visits_leave_the_invite_usable(tmp_path: Path) -> None:
    """A forward-auth proxy can return the user to /account without the `#` code. That
    visit, and any failed attempt, must not spend the invite (owner report 2026-10-22)."""
    c, h = admin_client(tmp_path)
    _, token = invite(c, h, "jordan")
    c.get("/account")  # the page itself: a fragment is never sent, so the server sees no code
    c.get("/api/auth/state")  # what the page asks on load
    assert c.post("/api/account/password", json={"password": USER_PW}).status_code == 422
    assert (
        c.post("/api/account/password", json={"token": "", "password": USER_PW}).status_code == 422
    )
    assert accept(c, "wrong-" + token[6:]) == 403
    assert accept(c, token, "short") == 422
    assert accept(c, token) == 204
    assert login(c, "jordan") is not None


# --- roles and admin-only routes --------------------------------------------------------


def test_only_admins_manage_users(tmp_path: Path) -> None:
    c, h = admin_client(tmp_path)
    _, token = invite(c, h, "jordan")
    accept(c, token)
    analyst = login(c, "jordan")
    assert analyst is not None
    fresh = TestClient(c.app, base_url=str(c.base_url))
    assert fresh.get("/api/users", headers=analyst).status_code == 403
    res = fresh.post("/api/users", json={"username": "x", "role": "admin"}, headers=analyst)
    assert res.status_code == 403


def test_role_change_applies_on_next_request(tmp_path: Path) -> None:
    c, h = admin_client(tmp_path)
    user_id, token = invite(c, h, "jordan")
    accept(c, token)
    bearer = login(c, "jordan")
    assert bearer is not None
    fresh = TestClient(c.app, base_url=str(c.base_url))
    assert fresh.get("/api/users", headers=bearer).status_code == 403
    assert c.patch(f"/api/users/{user_id}", json={"role": "admin"}, headers=h).status_code == 200
    assert fresh.get("/api/users", headers=bearer).status_code == 200
    assert "user.role_change" in audit_actions(tmp_path)


def test_disable_revokes_sessions_immediately(tmp_path: Path) -> None:
    c, h = admin_client(tmp_path)
    user_id, token = invite(c, h, "jordan")
    accept(c, token)
    bearer = login(c, "jordan")
    assert bearer is not None
    fresh = TestClient(c.app, base_url=str(c.base_url))
    assert fresh.post("/api/query", json={"sql": "SELECT 1"}, headers=bearer).status_code == 200
    assert c.patch(f"/api/users/{user_id}", json={"disabled": True}, headers=h).status_code == 200
    assert fresh.post("/api/query", json={"sql": "SELECT 1"}, headers=bearer).status_code == 401
    assert login(c, "jordan") is None
    # Re-enabling does not resurrect old sessions.
    c.patch(f"/api/users/{user_id}", json={"disabled": False}, headers=h)
    assert fresh.post("/api/query", json={"sql": "SELECT 1"}, headers=bearer).status_code == 401
    assert login(c, "jordan") is not None


def test_last_admin_cannot_be_disabled_or_demoted(tmp_path: Path) -> None:
    c, h = admin_client(tmp_path)
    me = next(u for u in c.get("/api/users").json() if u["username"] == "admin")
    for change in ({"disabled": True}, {"role": "analyst"}):
        res = c.patch(f"/api/users/{me['user_id']}", json=change, headers=h)
        assert res.status_code == 409
        assert res.json()["code"] == "last_admin"


def test_second_admin_allows_demoting_the_first(tmp_path: Path) -> None:
    c, h = admin_client(tmp_path)
    _, token = invite(c, h, "second", "admin")
    accept(c, token)
    me = next(u for u in c.get("/api/users").json() if u["username"] == "admin")
    assert (
        c.patch(f"/api/users/{me['user_id']}", json={"role": "analyst"}, headers=h).status_code
        == 200
    )


def test_pending_admin_does_not_count_as_active(tmp_path: Path) -> None:
    c, h = admin_client(tmp_path)
    invite(c, h, "second", "admin")  # never accepted
    me = next(u for u in c.get("/api/users").json() if u["username"] == "admin")
    assert (
        c.patch(f"/api/users/{me['user_id']}", json={"disabled": True}, headers=h).status_code
        == 409
    )


def test_unknown_user_is_404(tmp_path: Path) -> None:
    c, h = admin_client(tmp_path)
    res = c.patch(
        "/api/users/00000000-0000-4000-8000-000000000000", json={"disabled": True}, headers=h
    )
    assert res.status_code == 404


# --- reset ------------------------------------------------------------------------------


def test_reset_link_sets_new_password_and_ends_sessions(tmp_path: Path) -> None:
    c, h = admin_client(tmp_path)
    user_id, token = invite(c, h, "jordan")
    accept(c, token)
    bearer = login(c, "jordan")
    assert bearer is not None
    res = c.post(f"/api/users/{user_id}/reset", headers=h)
    assert res.status_code == 200
    reset_token = res.json()["reset_token"]
    assert accept(c, reset_token, "brand new passphrase") == 204
    fresh = TestClient(c.app, base_url=str(c.base_url))
    assert fresh.post("/api/query", json={"sql": "SELECT 1"}, headers=bearer).status_code == 401
    assert login(c, "jordan", USER_PW) is None
    assert login(c, "jordan", "brand new passphrase") is not None
    assert "user.reset_issued" in audit_actions(tmp_path)


def test_new_reset_link_invalidates_older_one(tmp_path: Path) -> None:
    c, h = admin_client(tmp_path)
    user_id, token = invite(c, h, "jordan")
    accept(c, token)
    first = c.post(f"/api/users/{user_id}/reset", headers=h).json()["reset_token"]
    second = c.post(f"/api/users/{user_id}/reset", headers=h).json()["reset_token"]
    assert accept(c, first) == 403
    assert accept(c, second) == 204


def test_disabled_user_cannot_use_a_reset_link(tmp_path: Path) -> None:
    c, h = admin_client(tmp_path)
    user_id, token = invite(c, h, "jordan")
    accept(c, token)
    reset_token = c.post(f"/api/users/{user_id}/reset", headers=h).json()["reset_token"]
    c.patch(f"/api/users/{user_id}", json={"disabled": True}, headers=h)
    assert accept(c, reset_token) == 403


# --- open local mode --------------------------------------------------------------------


def test_first_account_on_open_install_must_be_admin(tmp_path: Path) -> None:
    c = server(tmp_path, "127.0.0.1")
    res = c.post("/api/users", json={"username": "jordan", "role": "analyst"})
    assert res.status_code == 409
    assert res.json()["code"] == "first_user_admin"
    assert c.post("/api/users", json={"username": "jordan", "role": "admin"}).status_code == 201


def test_nested_metadata_writes_fail_fast_instead_of_hanging(tmp_path: Path) -> None:
    import sqlite3 as _sqlite3
    import time

    import pytest

    from app.meta.db import MetaDB

    meta = MetaDB(tmp_path / "m.sqlite")
    started = time.monotonic()
    with pytest.raises(_sqlite3.OperationalError), meta.connect() as outer:
        outer.execute("BEGIN IMMEDIATE")
        with meta.connect() as inner:
            inner.execute("BEGIN IMMEDIATE")
    assert time.monotonic() - started < 10
