"""Schedules send summary alerts to their targets, with retries (ADR-0007)."""

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.integration.test_alert_targets import Receiver
from tests.integration.test_schedules import WIN_ID, make_lab, run_now, schedule


@pytest.fixture
def lab(tmp_path: Path) -> Any:
    out = make_lab(tmp_path)
    out["app"].state.alert_dispatcher._clock = out["clock"]
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


def tick(lab: dict[str, Any]) -> int:
    n: int = lab["app"].state.alert_dispatcher.tick()
    return n


def deliveries(lab: dict[str, Any], sid: str) -> list[dict[str, Any]]:
    res = lab["admin"].get(f"/api/schedules/{sid}/deliveries")
    out: list[dict[str, Any]] = res.json()
    return out


def test_rule_matches_send_a_summary_without_event_content(lab: dict[str, Any]) -> None:
    s = schedule(
        lab["admin"], lab["h"], kind="rule", target_id=WIN_ID, target_ids=[lab["target"]]
    ).json()
    assert s["target_ids"] == [lab["target"]]
    run_now(lab, lab["admin"], s["schedule_id"], lab["h"])
    assert [d["status"] for d in deliveries(lab, s["schedule_id"])] == ["pending"]
    assert tick(lab) == 1
    ((_, body),) = lab["rx"].got
    doc = json.loads(body)
    assert (doc["kind"], doc["count"], doc["detail"]) == (
        "match",
        6,
        "Rule: Failed logon by Jane Doe",
    )
    assert doc["link"] == "https://siem.example.internal:8080/dashboard"
    run = lab["admin"].get("/api/schedules").json()[0]["recent"][0]
    assert run["rule_run_id"] not in body.decode()  # summary only: no ids, rows, or fields
    (d,) = deliveries(lab, s["schedule_id"])
    assert (d["status"], d["attempts"], d["target_name"]) == ("sent", 1, "Relay")


def test_saved_searches_alert_only_when_flagged(lab: dict[str, Any]) -> None:
    quiet = schedule(lab["ana"], target_ids=[lab["target"]], lookback_minutes=4320).json()
    run_now(lab, lab["ana"], quiet["schedule_id"])
    assert deliveries(lab, quiet["schedule_id"]) == []
    loud = schedule(
        lab["ana"], target_ids=[lab["target"]], lookback_minutes=4320,
        threshold_kind="above", threshold_value=0,
    ).json()  # fmt: skip
    run_now(lab, lab["ana"], loud["schedule_id"])
    tick(lab)
    doc = json.loads(lab["rx"].got[0][1])
    assert (doc["kind"], doc["reason"], doc["detail"]) == ("flag", "1 is above 0", "Saved search")


def test_a_schedule_that_pauses_itself_says_why_and_manual_pauses_stay_quiet(
    lab: dict[str, Any],
) -> None:
    s = schedule(
        lab["admin"], lab["h"], kind="rule", target_id=WIN_ID, target_ids=[lab["target"]]
    ).json()
    lab["admin"].patch(
        f"/api/schedules/{s['schedule_id']}", json={"paused": True}, headers=lab["h"]
    )
    assert deliveries(lab, s["schedule_id"]) == []
    lab["admin"].patch(
        f"/api/schedules/{s['schedule_id']}", json={"paused": False}, headers=lab["h"]
    )
    lab["admin"].post(
        "/api/rules/enabled", json={"rule_ids": [WIN_ID], "enabled": False}, headers=lab["h"]
    )
    run_now(lab, lab["admin"], s["schedule_id"], lab["h"])
    tick(lab)
    doc = json.loads(lab["rx"].got[0][1])
    assert doc["kind"] == "pause" and "disabled" in doc["detail"] and doc["count"] is None


def test_failures_retry_then_stop_and_never_show_the_url(lab: dict[str, Any]) -> None:
    lab["rx"].status = 503
    s = schedule(
        lab["admin"], lab["h"], kind="rule", target_id=WIN_ID, target_ids=[lab["target"]]
    ).json()
    run_now(lab, lab["admin"], s["schedule_id"], lab["h"])
    tick(lab)
    (d,) = deliveries(lab, s["schedule_id"])
    assert (d["status"], d["attempts"]) == ("pending", 1)
    assert tick(lab) == 0  # not due again for a minute
    for wait in (1, 5, 15):
        lab["clock"].now += timedelta(minutes=wait)
        assert tick(lab) == 1
    (d,) = deliveries(lab, s["schedule_id"])
    assert (d["status"], d["attempts"]) == ("failed", 4)
    assert d["last_error"] == "The destination answered HTTP 503" and "TOKEN123" not in json.dumps(
        d
    )
    assert len(lab["rx"].got) == 4


def test_unknown_targets_are_refused_before_anything_is_made(lab: dict[str, Any]) -> None:
    res = schedule(lab["admin"], lab["h"], kind="rule", target_id=WIN_ID, target_ids=["nope"])
    assert res.status_code == 400
    assert lab["admin"].get("/api/schedules").json() == []
