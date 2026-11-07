"""Proxmox guest inventory end to end (ADR-0045 Part A, D210), against a fake Proxmox API
shaped like versions 8 and 9: the PVEAuditor check at save, the minimal record as `raw`,
events only on a change plus a daily heartbeat, agent and container addresses, and a fake
secret in descriptions and cloud-init fields that must appear nowhere."""

import ipaddress
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import httpx
import pytest
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

import app.alerts.net as net
from app.core.config import load_config
from app.main import create_app
from tests.fake_proxmox import SECRET, TOKEN_ID, TOKEN_SECRET, FakeProxmox

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
BASE = "https://siem.example.internal"
ALLOWED_KEYS = {"feed", "event", "time", "vmid", "type", "name", "node", "status", "tags",
                "macs", "ips", "changed"}  # fmt: skip


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def make_lab(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: int) -> dict[str, Any]:
    monkeypatch.setattr(net, "_resolve", lambda host, port: [ipaddress.ip_address("10.0.0.10")])
    config = load_config(
        Path("missing.yaml"),
        {
            "APP__PATHS__DATA_DIR": str(tmp_path / "data"),
            "APP__PATHS__ALLOWED_ROOTS": str(tmp_path),
            "APP__SERVER__HOST": "0.0.0.0",
        },
    )
    app = create_app(config)
    fake = FakeProxmox(version)
    clock = Clock()
    app.state.ingest._clock = clock
    app.state.auth.clock = clock
    app.state.ingest.api_transport = fake.transport()
    admin = TestClient(app, base_url=BASE)
    token = app.state.auth.setup_url("siem.example.internal", 8080).split("#", 1)[1]
    csrf = admin.post(
        "/api/setup",
        json={"token": token, "username": "admin", "password": "correct horse battery"},
    ).json()["csrf_token"]
    return {
        "app": app,
        "admin": admin,
        "h": {"X-CSRF-Token": csrf},
        "fake": fake,
        "clock": clock,
        "data": tmp_path / "data",
    }


