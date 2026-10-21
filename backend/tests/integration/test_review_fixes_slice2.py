"""Fixes from the Slice 2 access-control review (2026-10-10)."""

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import load_config
from app.main import create_app

ADMIN_PW = "correct horse battery"
USER_PW = "another long passphrase"
BASE = "https://siem.example.internal"


def setup(tmp_path: Path) -> tuple[TestClient, dict[str, str], str, Path]:
    logs = tmp_path / "logs"
    (logs / "secret").mkdir(parents=True)
    (logs / "secret" / "x.log").write_text("<38>Oct  9 20:41:01 h sshd[1]: secret line\n")
    config = load_config(
        Path("missing.yaml"),
        {
            "APP__PATHS__DATA_DIR": str(tmp_path / "data"),
            "APP__PATHS__ALLOWED_ROOTS": str(logs),
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
    uid = res.json()["user"]["user_id"]
    admin.post(
        "/api/account/password", json={"token": res.json()["invite_token"], "password": USER_PW}
    )
    return admin, h, uid, logs


def cli_token(app: object) -> str:
    c = TestClient(app, base_url=BASE)  # type: ignore[arg-type]
    res = c.post("/api/auth/login", json={"username": "ana", "password": USER_PW, "client": "cli"})
    return str(res.json()["token"])


def audit(tmp_path: Path) -> list[tuple[str, str, dict[str, object]]]:
    db = sqlite3.connect(tmp_path / "data" / "meta.sqlite")
    return [
        (a, o, json.loads(d))
        for a, o, d in db.execute("SELECT action, outcome, detail FROM audit_log ORDER BY audit_id")
    ]


# --- 1: a CLI token presented as a cookie is not a browser session ------------------------


def test_cli_token_in_cookie_cannot_mint_tokens(tmp_path: Path) -> None:
    admin, _, _, _ = setup(tmp_path)
    token = cli_token(admin.app)
    c = TestClient(admin.app, base_url=BASE)
    c.cookies.set("session", token)
    state = c.get("/api/auth/state").json()
    assert state["user"] is None and state["csrf_token"] is None
    res = c.post(
        "/api/tokens", json={"label": "persist", "days": 365}, headers={"X-CSRF-Token": "x"}
    )
    assert res.status_code == 401


def test_browser_session_secret_is_not_a_bearer_token(tmp_path: Path) -> None:
    admin, _, _, _ = setup(tmp_path)
    secret = admin.cookies.get("session")
    fresh = TestClient(admin.app, base_url=BASE)
    res = fresh.post(
        "/api/query", json={"sql": "SELECT 1"}, headers={"Authorization": f"Bearer {secret}"}
    )
    assert res.status_code == 401


# --- 2: deleting a source removes its grants ------------------------------------------------


def test_deleted_source_grants_do_not_carry_over_to_a_new_source(tmp_path: Path) -> None:
    admin, h, uid, logs = setup(tmp_path)
    admin.post(
        "/api/sources",
        json={"source_id": "secret", "format": "syslog", "path": str(logs / "secret")},
        headers=h,
    )
    gid = admin.post("/api/groups", json={"name": "G"}, headers=h).json()["group_id"]
    admin.put(f"/api/groups/{gid}/sources", json={"source_ids": ["secret"]}, headers=h)
    admin.put(f"/api/groups/{gid}/members", json={"user_ids": [uid]}, headers=h)
    assert admin.delete("/api/sources/secret", headers=h).status_code == 204
    assert admin.get("/api/groups").json()[0]["source_ids"] == []
    admin.post(
        "/api/sources",
        json={"source_id": "secret", "format": "syslog", "path": str(logs / "secret")},
        headers=h,
    )
    assert admin.get("/api/groups").json()[0]["source_ids"] == []


# --- 3 and 4: denied actions and effective scope are audited ---------------------------------


def test_refused_privileged_actions_are_audited(tmp_path: Path) -> None:
    admin, h, uid, _ = setup(tmp_path)
    fresh = TestClient(admin.app, base_url=BASE)
    bearer = {"Authorization": f"Bearer {cli_token(admin.app)}"}
    assert (
        fresh.patch(f"/api/users/{uid}", json={"role": "admin"}, headers=bearer).status_code == 403
    )
    me = next(u for u in admin.get("/api/users").json() if u["username"] == "admin")
    assert (
        admin.patch(f"/api/users/{me['user_id']}", json={"disabled": True}, headers=h).status_code
        == 409
    )
    assert (
        admin.post("/api/groups", json={"name": "x"}, headers={"X-CSRF-Token": "wrong"}).status_code
        == 403
    )
    rows = audit(tmp_path)
    denied = [(a, o, d) for a, o, d in rows if o == "denied"]
    assert any(a == "access.denied" and d.get("path") == f"/api/users/{uid}" for a, _, d in denied)
    assert any(
        a == "user.update" and d.get("reason") == "last_admin" for a, o, d in rows if o == "failure"
    )
    assert any(a == "auth.csrf_failed" for a, _, _ in denied)


def test_query_audit_records_effective_scope(tmp_path: Path) -> None:
    admin, _, _, _ = setup(tmp_path)
    fresh = TestClient(admin.app, base_url=BASE)
    bearer = {"Authorization": f"Bearer {cli_token(admin.app)}"}
    fresh.post("/api/query", json={"sql": "SELECT 1", "sources": ["anything"]}, headers=bearer)
    detail = [d for a, _, d in audit(tmp_path) if a == "query.run"][-1]
    assert detail["sources_in_scope"] == []
    assert detail["sources_requested"] == ["anything"]


def test_group_description_change_audited(tmp_path: Path) -> None:
    admin, h, _, _ = setup(tmp_path)
    gid = admin.post("/api/groups", json={"name": "G", "description": "old"}, headers=h).json()[
        "group_id"
    ]
    admin.patch(f"/api/groups/{gid}", json={"description": "new"}, headers=h)
    detail = [d for a, _, d in audit(tmp_path) if a == "group.update"][-1]
    assert detail["description_before"] == "old" and detail["description_after"] == "new"


# --- 5: names are validated after trimming ----------------------------------------------------


def test_blank_group_names_rejected(tmp_path: Path) -> None:
    admin, h, _, _ = setup(tmp_path)
    assert admin.post("/api/groups", json={"name": "   "}, headers=h).status_code == 422
    gid = admin.post("/api/groups", json={"name": "  Ops  "}, headers=h).json()["group_id"]
    assert admin.get("/api/groups").json()[0]["name"] == "Ops"
    assert admin.patch(f"/api/groups/{gid}", json={"name": "  "}, headers=h).status_code == 422


# --- 6: non-admins do not see server paths ------------------------------------------------------


def test_analysts_do_not_see_source_paths_or_raw_errors(tmp_path: Path) -> None:
    admin, h, uid, logs = setup(tmp_path)
    admin.post(
        "/api/sources",
        json={"source_id": "secret", "format": "syslog", "path": str(logs / "secret")},
        headers=h,
    )
    gid = admin.post("/api/groups", json={"name": "G"}, headers=h).json()["group_id"]
    admin.put(f"/api/groups/{gid}/sources", json={"source_ids": ["secret"]}, headers=h)
    admin.put(f"/api/groups/{gid}/members", json={"user_ids": [uid]}, headers=h)
    (logs / "secret" / "x.log").unlink()
    (logs / "secret").rmdir()
    admin.app.state.ingest.run_once()  # type: ignore[attr-defined]
    fresh = TestClient(admin.app, base_url=BASE)
    listed = fresh.get(
        "/api/sources", headers={"Authorization": f"Bearer {cli_token(admin.app)}"}
    ).json()
    assert listed[0]["path"] == ""
    assert str(logs) not in json.dumps(listed)
    assert listed[0]["status"]["state"] == "error"
    assert admin.get("/api/sources").json()[0]["path"] == str(logs / "secret")


# --- 7: the acting admin is re-checked inside the transaction -------------------------------------


def test_admin_demoted_mid_flight_cannot_finish_a_change(tmp_path: Path) -> None:
    admin, _, uid, _ = setup(tmp_path)
    auth = admin.app.state.auth  # type: ignore[attr-defined]
    stale_actor = next(
        u for u in [auth.users.get(r.user_id) for r in auth.admin.all()] if u and u.role == "admin"
    )
    second = auth.admin.invite("second", "admin", stale_actor, None)
    auth.admin.redeem(second[1], USER_PW, None)
    # Demote the first admin directly, then replay a change with its stale identity.
    auth.admin.update(stale_actor.user_id, second[0], None, role="analyst")
    import pytest

    from app.core.errors import ForbiddenError

    with pytest.raises(ForbiddenError):
        auth.admin.update(uid, stale_actor, None, role="admin")
