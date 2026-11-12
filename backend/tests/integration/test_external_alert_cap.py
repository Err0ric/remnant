"""ADR-0049 0b (D231): the per-source vendor alert cap, its pause and notice, and the
per-source switch that sends new vendor alerts to alert targets."""

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from app.alerts import external
from app.alerts.external import ExternalAlerts
from app.alerts.external_cap import ExternalAlertSettings
from tests.integration.test_alert_targets import Receiver
from tests.integration.test_external_alerts import T, _ext, _Registry, _send
from tests.integration.test_schedules import make_lab
from tests.unit.test_alert_templates import ALERT, template

PEOPLE = ("bob", "carol", "dave", "erin", "frank", "grace", "heidi", "ivan")


def alert(n: int, person: str = "alice", sev: int = 9) -> str:
    return (
        ALERT.replace("A-1001", f"A-{2000 + n}")
        .replace("suser=alice", f"suser={person}")
        .replace("|9|", f"|{sev}|")
    )


@pytest.fixture
def lab(tmp_path: Path) -> Any:
    out = make_lab(tmp_path)
    app = out["app"]
    rx = Receiver()
    res = out["admin"].post(
        "/api/alert-targets",
        json={"name": "Relay", "kind": "webhook", "url": f"http://127.0.0.1:{rx.port}/hook/T1"},
        headers=out["h"],
    )
    out["target"] = res.json()["target_id"]
    out["settings"] = ExternalAlertSettings(
        app.state.meta, app.state.auth.audit, lambda: {"edr"}, clock=lambda: T
    )
    out["t"] = template()
    out["watch"] = ExternalAlerts(
        app.state.engine,
        app.state.meta,
        app.state.alert_items,
        _Registry(out["t"]),
        settings=out["settings"],
        dispatcher=app.state.alert_dispatcher,
        audit=app.state.auth.audit,
        link="https://siem.example.internal:8080",
    )
    out["at"] = T
    yield out
    rx.server.shutdown()


def _sent(lab: dict[str, Any]) -> list[str]:
    rows = lab["app"].state.alert_dispatcher.deliveries(source_id="edr", limit=100)
    return [d.kind for d in reversed(rows)]


def _alerts(lab: dict[str, Any]) -> list[dict[str, Any]]:
    with lab["app"].state.meta.connect() as con:
        rows = con.execute(
            "SELECT alert FROM alert_deliveries WHERE source_id = 'edr' ORDER BY created_at"
        ).fetchall()
    return [json.loads(r[0]) for r in rows]


def _notify(lab: dict[str, Any], on: bool = True, min_severity: str = "high") -> None:
    who = lab["app"].state.auth.users.get(lab["ids"]["ana"])
    lab["settings"].set("edr", on, [lab["target"]], min_severity, who, None)


def test_notify_is_off_by_default(lab: dict[str, Any]) -> None:
    assert lab["settings"].get("edr").notify is False
    assert lab["settings"].get("edr").min_severity == "high"
    _send(lab, alert(1))
    assert len(_ext(lab)) == 1 and _sent(lab) == []


def test_notify_sends_new_items_and_rises_at_or_above_the_minimum(lab: dict[str, Any]) -> None:
    _notify(lab)
    _send(lab, alert(1))  # high: sent
    _send(lab, alert(1))  # a resend: nothing
    _send(lab, alert(2, "bob", sev=5))  # medium, under the minimum: raised, not sent
    assert len(_ext(lab)) == 2 and _sent(lab) == ["vendor_alert"]
    (msg,) = _alerts(lab)
    assert msg["severity"] == "high" and "alerts#item=" in msg["link"]
    assert msg["detail"] == "ExampleCorp EdgeSensor alert A-2001, critical severity"
    _send(lab, alert(2, "bob", sev=8))  # the medium alert comes back high: a rise, sent
    assert _sent(lab) == ["vendor_alert", "vendor_alert"]