@pytest.fixture
def lab(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    return make_lab(tmp_path, monkeypatch, 9)


def body(**over: Any) -> dict[str, Any]:
    return {
        "source_id": "pve",
        "format": "json",
        "kind": "proxmox",
        "template_id": "proxmox_inventory",
        "proxmox": {"host": "pve1.example.internal", "token_id": TOKEN_ID} | over,
        "credentials": {"token_secret": TOKEN_SECRET},
    }


def add(lab: dict[str, Any], b: dict[str, Any] | None = None) -> httpx.Response:
    res: httpx.Response = lab["admin"].post("/api/sources", json=b or body(), headers=lab["h"])
    return res


def rows(lab: dict[str, Any], sql: str) -> list[list[Any]]:
    res = lab["admin"].post("/api/query", json={"sql": sql}, headers=lab["h"])
    assert res.status_code == 200, res.text
    return list(res.json()["rows"])


def poll(lab: dict[str, Any], minutes: int = 15) -> int:
    lab["clock"].now += timedelta(minutes=minutes)
    written: int = lab["app"].state.ingest.run_once()
    return written


def lake(lab: dict[str, Any], columns: str = "*") -> list[tuple[Any, ...]]:
    """Every stored row, read from the Parquet files (the session may have expired)."""
    glob = str(lab["data"] / "lake" / "**" / "*.parquet")
    sql = f"SELECT {columns} FROM read_parquet(?, union_by_name = true)"
    return duckdb.connect().execute(sql, [glob]).fetchall()


def events(lab: dict[str, Any]) -> list[dict[str, Any]]:
    return [json.loads(r[1]) for r in sorted(lake(lab, "time, raw"))]


def test_a_token_that_can_change_things_is_refused_at_save(lab: dict[str, Any]) -> None:
    lab["fake"].grant("Sys.Modify", "VM.Allocate")
    res = add(lab)
    assert res.status_code == 400
    assert "PVEAuditor" in res.json()["detail"] and "VM.Allocate" in res.json()["detail"]
    assert lab["admin"].get("/api/sources").json() == []


def test_first_poll_writes_one_appeared_event_per_guest_from_the_allowed_fields(
    lab: dict[str, Any],
) -> None:
    assert add(lab).status_code == 201
    assert lab["app"].state.ingest.run_once() == 3  # the template is left out
    got = {e["vmid"]: e for e in events(lab)}
    assert set(got) == {104, 105, 201}
    for e in got.values():
        assert set(e) <= ALLOWED_KEYS and e["event"] == "appeared"
    vm = got[104]
    assert vm["name"] == "build-runner" and vm["node"] == "pve2" and vm["tags"] == ["ci", "linux"]
    assert vm["macs"] == ["52:54:00:12:34:56"]
    assert vm["ips"] == [
        {"ip": "10.20.30.40", "from": "config"},
        {"ip": "10.20.30.41", "from": "agent"},
    ]
    assert got[105]["ips"] == [] and got[105]["macs"] == ["52:54:00:ab:cd:05"]
    assert got[201]["ips"] == [
        {"ip": "192.168.10.5", "from": "config"},
        {"ip": "2001:db8::5", "from": "container"},
    ]
    # Agent-less VM: the agent is never asked.
    assert not any("/105/agent" in c for c in lab["fake"].calls)
    (row,) = rows(
        lab,
        "SELECT device_hostname, device_ip, message, template_id, classification FROM events"
        " WHERE device_hostname = 'build-runner'",
    )
    assert row == ["build-runner", "10.20.30.40", "appeared", "proxmox_inventory", "local_only"]


def test_unchanged_poll_writes_nothing_and_changes_and_removals_write_one_event(
    lab: dict[str, Any],
) -> None:
    assert add(lab).status_code == 201
    assert lab["app"].state.ingest.run_once() == 3
    assert poll(lab) == 0
    # DHCP churn on the container, and the VM moves node.
    guests = lab["fake"].guests
    guests[201]["report"][1]["inet"] = "192.168.10.77/24"
    guests[104]["res"]["node"] = "pve1"
    assert poll(lab) == 2
    changed = {e["vmid"]: e for e in events(lab) if e["event"] == "changed"}
    assert changed[201]["changed"] == ["ip"] and changed[104]["changed"] == ["node"]
    # A description edit is not a change: it is never read.
    guests[105]["config"]["description"] = "something else"
    assert poll(lab) == 0
    del guests[105]
    assert poll(lab) == 1
    (gone,) = [e for e in events(lab) if e["event"] == "disappeared"]
    assert gone["vmid"] == 105 and gone["name"] == "scanner"
    assert poll(lab) == 0


def test_one_heartbeat_per_guest_a_day(lab: dict[str, Any]) -> None:
    assert add(lab).status_code == 201
    lab["app"].state.ingest.run_once()
    assert poll(lab, 60 * 23) == 0
    assert poll(lab, 60) == 3
    assert {e["event"] for e in events(lab)} == {"appeared", "heartbeat"}
    assert poll(lab) == 0


def test_proxmox_8_records_config_addresses_and_says_agent_ips_are_not_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab = make_lab(tmp_path, monkeypatch, 8)
    assert add(lab).status_code == 201
    assert lab["app"].state.ingest.run_once() == 3
    vm = next(e for e in events(lab) if e["vmid"] == 104)
    assert vm["ips"] == [{"ip": "10.20.30.40", "from": "config"}]
    status = lab["admin"].get("/api/sources").json()[0]["status"]
    assert status["state"] == "reading"
    assert status["warnings"] == ["Agent IPs not available with this token"]


def test_the_fake_secret_appears_nowhere(lab: dict[str, Any]) -> None:
    with capture_logs() as logs:
        test = lab["admin"].post(
            "/api/sources/api/test",
            json={
                "kind": "proxmox",
                "proxmox": body()["proxmox"],
                "credentials": {"token_secret": TOKEN_SECRET},
            },
            headers=lab["h"],
        )
        assert test.status_code == 200
        assert test.json()["feeds"] == {
            "permissions": "ok: read only (PVEAuditor)",
            "version": "ok: Proxmox VE 9.0.3",
            "guests": "ok: 3 guests",
        }
        assert add(lab).status_code == 201
        lab["app"].state.ingest.run_once()
        lab["fake"].guests[201]["report"][1]["inet"] = "192.168.10.9/24"
        poll(lab)
        sources = lab["admin"].get("/api/sources").text
    assert SECRET not in sources and TOKEN_SECRET not in sources
    assert "pve1.example.internal" in sources  # admins see the host, never the secret
    assert SECRET not in json.dumps(logs, default=str)
    assert TOKEN_SECRET not in json.dumps(logs, default=str)
    # The whole lake, every column, and every table of the meta database.
    dumped = json.dumps(lake(lab), default=str)
    assert "build-runner" in dumped and SECRET not in dumped and "corp.internal" not in dumped
    con = sqlite3.connect(lab["data"] / "meta.sqlite")
    for (table,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'"):
        text = json.dumps(con.execute(f'SELECT * FROM "{table}"').fetchall(), default=str)
        assert SECRET not in text, table
        assert TOKEN_SECRET not in text, table  # encrypted at rest


def test_replacing_the_token_with_one_that_can_change_things_is_refused(
    lab: dict[str, Any],
) -> None:
    assert add(lab).status_code == 201
    lab["fake"].grant("VM.PowerMgmt")
    res = lab["admin"].put(
        "/api/sources/pve/credentials", json={"token_secret": TOKEN_SECRET}, headers=lab["h"]
    )
    assert res.status_code == 400 and "VM.PowerMgmt" in res.json()["detail"]
    # The poll checks too: a token widened after save stops reading.
    assert lab["app"].state.ingest.run_once() == 0
    status = lab["admin"].get("/api/sources").json()[0]["status"]
    assert status["state"] == "error" and "PVEAuditor" in status["error"]


def test_settings_have_no_skip_verification_switch(lab: dict[str, Any]) -> None:
    res = add(lab, body(verify_tls=False))
    assert res.status_code in (400, 422)
