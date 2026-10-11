"""Saved searches (SPEC 5.4): typed params bound (never pasted), caller's scope, sharing, YAML."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.ingest.normalizer import Normalizer, SourceSpec
from app.ingest.records import DecodedLine
from app.ingest.writer import LakeWriter
from app.main import create_app

ADMIN_PW = "correct horse battery"
USER_PW = "another long passphrase"
BASE = "https://siem.example.internal"
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)

FAILED = {
    "id": "failed_by_user",
    "name": "Failed logins by user",
    "description": "Top users with failures",
    "tags": ["auth", "ssh"],
    "visibility": "shared",
    "sql": (
        "SELECT json_extract_string(unmapped, '$.who') AS who, count(*) AS n FROM events\n"
        "WHERE json_extract_string(unmapped, '$.result') = {{result}}\n"
        "  AND time BETWEEN {{start}} AND {{end}}\n"
        "GROUP BY 1 ORDER BY 2 DESC LIMIT {{top}}"
    ),
    "params": [
        {"name": "result", "type": "string", "default": "failure"},
        {"name": "top", "type": "int", "default": 5},
    ],
}


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, object]:
    logs = tmp_path / "logs"
    for s in ("auth", "hr"):
        (logs / s).mkdir(parents=True)
    rows = []
    for source, who, result, n in (
        ("auth", "alice", "failure", 4),
        ("auth", "bob", "failure", 2),
        ("auth", "carol", "success", 3),
        ("hr", "payroll_admin", "failure", 9),
    ):
        norm = Normalizer(SourceSpec(source_id=source, format="json"), clock=lambda: NOW)
        for i in range(n):
            line = json.dumps({"time": f"2026-10-10T10:{i:02d}:00Z", "who": who, "result": result})
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
    admin = TestClient(app, base_url=BASE)
    token = app.state.auth.setup_url("siem.example.internal", 8080).split("#", 1)[1]
    h = {
        "X-CSRF-Token": admin.post(
            "/api/setup", json={"token": token, "username": "admin", "password": ADMIN_PW}
        ).json()["csrf_token"]
    }
    for s in ("auth", "hr"):
        admin.post(
            "/api/sources",
            json={"source_id": s, "format": "json", "path": str(logs / s)},
            headers=h,
        )
    ids = {}
    for name, role in (("ana", "analyst"), ("bo", "analyst"), ("aud", "auditor")):
        res = admin.post("/api/users", json={"username": name, "role": role}, headers=h).json()
        ids[name] = res["user"]["user_id"]
        admin.post(
            "/api/account/password", json={"token": res["invite_token"], "password": USER_PW}
        )
    gid = admin.post("/api/groups", json={"name": "SOC"}, headers=h).json()["group_id"]
    admin.put(f"/api/groups/{gid}/sources", json={"source_ids": ["auth"]}, headers=h)
    admin.put(f"/api/groups/{gid}/members", json={"user_ids": list(ids.values())}, headers=h)
    return {"app": app, "admin": admin, "h": h, "tmp": tmp_path}


def as_user(lab: dict[str, object], name: str) -> TestClient:
    c = TestClient(lab["app"], base_url=BASE)  # type: ignore[arg-type]
    token = c.post(
        "/api/auth/login", json={"username": name, "password": USER_PW, "client": "cli"}
    ).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    return c


RANGE = {"start": "2026-10-10T00:00:00Z", "end": "2026-10-11T00:00:00Z"}


def run(
    c: TestClient,
    sid: str,
    params: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
):  # type: ignore[no-untyped-def]  # httpx Response
    return c.post(
        f"/api/searches/{sid}/run", json={"params": params or {}, **RANGE}, headers=headers
    )


# --- create, run, params ---------------------------------------------------------------------


def test_create_and_run_with_defaults(lab: dict[str, object]) -> None:
    ana = as_user(lab, "ana")
    assert ana.post("/api/searches", json=FAILED).status_code == 201
    res = run(ana, "failed_by_user")
    assert res.status_code == 200, res.text
    assert res.json()["rows"] == [["alice", 4], ["bob", 2]]


def test_params_override_and_are_typed(lab: dict[str, object]) -> None:
    ana = as_user(lab, "ana")
    ana.post("/api/searches", json=FAILED)
    assert run(ana, "failed_by_user", {"top": 1}).json()["rows"] == [["alice", 4]]
    assert run(ana, "failed_by_user", {"top": "1"}).json()["rows"] == [
        ["alice", 4]
    ]  # CLI strings coerce
    bad = run(ana, "failed_by_user", {"top": "five"})
    assert bad.status_code == 400 and bad.json()["code"] == "param_invalid"
    assert run(ana, "failed_by_user", {"nope": 1}).status_code == 400


@pytest.mark.parametrize(
    "value",
    [
        "failure' OR 1=1 --",
        "x') UNION SELECT raw, 1 FROM events --",
        "failure'; DROP TABLE events; --",
    ],
)
def test_param_values_are_bound_never_pasted(lab: dict[str, object], value: str) -> None:
    ana = as_user(lab, "ana")
    ana.post("/api/searches", json=FAILED)
    res = run(ana, "failed_by_user", {"result": value})
    assert res.status_code == 200
    assert res.json()["rows"] == []


def test_runs_in_the_callers_scope_not_the_authors(lab: dict[str, object]) -> None:
    admin, h = lab["admin"], lab["h"]
    shared = dict(FAILED, id="admin_failed")
    assert admin.post("/api/searches", json=shared, headers=h).status_code == 201  # type: ignore[union-attr]
    admin_rows = run(admin, "admin_failed", headers=h).json()["rows"]  # type: ignore[arg-type]
    assert ["payroll_admin", 9] in admin_rows
    ana_rows = run(as_user(lab, "ana"), "admin_failed").json()["rows"]
    assert ["payroll_admin", 9] not in ana_rows and ana_rows[0] == ["alice", 4]


def test_source_restriction_narrows_but_never_widens(lab: dict[str, object]) -> None:
    ana = as_user(lab, "ana")
    ana.post("/api/searches", json=dict(FAILED, id="hr_only", sources=["hr"]))
    assert run(ana, "hr_only").json()["rows"] == []


def test_undefined_placeholder_and_non_select_rejected_at_save(lab: dict[str, object]) -> None:
    ana = as_user(lab, "ana")
    bad = ana.post(
        "/api/searches", json=dict(FAILED, id="bad1", sql="SELECT {{missing}} FROM events")
    )
    assert bad.status_code == 400 and "missing" in bad.json()["detail"]
    drop = ana.post(
        "/api/searches", json=dict(FAILED, id="bad2", sql="DROP TABLE events", params=[])
    )
    assert drop.status_code == 400 and drop.json()["code"] == "query_rejected"
    reserved = ana.post(
        "/api/searches",
        json=dict(
            FAILED, id="bad3", params=[*FAILED["params"], {"name": "start", "type": "string"}]
        ),  # type: ignore[list-item]
    )
    assert reserved.status_code == 422


# --- visibility and ownership --------------------------------------------------------------------


def test_private_searches_are_invisible_to_others(lab: dict[str, object]) -> None:
    ana, bo = as_user(lab, "ana"), as_user(lab, "bo")
    ana.post("/api/searches", json=dict(FAILED, id="mine", visibility="private"))
    assert [s["id"] for s in bo.get("/api/searches").json()] == []
    assert bo.get("/api/searches/mine").status_code == 404
    assert run(bo, "mine").status_code == 404  # type: ignore[union-attr]


def test_only_the_owner_edits_admins_may_delete(lab: dict[str, object]) -> None:
    ana, bo = as_user(lab, "ana"), as_user(lab, "bo")
    ana.post("/api/searches", json=FAILED)
    assert (
        bo.put("/api/searches/failed_by_user", json=dict(FAILED, name="hijack")).status_code == 403
    )
    assert bo.delete("/api/searches/failed_by_user").status_code == 403
    assert (
        ana.put("/api/searches/failed_by_user", json=dict(FAILED, name="Renamed")).status_code
        == 200
    )
    admin = lab["admin"]
    assert admin.delete("/api/searches/failed_by_user", headers=lab["h"]).status_code == 204  # type: ignore[union-attr]


def test_auditor_runs_shared_searches_but_cannot_create(lab: dict[str, object]) -> None:
    as_user(lab, "ana").post("/api/searches", json=FAILED)
    aud = as_user(lab, "aud")
    assert run(aud, "failed_by_user").status_code == 200  # type: ignore[union-attr]
    assert aud.post("/api/searches", json=dict(FAILED, id="aud1")).status_code == 403


def test_duplicate_id_conflicts(lab: dict[str, object]) -> None:
    ana, bo = as_user(lab, "ana"), as_user(lab, "bo")
    ana.post("/api/searches", json=dict(FAILED, visibility="private"))
    assert bo.post("/api/searches", json=FAILED).status_code == 409


def test_list_filters_by_tag(lab: dict[str, object]) -> None:
    ana = as_user(lab, "ana")
    ana.post("/api/searches", json=FAILED)
    ana.post("/api/searches", json=dict(FAILED, id="other", tags=["dns"]))
    assert [s["id"] for s in ana.get("/api/searches", params={"tag": "dns"}).json()] == ["other"]


# --- YAML -------------------------------------------------------------------------------------------


def test_yaml_export_import_round_trip(lab: dict[str, object]) -> None:
    ana, bo = as_user(lab, "ana"), as_user(lab, "bo")
    ana.post("/api/searches", json=FAILED)
    exported = ana.get("/api/searches/failed_by_user/export")
    assert exported.headers["content-type"].startswith("application/yaml")
    doc = yaml.safe_load(exported.text)
    assert doc["schema_version"] == 1 and doc["sql"] == FAILED["sql"]
    assert doc["params"] == FAILED["params"]

    doc["id"] = "imported_copy"
    res = bo.post(
        "/api/searches/import",
        content=yaml.safe_dump(doc),
        headers={"Content-Type": "application/yaml"},
    )
    assert res.status_code == 201, res.text
    copy = bo.get("/api/searches/imported_copy").json()
    assert copy["owner_id"] != doc["owner_id"]  # the importer owns it
    assert copy["visibility"] == "private"  # imports start private
    assert run(bo, "imported_copy").json()["rows"] == [["alice", 4], ["bob", 2]]


@pytest.mark.parametrize(
    "body",
    [
        "!!python/object/apply:os.system ['echo pwned']",
        "schema_version: 1\nid: x\nname: x\nsql: DROP TABLE events\n",
        "not: [valid",
        "a: " + "x" * 300_000,
    ],
)
def test_import_rejects_unsafe_or_invalid_yaml(lab: dict[str, object], body: str) -> None:
    res = as_user(lab, "ana").post(
        "/api/searches/import", content=body, headers={"Content-Type": "application/yaml"}
    )
    assert res.status_code in (400, 413, 422)


def test_runs_and_changes_are_audited(lab: dict[str, object]) -> None:
    import sqlite3

    ana = as_user(lab, "ana")
    ana.post("/api/searches", json=FAILED)
    run(ana, "failed_by_user", {"top": 1})
    db = sqlite3.connect(lab["tmp"] / "data" / "meta.sqlite")  # type: ignore[operator]
    rows = {
        a: json.loads(d)
        for a, d in db.execute("SELECT action, detail FROM audit_log WHERE action LIKE 'search.%'")
    }
    assert rows["search.run"]["search_id"] == "failed_by_user"
    assert rows["search.run"]["params"] == {"result": "failure", "top": 1}
    assert rows["search.run"]["sources_in_scope"] == ["auth"]
    assert "search.create" in rows


def test_ask_origin_is_kept_and_bounded(lab: dict[str, object]) -> None:
    ana = as_user(lab, "ana")
    spec = dict(FAILED, id="from_ask", mode="ask", origin={"ask_prompt": "failed logins by user"})
    assert ana.post("/api/searches", json=spec).status_code == 201
    got = ana.get("/api/searches/from_ask").json()
    assert got["mode"] == "ask" and got["origin"] == {"ask_prompt": "failed logins by user"}
    for origin in ({"other": "x"}, {"ask_prompt": "x" * 2001}):
        bad = dict(spec, id="bad_origin", origin=origin)
        assert ana.post("/api/searches", json=bad).status_code == 422


def test_simple_search_text_is_kept_as_the_origin(lab: dict[str, object]) -> None:
    ana = as_user(lab, "ana")
    spec = dict(FAILED, id="from_simple", origin={"simple_text": 'sshd "failed password"'})
    assert ana.post("/api/searches", json=spec).status_code == 201
    got = ana.get("/api/searches/from_simple").json()
    assert got["mode"] == "query" and got["origin"] == {"simple_text": 'sshd "failed password"'}
