"""Hand-off of selected events to an alert target (ADR-0024)."""

import json
import sqlite3
from typing import Any

import pytest

from app.alerts.render import Alert, slack_payload, webhook_body
from tests.integration.test_schedules import make_lab


@pytest.fixture
def lab(tmp_path: Any) -> dict[str, Any]:
    out = make_lab(tmp_path)
    res = out["admin"].post(
        "/api/alert-targets",
        json={"name": "Case desk", "kind": "webhook", "url": "http://127.0.0.1:9/hook"},
        headers=out["h"],
    )
    assert res.status_code in (200, 201), res.text
    out["target"] = res.json()["target_id"]
    return out


def _ids(lab: dict[str, Any], n: int) -> list[str]:
    rows = (
        lab["admin"]
        .post(
            "/api/query", json={"sql": f"SELECT event_id FROM events LIMIT {n}"}, headers=lab["h"]
        )
        .json()["rows"]
    )
    return [str(r[0]) for r in rows]


def _queued(lab: dict[str, Any]) -> list[dict[str, Any]]:
    with sqlite3.connect(lab["db"]) as db:
        rows = db.execute("SELECT alert FROM alert_deliveries WHERE schedule_id IS NULL").fetchall()
    return [json.loads(r[0]) for r in rows if json.loads(r[0])["kind"] == "handoff"]


def test_events_go_to_a_private_target_with_a_note(lab: dict[str, Any]) -> None:
    ids = _ids(lab, 3)
    res = lab["ana"].post(
        "/api/handoff",
        json={"target_id": lab["target"], "event_ids": ids, "note": "Look at these logons"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["sent"] == 3 and res.json()["withheld_local_only"] == 0
    (alert,) = _queued(lab)
    assert alert["detail"] == "Look at these logons" and alert["title"] == "Events from ana"
    assert sorted(e["event_id"] for e in alert["events"]) == sorted(ids)
    assert all("raw" in e for e in alert["events"])
    audit = lab["aud"].get("/api/audit/events", params={"action": "handoff."}).json()
    assert audit[0]["username"] == "ana" and audit[0]["outcome"] == "success"


def test_local_only_events_stay_home_unless_the_target_is_private(lab: dict[str, Any]) -> None:
    lab["app"].state.alert_targets.private = lambda _tid: False  # a chat service, say
    ids = _ids(lab, 2)
    res = lab["admin"].post(
        "/api/handoff", json={"target_id": lab["target"], "event_ids": ids}, headers=lab["h"]
    )
    # The lab's sources are local_only (the default), so nothing may leave.
    assert res.status_code == 400
    assert "local-only" in res.json()["detail"]
    assert _queued(lab) == []
    denied = lab["aud"].get("/api/audit/events", params={"action": "handoff."}).json()
    assert denied[0]["outcome"] == "denied"


def test_roles_limits_and_unknown_ids(lab: dict[str, Any]) -> None:
    assert (
        lab["aud"]
        .post("/api/handoff", json={"target_id": lab["target"], "event_ids": _ids(lab, 1)})
        .status_code
        == 403
    )
    too_many = [f"00000000-0000-7000-8000-{i:012d}" for i in range(101)]
    assert (
        lab["ana"].post("/api/handoff", json={"target_id": lab["target"], "event_ids": too_many})
    ).status_code == 422
    bad = lab["ana"].post(
        "/api/handoff", json={"target_id": lab["target"], "event_ids": ["x'; DROP"]}
    )
    assert bad.status_code == 400
    unknown = lab["ana"].post(
        "/api/handoff",
        json={"target_id": lab["target"], "event_ids": ["00000000-0000-7000-8000-000000000001"]},
    )
    assert unknown.status_code == 400
    assert "none of the selected" in unknown.json()["detail"].lower()
    gone = lab["ana"].post("/api/handoff", json={"target_id": "nope", "event_ids": _ids(lab, 1)})
    assert gone.status_code == 404


def test_chat_gets_a_short_escaped_list_and_webhooks_the_events() -> None:
    events = [
        {
            "event_id": f"e{i}",
            "time": "2026-10-17T10:00:00+00:00",
            "source_id": "fw",
            "message": "<@channel> hello",
            "raw": "x",
        }
        for i in range(25)
    ]
    alert = Alert(
        "handoff", "Events from ana", "note", 25, None, None, None, None, "P", tuple(events)
    )
    text = slack_payload(alert)["text"]
    assert "&lt;@channel&gt;" in text and "<@channel>" not in text
    assert "and 5 more" in text
    body = json.loads(webhook_body(alert))
    assert len(body["events"]) == 25 and body["events"][0]["raw"] == "x"
    plain = json.loads(webhook_body(Alert("test", "t", "d", None, None, None, None, None, "P")))
    assert "events" not in plain  # every other alert stays a summary (ADR-0007)
