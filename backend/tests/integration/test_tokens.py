"""Per-user CLI and API tokens: named, listed, revocable, never minted by a token (T9, T18)."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import load_config
from app.main import create_app

ADMIN_PW = "correct horse battery"
USER_PW = "another long passphrase"
BASE = "https://siem.example.internal"


def setup(tmp_path: Path) -> tuple[TestClient, dict[str, str], str]:
    config = load_config(
        Path("missing.yaml"),
        {"APP__PATHS__DATA_DIR": str(tmp_path / "data"), "APP__SERVER__HOST": "0.0.0.0"},
    )
    app = create_app(config)
    admin = TestClient(app, base_url=BASE)
    token = app.state.auth.setup_url("siem.example.internal", 8080).split("#", 1)[1]
    csrf = admin.post(
        "/api/setup", json={"token": token, "username": "admin", "password": ADMIN_PW}
    ).json()["csrf_token"]
    h = {"X-CSRF-Token": csrf}
    res = admin.post("/api/users", json={"username": "jordan", "role": "analyst"}, headers=h)
    uid = res.json()["user"]["user_id"]
    admin.post(
        "/api/account/password", json={"token": res.json()["invite_token"], "password": USER_PW}
    )
    return admin, h, uid


def browser_login(app: object, username: str, password: str) -> tuple[TestClient, dict[str, str]]:
    c = TestClient(app, base_url=BASE)  # type: ignore[arg-type]
    res = c.post("/api/auth/login", json={"username": username, "password": password})
    return c, {"X-CSRF-Token": res.json()["csrf_token"]}


def cli_login(app: object, label: str | None = None) -> str:
    c = TestClient(app, base_url=BASE)  # type: ignore[arg-type]
    body: dict[str, str] = {"username": "jordan", "password": USER_PW, "client": "cli"}
    if label:
        body["label"] = label
    return str(c.post("/api/auth/login", json=body).json()["token"])


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_create_list_use_and_revoke_a_token(tmp_path: Path) -> None:
    admin, _, _ = setup(tmp_path)
    c, h = browser_login(admin.app, "jordan", USER_PW)
    res = c.post("/api/tokens", json={"label": "nightly export script", "days": 30}, headers=h)
    assert res.status_code == 201
    token, token_id = res.json()["token"], res.json()["token_id"]

    fresh = TestClient(admin.app, base_url=BASE)
    assert (
        fresh.post("/api/query", json={"sql": "SELECT 1"}, headers=bearer(token)).status_code == 200
    )

    listed = c.get("/api/tokens").json()
    mine = next(t for t in listed if t["token_id"] == token_id)
    assert mine["label"] == "nightly export script"
    assert mine["last_used_at"] is not None
    assert "token" not in mine  # the secret is shown once, at creation
    expires = datetime.fromisoformat(mine["expires_at"])
    assert timedelta(days=29) < expires - datetime.now(UTC) <= timedelta(days=30)

    assert c.delete(f"/api/tokens/{token_id}", headers=h).status_code == 204
    assert (
        fresh.post("/api/query", json={"sql": "SELECT 1"}, headers=bearer(token)).status_code == 401
    )


def test_token_cannot_create_more_tokens(tmp_path: Path) -> None:
    admin, _, _ = setup(tmp_path)
    token = cli_login(admin.app)
    fresh = TestClient(admin.app, base_url=BASE)
    res = fresh.post("/api/tokens", json={"label": "persistence"}, headers=bearer(token))
    assert res.status_code == 403
    assert res.json()["code"] == "interactive_required"


def test_cli_login_appears_as_a_named_token(tmp_path: Path) -> None:
    admin, _, _ = setup(tmp_path)
    cli_login(admin.app, label="remnant CLI on laptop-01")
    c, _ = browser_login(admin.app, "jordan", USER_PW)
    labels = [t["label"] for t in c.get("/api/tokens").json()]
    assert labels == ["remnant CLI on laptop-01"]


def test_browser_sessions_are_not_listed_as_tokens(tmp_path: Path) -> None:
    admin, _, _ = setup(tmp_path)
    c, _ = browser_login(admin.app, "jordan", USER_PW)
    assert c.get("/api/tokens").json() == []


def test_users_cannot_revoke_each_others_tokens(tmp_path: Path) -> None:
    admin, h, _ = setup(tmp_path)
    admin_token = admin.post("/api/tokens", json={"label": "admin script"}, headers=h).json()
    c, eh = browser_login(admin.app, "jordan", USER_PW)
    assert c.delete(f"/api/tokens/{admin_token['token_id']}", headers=eh).status_code == 404
    fresh = TestClient(admin.app, base_url=BASE)
    ok = fresh.post("/api/query", json={"sql": "SELECT 1"}, headers=bearer(admin_token["token"]))
    assert ok.status_code == 200


def test_admin_signs_a_user_out_everywhere(tmp_path: Path) -> None:
    admin, h, uid = setup(tmp_path)
    token = cli_login(admin.app)
    c, _ = browser_login(admin.app, "jordan", USER_PW)
    assert admin.post(f"/api/users/{uid}/signout", headers=h).status_code == 204
    fresh = TestClient(admin.app, base_url=BASE)
    assert (
        fresh.post("/api/query", json={"sql": "SELECT 1"}, headers=bearer(token)).status_code == 401
    )
    assert c.get("/api/tokens").status_code == 401
    assert login_still_works(admin.app)


def login_still_works(app: object) -> bool:
    c = TestClient(app, base_url=BASE)  # type: ignore[arg-type]
    return (
        c.post("/api/auth/login", json={"username": "jordan", "password": USER_PW}).status_code
        == 200
    )


def test_token_limits(tmp_path: Path) -> None:
    admin, h, _ = setup(tmp_path)
    assert admin.post("/api/tokens", json={"label": "x", "days": 400}, headers=h).status_code == 422
    assert admin.post("/api/tokens", json={"label": "", "days": 10}, headers=h).status_code == 422


def test_only_hashes_are_stored_and_actions_audited(tmp_path: Path) -> None:
    admin, h, _ = setup(tmp_path)
    res = admin.post("/api/tokens", json={"label": "script"}, headers=h).json()
    admin.delete(f"/api/tokens/{res['token_id']}", headers=h)
    db = sqlite3.connect(tmp_path / "data" / "meta.sqlite")
    stored = " ".join(str(r) for r in db.execute("SELECT * FROM sessions"))
    assert res["token"] not in stored
    actions = [r[0] for r in db.execute("SELECT action FROM audit_log")]
    assert "token.create" in actions and "token.revoke" in actions
    assert res["token"] not in " ".join(str(r) for r in db.execute("SELECT detail FROM audit_log"))
