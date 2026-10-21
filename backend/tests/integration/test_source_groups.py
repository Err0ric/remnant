"""Source groups: deny-by-default, per-user source scope on every surface (SPEC 3.6, T15, ADR-0004).

The lake holds three sources. "hr_payroll" is restricted. Every way a non-admin can read
events must show only the sources their groups grant.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import keyring
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from app.cli import main as cli
from app.cli.client import Credentials
from app.core.config import load_config
from app.ingest.normalizer import Normalizer, SourceSpec
from app.ingest.records import DecodedLine
from app.ingest.writer import LakeWriter
from app.main import create_app

ADMIN_PW = "correct horse battery"
USER_PW = "another long passphrase"
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
SOURCES = ("linux_auth", "fw_edge", "hr_payroll")


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, object]:
    logs = tmp_path / "logs"
    for s in SOURCES:
        (logs / s).mkdir(parents=True)
        (logs / s / "x.log").touch()
    rows = []
    for s in SOURCES:
        norm = Normalizer(SourceSpec(source_id=s, format="json"), clock=lambda: NOW)
        for i in range(3):
            line = json.dumps({"time": f"2026-10-10T10:0{i}:00Z", "who": s, "n": i})
            row = norm.normalize(DecodedLine(text=line, bytes_invalid=False, truncated=False))
            assert row is not None
            rows.append(row)
    LakeWriter(tmp_path / "data" / "lake").write(rows)

    config = load_config(
        Path("missing.yaml"),
        {
            "APP__PATHS__DATA_DIR": str(tmp_path / "data"),
            "APP__PATHS__ALLOWED_ROOTS": str(logs),
            "APP__SERVER__HOST": "0.0.0.0",
        },
    )
    app = create_app(config)
    admin = TestClient(app, base_url="https://siem.example.internal")
    token = app.state.auth.setup_url("siem.example.internal", 8080).split("#", 1)[1]
    csrf = admin.post(
        "/api/setup", json={"token": token, "username": "admin", "password": ADMIN_PW}
    ).json()["csrf_token"]
    h = {"X-CSRF-Token": csrf}
    for s in SOURCES:
        res = admin.post(
            "/api/sources",
            json={"source_id": s, "format": "json", "path": str(logs / s)},
            headers=h,
        )
        assert res.status_code == 201, res.text

    users = {}
    for name, role in (("ana", "analyst"), ("aud", "auditor"), ("nogroup", "analyst")):
        res = admin.post("/api/users", json={"username": name, "role": role}, headers=h)
        users[name] = res.json()["user"]["user_id"]
        admin.post(
            "/api/account/password", json={"token": res.json()["invite_token"], "password": USER_PW}
        )

    sec = admin.post(
        "/api/groups", json={"name": "Security", "description": "SOC sources"}, headers=h
    )
    assert sec.status_code == 201, sec.text
    gid = sec.json()["group_id"]
    assert (
        admin.put(
            f"/api/groups/{gid}/sources", json={"source_ids": ["linux_auth", "fw_edge"]}, headers=h
        ).status_code
        == 200
    )
    assert (
        admin.put(
            f"/api/groups/{gid}/members", json={"user_ids": [users["ana"], users["aud"]]}, headers=h
        ).status_code
        == 200
    )
    return {"app": app, "admin": admin, "h": h, "users": users, "gid": gid, "tmp": tmp_path}


def bearer(lab: dict[str, object], username: str) -> dict[str, str]:
    c = TestClient(lab["app"], base_url="https://siem.example.internal")  # type: ignore[arg-type]
    res = c.post(
        "/api/auth/login", json={"username": username, "password": USER_PW, "client": "cli"}
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def client(lab: dict[str, object]) -> TestClient:
    return TestClient(lab["app"], base_url="https://siem.example.internal")  # type: ignore[arg-type]


def seen_sources(lab: dict[str, object], auth: dict[str, str], **body: object) -> set[str]:
    res = client(lab).post(
        "/api/query",
        json={"sql": "SELECT DISTINCT source_id FROM events", **body},
        headers=auth,
    )
    assert res.status_code == 200, res.text
    return {r[0] for r in res.json()["rows"]}


# --- query surface ---------------------------------------------------------------------


def test_analyst_sees_only_granted_sources(lab: dict[str, object]) -> None:
    assert seen_sources(lab, bearer(lab, "ana")) == {"linux_auth", "fw_edge"}


def test_auditor_scoped_the_same_way(lab: dict[str, object]) -> None:
    assert seen_sources(lab, bearer(lab, "aud")) == {"linux_auth", "fw_edge"}


def test_admin_sees_everything(lab: dict[str, object]) -> None:
    admin = lab["admin"]
    res = admin.post(
        "/api/query", json={"sql": "SELECT DISTINCT source_id FROM events"}, headers=lab["h"]
    )  # type: ignore[union-attr]
    assert {r[0] for r in res.json()["rows"]} == set(SOURCES)


def test_user_without_groups_sees_nothing(lab: dict[str, object]) -> None:
    assert seen_sources(lab, bearer(lab, "nogroup")) == set()


def test_client_source_filter_cannot_widen_scope(lab: dict[str, object]) -> None:
    auth = bearer(lab, "ana")
    assert seen_sources(lab, auth, sources=["hr_payroll"]) == set()
    assert seen_sources(lab, auth, sources=["hr_payroll", "fw_edge"]) == {"fw_edge"}


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT count(*) FROM events WHERE source_id = 'hr_payroll'",
        "SELECT count(*) FROM events WHERE raw LIKE '%hr_payroll%'",
        "WITH e AS (SELECT * FROM events) SELECT count(*) FROM e WHERE source_id = 'hr_payroll'",
    ],
)
def test_restricted_rows_unreachable_by_sql(lab: dict[str, object], sql: str) -> None:
    res = client(lab).post("/api/query", json={"sql": sql}, headers=bearer(lab, "ana"))
    assert res.json()["rows"] == [[0]]


def test_restricted_event_not_found_by_id(lab: dict[str, object]) -> None:
    admin = lab["admin"]
    eid = admin.post(  # type: ignore[union-attr]
        "/api/query",
        json={"sql": "SELECT event_id FROM events WHERE source_id = 'hr_payroll' LIMIT 1"},
        headers=lab["h"],
    ).json()["rows"][0][0]
    res = client(lab).post(
        "/api/query",
        json={"sql": f"SELECT * FROM events WHERE event_id = '{eid}'"},
        headers=bearer(lab, "ana"),
    )
    assert res.json()["rows"] == []


def test_result_reports_only_permitted_sources_in_scope(lab: dict[str, object]) -> None:
    res = client(lab).post("/api/query", json={"sql": "SELECT 1"}, headers=bearer(lab, "ana"))
    assert set(res.json()["sources"]) <= {"linux_auth", "fw_edge"}


# --- grants change on the next request ---------------------------------------------------


def test_grant_and_revoke_take_effect_immediately(lab: dict[str, object]) -> None:
    admin, h, gid = lab["admin"], lab["h"], lab["gid"]
    auth = bearer(lab, "ana")
    admin.put(f"/api/groups/{gid}/sources", json={"source_ids": ["linux_auth"]}, headers=h)  # type: ignore[union-attr]
    assert seen_sources(lab, auth) == {"linux_auth"}
    admin.put(f"/api/groups/{gid}/members", json={"user_ids": []}, headers=h)  # type: ignore[union-attr]
    assert seen_sources(lab, auth) == set()


def test_deleting_a_group_removes_its_access(lab: dict[str, object]) -> None:
    admin, h, gid = lab["admin"], lab["h"], lab["gid"]
    auth = bearer(lab, "ana")
    assert admin.delete(f"/api/groups/{gid}", headers=h).status_code == 204  # type: ignore[union-attr]
    assert seen_sources(lab, auth) == set()


def test_access_comes_from_the_union_of_groups(lab: dict[str, object]) -> None:
    admin, h, users = lab["admin"], lab["h"], lab["users"]
    hr = admin.post("/api/groups", json={"name": "HR"}, headers=h).json()["group_id"]  # type: ignore[union-attr]
    admin.put(f"/api/groups/{hr}/sources", json={"source_ids": ["hr_payroll"]}, headers=h)  # type: ignore[union-attr]
    admin.put(f"/api/groups/{hr}/members", json={"user_ids": [users["ana"]]}, headers=h)  # type: ignore[union-attr, index]
    assert seen_sources(lab, bearer(lab, "ana")) == set(SOURCES)
    assert seen_sources(lab, bearer(lab, "aud")) == {"linux_auth", "fw_edge"}


# --- other surfaces ----------------------------------------------------------------------


def test_sources_list_hides_ungranted_sources_and_paths_from_non_admins(
    lab: dict[str, object],
) -> None:
    listed = client(lab).get("/api/sources", headers=bearer(lab, "ana")).json()
    assert {s["source_id"] for s in listed} == {"linux_auth", "fw_edge"}
    assert client(lab).get("/api/sources/settings", headers=bearer(lab, "ana")).status_code == 403


def test_cli_sees_the_same_scope(lab: dict[str, object], monkeypatch: pytest.MonkeyPatch) -> None:
    def factory(creds: Credentials) -> TestClient:
        c = client(lab)
        if creds.token:
            c.headers["Authorization"] = f"Bearer {creds.token}"
        return c

    token = bearer(lab, "ana")["Authorization"].split(" ", 1)[1]
    monkeypatch.setattr(cli, "client_factory", factory)
    monkeypatch.setenv("REMNANT_TOKEN", token)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(lab["tmp"] / "cfg"))  # type: ignore[operator]
    keyring.get_keyring()  # conftest already isolates the keychain
    res = CliRunner().invoke(
        cli.app,
        [
            "query",
            "SELECT DISTINCT source_id FROM events ORDER BY 1",
            "-o",
            "csv",
            "--server",
            "https://siem.example.internal",
        ],
    )
    assert res.exit_code == 0, res.stderr
    assert res.stdout.split() == ["source_id", "fw_edge", "linux_auth"]


# --- administration ----------------------------------------------------------------------


def test_only_admins_manage_groups(lab: dict[str, object]) -> None:
    auth = bearer(lab, "ana")
    c = client(lab)
    assert c.get("/api/groups", headers=auth).status_code == 403
    assert c.post("/api/groups", json={"name": "Mine"}, headers=auth).status_code == 403
    assert (
        c.put(
            f"/api/groups/{lab['gid']}/members",
            json={"user_ids": [lab["users"]["ana"]]},
            headers=auth,  # type: ignore[index]
        ).status_code
        == 403
    )


def test_group_validation(lab: dict[str, object]) -> None:
    admin, h, gid = lab["admin"], lab["h"], lab["gid"]
    assert admin.post("/api/groups", json={"name": "security"}, headers=h).status_code == 409  # type: ignore[union-attr]
    bad_source = admin.put(f"/api/groups/{gid}/sources", json={"source_ids": ["nope"]}, headers=h)  # type: ignore[union-attr]
    assert bad_source.status_code == 400
    bad_user = admin.put(
        f"/api/groups/{gid}/members",
        json={"user_ids": ["00000000-0000-4000-8000-000000000000"]},
        headers=h,
    )  # type: ignore[union-attr]
    assert bad_user.status_code == 400


def test_group_changes_are_audited_with_before_and_after(lab: dict[str, object]) -> None:
    import sqlite3

    db = sqlite3.connect(lab["tmp"] / "data" / "meta.sqlite")  # type: ignore[operator]
    rows = db.execute(
        "SELECT action, detail FROM audit_log WHERE action LIKE 'group.%' ORDER BY audit_id"
    ).fetchall()
    actions = [a for a, _ in rows]
    assert actions[:3] == ["group.create", "group.sources_set", "group.members_set"]
    detail = json.loads(rows[1][1])
    assert detail["before"] == [] and detail["after"] == ["fw_edge", "linux_auth"]


def test_group_listing_shows_sources_and_members(lab: dict[str, object]) -> None:
    groups = lab["admin"].get("/api/groups").json()  # type: ignore[union-attr]
    assert groups[0]["name"] == "Security"
    assert groups[0]["source_ids"] == ["fw_edge", "linux_auth"]
    assert len(groups[0]["user_ids"]) == 2
