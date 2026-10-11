"""A Loki source end to end (ADR-0011): add, poll, parse, store, restart, scope, secrets."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.ingest.connectors.loki import LokiClient, to_ns
from app.ingest.watcher import IngestService
from app.main import create_app
from tests.fake_loki import FakeLoki

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
BASE = "https://siem.example.internal"
SECRET = "loki-bearer-s3cret"
LOKI = {
    "url": "http://127.0.0.1:3100",
    "query": '{job="syslog", host=~"bastion|web-01"}',
    "auth": "bearer",
    "backfill_hours": 24,
}


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    config = load_config(
        Path("missing.yaml"),
        {
            "APP__PATHS__DATA_DIR": str(tmp_path / "data"),
            "APP__PATHS__ALLOWED_ROOTS": str(tmp_path),
            "APP__SERVER__HOST": "0.0.0.0",
        },
    )
    app = create_app(config)
    fake = FakeLoki()
    clock = Clock()
    app.state.ingest._clock = clock
    app.state.ingest.loki_client = lambda s, secret: LokiClient(s, secret, fake.transport())
    admin = TestClient(app, base_url=BASE)
    token = app.state.auth.setup_url("siem.example.internal", 8080).split("#", 1)[1]
    csrf = admin.post(
        "/api/setup",
        json={"token": token, "username": "admin", "password": "correct horse battery"},
    ).json()["csrf_token"]
    h = {"X-CSRF-Token": csrf}
    ts = (NOW - timedelta(hours=1)).strftime("%b %e %H:%M:%S")
    fake.add(
        to_ns(NOW - timedelta(hours=1)),
        f"<38>{ts} bastion sshd[7]: Failed password for root from 203.0.113.9 port 4 ssh2",
        job="syslog",
        host="bastion",
    )
    fake.add(
        to_ns(NOW - timedelta(minutes=20)), "plain line with no header", job="syslog", host="web-01"
    )
    body = {
        "source_id": "loki_auth",
        "format": "syslog",
        "kind": "loki",
        "loki": LOKI,
        "loki_secret": SECRET,
    }
    res = admin.post("/api/sources", json=body, headers=h)
    assert res.status_code == 201, res.text
    return {
        "app": app,
        "admin": admin,
        "h": h,
        "fake": fake,
        "clock": clock,
        "db": tmp_path / "data" / "meta.sqlite",
        "config": config,
    }


def rows(lab: dict[str, Any], sql: str) -> list[list[Any]]:
    res = lab["admin"].post("/api/query", json={"sql": sql}, headers=lab["h"])
    assert res.status_code == 200, res.text
    return list(res.json()["rows"])


def test_lines_land_with_raw_unchanged_labels_kept_and_times_filled(lab: dict[str, Any]) -> None:
    assert lab["app"].state.ingest.run_once() == 2
    got = rows(
        lab, "SELECT raw, envelope, time, classification, parse_status FROM events ORDER BY time"
    )
    assert got[0][0].startswith("<38>") and "Failed password for root" in got[0][0]
    assert json.loads(got[0][1])["loki_labels"] == {"job": "syslog", "host": "bastion"}
    assert got[1][0] == "plain line with no header"
    assert got[1][2].startswith("2026-10-12T11:40")  # Loki's time: the line has none
    assert {r[3] for r in got} == {"local_only"}
    call = lab["fake"].calls[-1]
    assert call.headers["authorization"] == f"Bearer {SECRET}"


def test_polls_every_30_seconds_and_never_reads_a_line_twice(lab: dict[str, Any]) -> None:
    ingest = lab["app"].state.ingest
    ingest.run_once()
    calls = len(lab["fake"].calls)
    ingest.run_once()  # too soon: no request
    assert len(lab["fake"].calls) == calls
    lab["clock"].now = NOW + timedelta(minutes=1)
    lab["fake"].add(to_ns(NOW + timedelta(seconds=5)), "new line", job="syslog", host="bastion")
    assert ingest.run_once() == 1
    assert rows(lab, "SELECT count(*) FROM events")[0][0] == 3
    status = lab["admin"].get("/api/sources").json()[0]["status"]
    assert status["state"] == "reading" and status["behind_s"] <= 30


def test_position_survives_a_restart(lab: dict[str, Any]) -> None:
    lab["app"].state.ingest.run_once()
    old = lab["app"].state.ingest
    fresh = IngestService(
        old._sources,
        old._meta,
        lab["config"].paths.data_dir / "lake",
        clock=lab["clock"],
        templates=old._templates,
    )
    fresh.loki_client = old.loki_client
    lab["clock"].now = NOW + timedelta(minutes=5)
    assert fresh.run_once() == 0
    assert rows(lab, "SELECT count(*) FROM events")[0][0] == 2


def test_secret_never_returned_or_logged_and_settings_hidden_from_analysts(
    lab: dict[str, Any],
) -> None:
    listed = lab["admin"].get("/api/sources").text
    assert SECRET not in listed and '"query"' in listed
    with sqlite3.connect(lab["db"]) as db:
        detail = db.execute(
            "SELECT detail FROM audit_log WHERE action = 'source.create'"
        ).fetchone()[0]
        stored = db.execute("SELECT connector_secret_enc FROM sources").fetchone()[0]
    assert SECRET not in detail and '"has_loki_secret":true' in detail
    assert SECRET not in stored
    a = (
        lab["admin"]
        .post("/api/users", json={"username": "ana", "role": "analyst"}, headers=lab["h"])
        .json()
    )
    lab["admin"].post(
        "/api/account/password",
        json={"token": a["invite_token"], "password": "another long passphrase"},
    )
    gid = (
        lab["admin"].post("/api/groups", json={"name": "All"}, headers=lab["h"]).json()["group_id"]
    )
    lab["admin"].put(
        f"/api/groups/{gid}/sources", json={"source_ids": ["loki_auth"]}, headers=lab["h"]
    )
    lab["admin"].put(
        f"/api/groups/{gid}/members", json={"user_ids": [a["user"]["user_id"]]}, headers=lab["h"]
    )
    tok = (
        TestClient(lab["app"], base_url=BASE)
        .post(
            "/api/auth/login",
            json={"username": "ana", "password": "another long passphrase", "client": "cli"},
        )
        .json()["token"]
    )
    ana = TestClient(lab["app"], base_url=BASE, headers={"Authorization": f"Bearer {tok}"})
    (mine,) = ana.get("/api/sources").json()
    assert mine["loki"] is None and "127.0.0.1" not in json.dumps(mine)


def test_connection_test_and_errors_show_on_the_source(lab: dict[str, Any]) -> None:
    recent = datetime.now(UTC) - timedelta(minutes=10)  # the test reads the last hour, now
    lab["fake"].add(to_ns(recent), "recent", job="syslog", host="bastion")
    res = lab["admin"].post(
        "/api/sources/loki/test", json={**LOKI, "secret": SECRET}, headers=lab["h"]
    )
    assert res.status_code == 200, res.text
    assert res.json()["streams"] and res.json()["lines"] >= 1
    bad = lab["admin"].post(
        "/api/sources/loki/test", json={**LOKI, "query": "job=syslog"}, headers=lab["h"]
    )
    assert bad.status_code == 400 and "label selector" in bad.json()["detail"]
    lab["fake"].status = 401
    lab["app"].state.ingest.run_once()
    status = lab["admin"].get("/api/sources").json()[0]["status"]
    assert status["state"] == "error" and "refused the credentials" in status["error"]


def test_bad_loki_sources_are_refused(lab: dict[str, Any]) -> None:
    a, h = lab["admin"], lab["h"]
    base = {"source_id": "x_loki", "format": "syslog", "kind": "loki"}
    assert a.post("/api/sources", json=base, headers=h).status_code == 422  # no settings
    assert (
        a.post("/api/sources", json={**base, "loki": LOKI, "path": "/tmp"}, headers=h).status_code
        == 422
    )
    meta = {**base, "loki": {**LOKI, "url": "http://169.254.169.254"}}
    lab["clock"].now = NOW
    assert a.post("/api/sources", json=meta, headers=h).status_code == 201  # checked when used
    lab["app"].state.ingest.run_once()
    st = {s["source_id"]: s["status"] for s in a.get("/api/sources").json()}["x_loki"]
    assert "not allowed" in st["error"]


def test_removing_a_source_forgets_its_position(lab: dict[str, Any]) -> None:
    lab["app"].state.ingest.run_once()
    assert lab["admin"].delete("/api/sources/loki_auth", headers=lab["h"]).status_code == 204
    with sqlite3.connect(lab["db"]) as db:
        assert db.execute("SELECT count(*) FROM connector_checkpoints").fetchone()[0] == 0


def test_automatic_parser_on_a_loki_stream(lab: dict[str, Any]) -> None:
    """ADR-0012: a mixed Loki selector routes each line to its own template."""
    res = lab["admin"].patch(
        "/api/sources/loki_auth", json={"template_id": "auto"}, headers=lab["h"]
    )
    assert res.status_code == 200, res.text
    assert lab["app"].state.ingest.run_once() == 2
    got = rows(
        lab,
        "SELECT template_id, src_endpoint_ip, envelope, time FROM events ORDER BY time",
    )
    assert got[0][:2] == ["linux_sshd", "203.0.113.9"]
    assert json.loads(got[0][2])["loki_labels"]["host"] == "bastion"
    assert got[1][0] == "generic_syslog" and got[1][3].startswith("2026-10-12T11:40")
