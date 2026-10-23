"""Quiet-source alerts (ADR-0014): one alert on quiet, one on resume, admin-only settings."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.integration.test_alert_targets import Receiver
from tests.integration.test_schedules import NOW, make_lab


@pytest.fixture
def lab(tmp_path: Path) -> Any:
    out = make_lab(tmp_path)
    app = out["app"]
    # New sources start with Alert if quiet on (ADR-0037; tested below); these tests set
    # their own watches, so the defaults are turned off first.
    for sid in ("lin_auth", "win_dc"):
        off = out["admin"].put(
            f"/api/sources/{sid}/watch",
            json={"quiet_after_s": None, "target_ids": []},
            headers=out["h"],
        )
        assert off.status_code == 200, off.text
    with app.state.meta.connect() as con:
        out["audit_from"] = con.execute("SELECT max(rowid) FROM audit_log").fetchone()[0]
    app.state.alert_dispatcher._clock = out["clock"]
    app.state.quiet._clock = out["clock"]
    received: dict[str, datetime | None] = {"lin_auth": NOW, "win_dc": NOW}
    app.state.quiet._received = lambda: dict(received)
    out["received"] = received
    rx = Receiver()
    url = f"http://127.0.0.1:{rx.port}/hook/TOKEN123"
    res = out["admin"].post(
        "/api/alert-targets",
        json={"name": "Relay", "kind": "webhook", "url": url},
        headers=out["h"],
    )
    out["rx"], out["target"] = rx, res.json()["target_id"]
    yield out
    rx.server.shutdown()


def watch(lab: dict[str, Any], source_id: str = "lin_auth", **body: Any) -> Any:
    body = {"quiet_after_s": 3600, "target_ids": [lab["target"]], **body}
    return lab["admin"].put(f"/api/sources/{source_id}/watch", json=body, headers=lab["h"])


def tick(lab: dict[str, Any]) -> int:
    changed: int = lab["app"].state.quiet.tick()
    lab["app"].state.alert_dispatcher.tick()
    return changed


def actions(lab: dict[str, Any]) -> list[str]:
    with lab["app"].state.meta.connect() as con:
        rows = con.execute(
            "SELECT action FROM audit_log WHERE rowid > ? AND (action LIKE 'source.quiet%'"
            " OR action = 'source.resumed') ORDER BY rowid",
            (lab["audit_from"],),
        ).fetchall()
    return [r[0] for r in rows]


def test_quiet_then_resumed_alerts_once_each(lab: dict[str, Any]) -> None:
    res = watch(lab)
    assert res.status_code == 200, res.text
    assert res.json()["state"] == "ok"
    lab["clock"].now = NOW + timedelta(minutes=30)
    assert tick(lab) == 0  # not quiet yet
    lab["clock"].now = NOW + timedelta(minutes=61)
    assert tick(lab) == 1
    lab["clock"].now = NOW + timedelta(minutes=90)
    assert tick(lab) == 0  # still quiet: no repeat alert
    ((_, body),) = lab["rx"].got
    doc = json.loads(body)
    assert (doc["kind"], doc["title"]) == ("quiet", "lin_auth")
    assert doc["detail"] == "No events received for 1 h 1 min"
    src = next(s for s in lab["admin"].get("/api/sources").json() if s["source_id"] == "lin_auth")
    assert src["quiet"]["state"] == "quiet" and src["quiet"]["quiet_after_s"] == 3600

    lab["received"]["lin_auth"] = NOW + timedelta(minutes=95)
    lab["clock"].now = NOW + timedelta(minutes=96)
    assert tick(lab) == 1
    doc = json.loads(lab["rx"].got[1][1])
    assert doc["kind"] == "resumed"
    assert doc["detail"] == "Events arriving again after 1 h 35 min"
    assert actions(lab) == ["source.quiet_alert_change", "source.quiet", "source.resumed"]
    kinds = [d["kind"] for d in lab["admin"].get("/api/sources/lin_auth/deliveries").json()]
    assert sorted(kinds) == ["quiet", "resumed"]


def test_turning_on_restarts_the_clock(lab: dict[str, Any]) -> None:
    lab["clock"].now = NOW + timedelta(days=3)  # already quiet for days before the watch
    watch(lab)
    assert tick(lab) == 0
    lab["clock"].now += timedelta(minutes=61)
    assert tick(lab) == 1


def test_received_time_survives_a_restart(lab: dict[str, Any]) -> None:
    watch(lab)
    lab["received"]["lin_auth"] = NOW + timedelta(minutes=10)
    lab["clock"].now = NOW + timedelta(minutes=11)
    tick(lab)
    lab["received"]["lin_auth"] = None  # a restart forgets ingest status
    lab["clock"].now = NOW + timedelta(minutes=69)
    assert tick(lab) == 0  # quiet is measured from the stored 10-minute mark, not from 0
    lab["clock"].now = NOW + timedelta(minutes=71)
    assert tick(lab) == 1


def test_no_targets_still_audits(lab: dict[str, Any]) -> None:
    watch(lab, target_ids=[])
    lab["clock"].now = NOW + timedelta(hours=2)
    assert tick(lab) == 1
    assert lab["rx"].got == []
    assert actions(lab)[-1] == "source.quiet"


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"quiet_after_s": 299}, 422),
        ({"quiet_after_s": 7 * 86400 + 1}, 422),
        ({"target_ids": ["nope"]}, 400),
    ],
)
def test_validation(lab: dict[str, Any], body: dict[str, Any], code: int) -> None:
    assert watch(lab, **body).status_code == code
    assert lab["admin"].get("/api/sources/watches").json() == []


def test_unknown_source_and_turning_off(lab: dict[str, Any]) -> None:
    assert watch(lab, source_id="missing").status_code == 404
    watch(lab)
    res = watch(lab, quiet_after_s=None)
    assert res.status_code == 200 and res.json() is None
    assert lab["admin"].get("/api/sources/watches").json() == []
    assert actions(lab) == ["source.quiet_alert_change", "source.quiet_alert_change"]


def test_admin_only(lab: dict[str, Any]) -> None:
    for name in ("ana", "aud"):
        client = lab[name]
        assert client.get("/api/sources/watches").status_code == 403
        assert client.get("/api/sources/lin_auth/deliveries").status_code == 403
        res = client.put("/api/sources/lin_auth/watch", json={"quiet_after_s": 3600})
        assert res.status_code == 403


def test_deleted_source_drops_its_watch(lab: dict[str, Any]) -> None:
    watch(lab)
    res = lab["admin"].delete("/api/sources/lin_auth", headers=lab["h"])
    assert res.status_code in (200, 204), res.text
    lab["clock"].now = NOW + timedelta(hours=2)
    assert tick(lab) == 0
    assert lab["admin"].get("/api/sources/watches").json() == []


def test_overview_shows_quiet_sources_to_readers_of_them(lab: dict[str, Any]) -> None:
    watch(lab)
    lab["clock"].now = NOW + timedelta(hours=2)
    tick(lab)
    rows = {s["source_id"]: s for s in lab["admin"].get("/api/overview").json()["sources"]}
    assert rows["lin_auth"]["quiet_since"] is not None
    assert rows["win_dc"]["quiet_since"] is None
    ana = {s["source_id"]: s for s in lab["ana"].get("/api/overview").json()["sources"]}
    assert set(ana) == {"lin_auth"} and ana["lin_auth"]["quiet_since"] is not None


def test_new_sources_start_with_alert_if_quiet_on_by_kind(lab: dict[str, Any]) -> None:
    """ADR-0037 owner answer 3: on by default, 60 min, 3 h for API connectors, no targets,
    audited, editable."""
    from app.ingest.quiet import default_quiet_s

    assert (default_quiet_s("file"), default_quiet_s("syslog"), default_quiet_s("loki")) == (
        3600,
        3600,
        3600,
    )
    assert default_quiet_s("m365") == default_quiet_s("anthropic") == 3 * 3600
    logs = Path(lab["app"].state.config.paths.allowed_roots[0]) / "lin"
    body = {
        "source_id": "lin_two",
        "format": "syslog",
        "path": str(logs),
        "template_id": "linux_sshd",
    }
    assert lab["admin"].post("/api/sources", json=body, headers=lab["h"]).status_code == 201
    w = next(x for x in lab["app"].state.quiet.all() if x.source_id == "lin_two")
    assert (w.quiet_after_s, w.target_ids, w.state) == (3600, [], "ok")
    with lab["app"].state.meta.connect() as con:
        row = con.execute(
            "SELECT user_id, detail FROM audit_log WHERE action = 'source.quiet_alert_change'"
            " ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
    assert json.loads(row["detail"])["source_id"] == "lin_two" and row["user_id"]
