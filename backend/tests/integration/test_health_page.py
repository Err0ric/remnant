"""Health page (ADR-0019): watched devices seen in events, alerts on silence and return,
admin-only changes, per-viewer scope, and per-machine agents."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.core.errors import ParamInvalidError
from app.search.health import DeviceWatch, evaluate, normalize
from tests.integration.test_alert_targets import Receiver
from tests.integration.test_schedules import make_lab

T = datetime(2026, 10, 9, 20, 44, tzinfo=UTC)


@pytest.fixture
def lab(tmp_path: Path) -> Any:
    out = make_lab(tmp_path)
    app = out["app"]
    app.state.alert_dispatcher._clock = out["clock"]
    app.state.health._clock = out["clock"]
    out["clock"].now = T  # just after the Linux fixture's last event
    rx = Receiver()
    res = out["admin"].post(
        "/api/alert-targets",
        json={"name": "Relay", "kind": "webhook", "url": f"http://127.0.0.1:{rx.port}/hook/T1"},
        headers=out["h"],
    )
    out["rx"], out["target"] = rx, res.json()["target_id"]
    yield out
    rx.server.shutdown()


def add(lab: dict[str, Any], **body: Any) -> Any:
    body = {"name": "Bastion", "match": "BASTION", "silence_s": 900, **body}
    return lab["admin"].post("/api/health-checks/devices", json=body, headers=lab["h"])


def checks(client: Any) -> dict[str, Any]:
    res = client.get("/api/health-checks")
    assert res.status_code == 200, res.text
    data: dict[str, Any] = res.json()
    return data


def test_devices_are_seen_in_events_by_host_or_address(lab: dict[str, Any]) -> None:
    assert add(lab).status_code == 201
    assert add(lab, name="Jump box", match="10.20.1.6").status_code == 201
    assert add(lab, name="DC", match="dc01").status_code == 201  # matches DC01.corp.example
    assert add(lab, name="Gone", match="ghost.example.net").status_code == 201
    got = {d["name"]: d for d in checks(lab["admin"])["devices"]}
    assert got["Bastion"]["match"] == "bastion"  # stored lower case
    for name in ("Bastion", "Jump box", "DC"):
        assert got[name]["state"] == "healthy", got[name]
        assert got[name]["last_seen"] and sum(got[name]["hourly"]) > 0
    assert got["Gone"]["state"] == "unknown"
    # An analyst reads only Linux: the domain controller is not in their sources.
    ana = {d["name"]: d for d in checks(lab["ana"])["devices"]}
    assert ana["Bastion"]["state"] == "healthy" and ana["DC"]["state"] == "unknown"
    assert ana["Bastion"]["target_ids"] == []


def test_changes_are_admin_only_validated_and_audited(lab: dict[str, Any]) -> None:
    body = {"name": "x", "match": "bastion", "silence_s": 900}
    assert lab["ana"].post("/api/health-checks/devices", json=body).status_code == 403
    assert add(lab, match="not a host!").status_code == 400
    assert add(lab, silence_s=60).status_code == 400
    assert add(lab, target_ids=["nope"]).status_code == 400
    did = add(lab).json()["device_id"]
    assert add(lab, name="Again").status_code == 400  # same address twice
    res = lab["admin"].put(
        f"/api/health-checks/devices/{did}",
        json={"name": "Bastion host", "match": "bastion", "silence_s": 3600},
        headers=lab["h"],
    )
    assert res.status_code == 200
    res = lab["admin"].delete(f"/api/health-checks/devices/{did}", headers=lab["h"])
    assert res.status_code == 204
    with lab["app"].state.meta.connect() as con:
        n = con.execute(
            "SELECT count(*) FROM audit_log WHERE action = 'device_watch.change'"
        ).fetchone()[0]
    assert n == 3


def test_silence_alerts_once_and_return_alerts_once(lab: dict[str, Any]) -> None:
    add(lab, target_ids=[lab["target"]])
    app = lab["app"]

    def tick() -> int:
        changed: int = app.state.health.tick()
        app.state.alert_dispatcher.tick()
        return changed

    assert tick() == 0
    lab["clock"].now = T + timedelta(minutes=20)  # 15 min allowed
    assert tick() == 1
    assert tick() == 0  # no repeat
    doc = json.loads(lab["rx"].got[0][1])
    assert (doc["kind"], doc["title"]) == ("device_quiet", "Bastion")
    assert doc["detail"].startswith("Silent 20 min")
    # Seen again: new events arrive for the device.
    app.state.ingest._clock = lambda: T + timedelta(minutes=25)
    src = next(s for s in app.state.sources.list() if s.source_id == "lin_auth")
    lin = Path(src.path) / "auth.log"
    with lin.open("a") as f:
        f.write("<38>Oct  9 21:05:00 bastion sshd[1]: Accepted publickey for x from 10.0.0.1\n")
    app.state.ingest.run_once()
    lab["clock"].now = T + timedelta(minutes=26)
    assert tick() == 1
    assert json.loads(lab["rx"].got[1][1])["kind"] == "device_resumed"
    with app.state.meta.connect() as con:
        acts = [
            r[0]
            for r in con.execute(
                "SELECT action FROM audit_log WHERE action LIKE 'device.%' ORDER BY rowid"
            )
        ]
    assert acts == ["device.quiet", "device.resumed"]


def test_health_view_is_audited(lab: dict[str, Any]) -> None:
    checks(lab["ana"])
    with lab["app"].state.meta.connect() as con:
        row = con.execute(
            "SELECT detail FROM audit_log WHERE action = 'health.view' ORDER BY rowid DESC"
        ).fetchone()
    assert json.loads(row[0])["sources_in_scope"] == ["lin_auth"]


def test_normalize_and_quieter_than_usual() -> None:
    assert normalize(" 10.0.0.1 ") == "10.0.0.1"
    assert normalize("2001:DB8::1") == "2001:db8::1"
    assert normalize("Sensor-A.corp.example.") == "sensor-a.corp.example"
    for bad in ("", "a b", "x" * 300, "-lead.example", "a;rm"):
        with pytest.raises(ParamInvalidError):
            normalize(bad)
    now = datetime(2026, 10, 10, 12, 30, tzinfo=UTC)
    d = DeviceWatch("d1", "Sensor", "s1", 3600, [], "ok", None, None, now.isoformat())
    hour0 = now.replace(minute=0) - timedelta(hours=23)
    rows = [["s1", hour0 + timedelta(hours=i), 100, hour0 + timedelta(hours=i)] for i in range(22)]
    rows += [["s1", hour0 + timedelta(hours=22), 5, hour0 + timedelta(hours=22)]]
    rows += [["s1", hour0 + timedelta(hours=23), 5, now - timedelta(minutes=5)]]
    (st,) = evaluate([d], rows, now)
    assert st.state == "attention" and st.reason == "Quieter than usual: 5% of its normal volume"
    assert len(st.hourly) == 24 and st.hourly[0] == 100


def test_agents_per_machine(tmp_path: Path) -> None:
    from tests.integration import test_otlp

    out = test_otlp.lab.__wrapped__(tmp_path)  # type: ignore[attr-defined]  # the fixture body
    assert test_otlp.send(out, test_otlp.payload()).status_code == 200
    out["app"].state.ingest._clock = lambda: test_otlp.T0
    out["app"].state.ingest.run_once()
    out["app"].state.health._clock = lambda: test_otlp.T0 + timedelta(days=2)
    agents = checks(out["admin"])["agents"]
    (ws,) = [a for a in agents if a["machine"] == "ws-0042"]
    assert (ws["kind"], ws["source_id"]) == ("OpenTelemetry", "claude")
    assert ws["state"] == "attention" and ws["reason"].startswith("Last reported 2 d")
    # The analyst cannot read the OpenTelemetry source.
    assert checks(out["ana"])["agents"] == []


def test_quarantined_files_are_counted(lab: dict[str, Any]) -> None:
    from app.ingest.durable import sweep

    lake = lab["app"].state.lake_dir
    folder = next(lake.glob("source=lin_auth/day=*"))
    (folder / "part-empty.parquet").write_bytes(b"")
    assert sweep(lake) == 1
    assert checks(lab["admin"])["quarantined_files"] == 1
