"""Proxmox inventory matches (ADR-0045 A5, A6) and empty-result explanations (Part B), over
the caller's own sources, against the fake Proxmox API."""

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.integration.test_proxmox_inventory import BASE, add, make_lab, poll

SSHD = "<38>Nov  6 11:50:00 web-01 sshd[811]: Accepted publickey for alice from 10.9.9.9 port 50122 ssh2"


@pytest.fixture
def lab(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    lab = make_lab(tmp_path, monkeypatch, 9)
    assert add(lab).status_code == 201
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "auth.log").write_text(SSHD + "\n")
    a, h = lab["admin"], lab["h"]
    body = {
        "source_id": "lin_auth",
        "format": "syslog",
        "path": str(logs),
        "template_id": "linux_sshd",
    }
    assert a.post("/api/sources", json=body, headers=h).status_code == 201
    lab["app"].state.ingest.run_once()
    res = a.post("/api/users", json={"username": "ana", "role": "analyst"}, headers=h)
    ana_id = res.json()["user"]["user_id"]
    a.post(
        "/api/account/password",
        json={"token": res.json()["invite_token"], "password": "another long passphrase"},
    )
    login = TestClient(lab["app"], base_url=BASE).post(
        "/api/auth/login",
        json={"username": "ana", "password": "another long passphrase", "client": "cli"},
    )
    lab["ana"] = TestClient(
        lab["app"], base_url=BASE, headers={"Authorization": f"Bearer {login.json()['token']}"}
    )
    gid = a.post("/api/groups", json={"name": "Linux"}, headers=h).json()["group_id"]
    a.put(f"/api/groups/{gid}/sources", json={"source_ids": ["lin_auth"]}, headers=h)
    a.put(f"/api/groups/{gid}/members", json={"user_ids": [ana_id]}, headers=h)
    return lab


def matches(client: TestClient, *values: str) -> dict[str, list[dict[str, Any]]]:
    res = client.get("/api/inventory/matches", params={"value": list(values)})
    assert res.status_code == 200, res.text
    out: dict[str, list[dict[str, Any]]] = res.json()["matches"]
    return out


def test_exact_ip_mac_and_name_matches_with_first_and_last_seen(lab: dict[str, Any]) -> None:
    got = matches(
        lab["admin"], "10.20.30.41", "52:54:00:AB:CD:05", "Build-Runner", "10.20.30", "build"
    )
    (vm,) = got["10.20.30.41"]
    assert (vm["type"], vm["vmid"], vm["name"], vm["node"]) == ("qemu", 104, "build-runner", "pve2")
    assert vm["current"] and vm["first_seen"] == vm["last_seen"]
    assert "json_extract_string(raw, '$.vmid') = '104'" in vm["search_sql"]
    assert [m["vmid"] for m in got["52:54:00:AB:CD:05"]] == [105]
    assert [m["vmid"] for m in got["Build-Runner"]] == [104]
    assert got["10.20.30"] == [] and got["build"] == []  # never by similarity
    shown = lab["admin"].post("/api/query", json={"sql": vm["search_sql"]}, headers=lab["h"])
    assert shown.status_code == 200 and len(shown.json()["rows"]) == 1


def test_an_address_two_guests_held_shows_both(lab: dict[str, Any]) -> None:
    guests = lab["fake"].guests
    guests[201]["report"][1]["inet"] = "192.168.10.77/24"  # the container lets .5 go
    guests[201]["config"]["net0"] = guests[201]["config"]["net0"].replace(".5/24", ".77/24")
    poll(lab)
    guests[105]["config"]["ipconfig0"] = "ip=192.168.10.5/24"  # and the VM takes it
    poll(lab)
    got = {m["vmid"]: m for m in matches(lab["admin"], "192.168.10.5")["192.168.10.5"]}
    assert set(got) == {201, 105}
    assert got[105]["current"] and got[201]["current"] is False
    assert got[201]["last_seen"] < got[105]["first_seen"]
    # Still found when the range starts after the last change (the daily snapshot rule).
    start = (lab["clock"].now + timedelta(hours=3)).isoformat()
    later = lab["admin"].get(
        "/api/inventory/matches", params={"value": "192.168.10.5", "start": start}
    )
    assert [m["vmid"] for m in later.json()["matches"]["192.168.10.5"]] == [105]


def test_matches_and_coverage_read_only_the_callers_sources(lab: dict[str, Any]) -> None:
    assert matches(lab["ana"], "10.20.30.41")["10.20.30.41"] == []
    res = lab["ana"].get("/api/inventory/coverage", params={"value": "10.20.30.41"})
    body = res.json()
    assert body["inventory_source"] is False and body["inventory"] == []
    assert body["restricted"] is True and body["can_add_source"] is False
    assert [c["category"] for c in body["categories"]] == ["identity"]
    with lab["app"].state.meta.connect() as con:
        actions = [r[0] for r in con.execute("SELECT action FROM audit_log")]
    assert "inventory.match" in actions and "address.coverage" in actions


def test_coverage_says_what_was_searched_and_what_could_see_it(lab: dict[str, Any]) -> None:
    res = lab["admin"].get("/api/inventory/coverage", params={"value": "10.20.30.41"})
    body = res.json()
    # Inventory events do not count as events naming the address.
    assert body["events"] == 0 and body["restricted"] is False and body["can_add_source"]
    (identity,) = body["categories"]  # sshd sign-ins
    assert identity["category"] == "identity"
    assert identity["sources"] == [
        {"source_id": "lin_auth", "state": "receiving", "since": None, "records_address": True}
    ]
    assert body["missing"] == ["dns", "network", "system"]
    assert body["inventory_source"] is True
    assert [m["vmid"] for m in body["inventory"]] == [104]
    # The sshd line names 10.9.9.9: there are events, so no explanation is needed.
    found = lab["admin"].get("/api/inventory/coverage", params={"value": "10.9.9.9"})
    assert found.json()["events"] == 1
    # Two hours later the file source has sent nothing for longer than its quiet period.
    lab["clock"].now += timedelta(hours=2)
    late = lab["admin"].get("/api/inventory/coverage", params={"value": "10.1.1.1"}).json()
    note = late["categories"][0]["sources"][0]
    assert note["state"] == "not_receiving" and note["since"].startswith("2026-11-06T12:")
    assert late["inventory"] == []