def test_a_source_over_its_cap_holds_medium_and_below_but_raises_high(
    lab: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(external, "CAP", 3)
    _notify(lab)
    for i, who in enumerate(PEOPLE[:3]):
        _send(lab, alert(i, who, sev=5))
    assert len(_ext(lab)) == 3
    assert "edr" in lab["settings"].pauses()
    _send(lab, alert(10, "erin", sev=5), alert(11, "frank", sev=3), alert(12, "grace", sev=5))
    assert len(_ext(lab)) == 3  # held: stored, not raised
    _send(lab, alert(13, "heidi", sev=9))  # High skips the cap
    assert len(_ext(lab)) == 4
    _send(lab, alert(12, "grace", sev=9))  # a held alert resent as High raises
    assert len(_ext(lab)) == 5
    assert lab["settings"].pauses()["edr"].held == {"medium": 1, "low": 1}
    sql = "SELECT count(*) FROM events WHERE source_id = 'edr'"
    res = lab["admin"].post("/api/query", json={"sql": sql}, headers=lab["h"])
    assert res.json()["rows"] == [[8]]  # every alert line is stored
    # One short notice as the pause starts, then only the High alerts.
    assert _sent(lab) == ["vendor_paused", "vendor_alert", "vendor_alert"]
    start = _alerts(lab)[0]
    assert "High and Critical still raise" in start["detail"] and start["count"] is None

    lab["at"] += timedelta(minutes=61)  # the hour drops back under the cap
    lab["watch"].tick(lab["at"])
    assert lab["settings"].pauses() == {}
    assert _sent(lab)[-1] == "vendor_resumed"  # the summary, at the end, with the counts
    notice = _alerts(lab)[-1]
    assert (
        notice["count"] == 2 and "Held, stored but not raised: 1 medium, 1 low." in notice["detail"]
    )
    lab["at"] += timedelta(minutes=5)
    lab["watch"].tick(lab["at"])
    assert _sent(lab).count("vendor_paused") == 1 and _sent(lab).count("vendor_resumed") == 1
    _send(lab, alert(20, "ivan", sev=5))  # resumed: medium raises again
    assert len(_ext(lab)) == 6


def test_pause_notices_go_to_every_target_when_the_source_has_none(
    lab: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """D235: a pause is never silent. Notify off and no targets chosen: both notices go to
    every alert target, and only the two."""
    monkeypatch.setattr(external, "CAP", 2)
    other = (
        lab["admin"]
        .post(
            "/api/alert-targets",
            json={"name": "Second", "kind": "webhook", "url": "http://127.0.0.1:9/hook/T2"},
            headers=lab["h"],
        )
        .json()["target_id"]
    )
    for i, who in enumerate(PEOPLE[:4]):
        _send(lab, alert(i, who, sev=5))
    assert "edr" in lab["settings"].pauses()
    lab["at"] += timedelta(minutes=61)
    lab["watch"].tick(lab["at"])
    rows = lab["app"].state.alert_dispatcher.deliveries(source_id="edr", limit=100)
    sent = sorted((d.kind, d.target_id) for d in rows)
    assert sent == sorted(
        (k, t) for k in ("vendor_paused", "vendor_resumed") for t in (lab["target"], other)
    )


def test_alert_notify_api_is_admin_only_checked_and_audited(lab: dict[str, Any]) -> None:
    admin, h = lab["admin"], lab["h"]
    assert admin.get("/api/sources/win_dc/alert-notify").json() == {
        "notify": False,
        "target_ids": [],
        "min_severity": "high",
    }
    body = {"notify": True, "target_ids": [lab["target"]], "min_severity": "critical"}
    res = admin.put("/api/sources/win_dc/alert-notify", json=body, headers=h)
    assert res.status_code == 200 and res.json() == body
    bad = {**body, "target_ids": ["nope"]}
    assert admin.put("/api/sources/win_dc/alert-notify", json=bad, headers=h).status_code == 400
    wrong = {**body, "min_severity": "urgent"}
    assert admin.put("/api/sources/win_dc/alert-notify", json=wrong, headers=h).status_code == 422
    assert admin.get("/api/sources/none/alert-notify").status_code == 404
    assert lab["ana"].get("/api/sources/win_dc/alert-notify").status_code == 403
    with lab["app"].state.meta.connect() as con:
        (n,) = con.execute(
            "SELECT count(*) FROM audit_log WHERE action = 'source.vendor_alert_change'"
        ).fetchone()
    assert n == 1
    listed = {s["source_id"]: s for s in admin.get("/api/sources").json()}
    assert listed["win_dc"]["emits_alerts"] is False and listed["win_dc"]["alert_pause"] is None
