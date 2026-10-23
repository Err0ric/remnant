"""GET /api/overview (ADR-0008): numbers read as the viewer, cached, audited once."""

import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tests.integration.test_schedules import WIN_ID, make_lab, run_now, schedule


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    out = make_lab(tmp_path)
    out["app"].state.overview._clock = out["clock"]
    return out


def fresh(lab: dict[str, Any]) -> None:
    lab["app"].state.overview._cache.clear()


def audits(lab: dict[str, Any], user: str) -> int:
    with sqlite3.connect(lab["db"]) as db:
        (n,) = db.execute(
            "SELECT count(*) FROM audit_log WHERE action = 'overview.view' AND user_id = ?",
            (lab["ids"].get(user, user),),
        ).fetchone()
    return int(n)


def test_volume_matches_a_direct_query_and_covers_24_hours(lab: dict[str, Any]) -> None:
    o = lab["admin"].get("/api/overview").json()
    assert len(o["hours"]) == 24 and o["hours"][-1] == "2026-10-10T12:00:00+00:00"
    totals = {v["source_id"]: sum(v["counts"]) for v in o["volume"]}
    assert set(totals) == {"lin_auth", "win_dc"} and all(n > 0 for n in totals.values())
    res = (
        lab["admin"]
        .post(
            "/api/query",
            json={
                "sql": "SELECT source_id, count(*) FROM events GROUP BY 1 ORDER BY 1",
                "start": o["hours"][0],
                "end": o["generated_at"],
            },
            headers=lab["h"],
        )
        .json()
    )
    assert {r[0]: r[1] for r in res["rows"]} == totals
    states = {s["source_id"]: s["state"] for s in o["sources"]}
    assert states == {"lin_auth": "reading", "win_dc": "reading"}
    assert all(s["last_event_at"] for s in o["sources"])


def test_analysts_see_only_their_sources_and_no_alert_health(lab: dict[str, Any]) -> None:
    o = lab["ana"].get("/api/overview").json()
    assert [v["source_id"] for v in o["volume"]] == ["lin_auth"]
    assert [s["source_id"] for s in o["sources"]] == ["lin_auth"]
    assert o["alerts"] is None
    assert lab["admin"].get("/api/overview").json()["alerts"] == {
        "targets": [],
        "failed_deliveries": 0,
    }


def test_detections_leave_out_runs_the_viewer_cannot_read(lab: dict[str, Any]) -> None:
    s = schedule(lab["admin"], lab["h"], kind="rule", target_id=WIN_ID, shared=True).json()
    run_now(lab, lab["admin"], s["schedule_id"], lab["h"])
    (d,) = lab["admin"].get("/api/overview").json()["detections"]
    assert (d["kind"], d["name"], d["count"]) == ("rule", "Failed logon", 6)
    assert lab["ana"].get("/api/overview").json()["detections"] == []


def test_flagged_searches_and_paused_schedules_are_listed(lab: dict[str, Any]) -> None:
    sid = schedule(lab["ana"], shared=True, threshold_kind="above", threshold_value=0).json()[
        "schedule_id"
    ]
    run_now(lab, lab["ana"], sid)
    lab["ana"].patch(f"/api/schedules/{sid}", json={"paused": True})
    o = lab["bob"].get("/api/overview").json()
    (d,) = o["detections"]
    assert (d["kind"], d["schedule_id"], d["count"]) == ("search", sid, 1)
    assert [p["schedule_id"] for p in o["paused"]] == [sid]


def test_cached_for_a_minute_audited_once_and_never_across_an_access_change(
    lab: dict[str, Any],
) -> None:
    lab["ana"].get("/api/overview")
    lab["ana"].get("/api/overview")
    assert audits(lab, "ana") == 1
    lab["admin"].put(f"/api/groups/{lab['gid']}/sources", json={"source_ids": []}, headers=lab["h"])
    o = lab["ana"].get("/api/overview").json()
    assert o["volume"] == [] and o["sources"] == []
    assert audits(lab, "ana") == 2


def test_source_errors_are_hidden_from_non_admins(lab: dict[str, Any]) -> None:
    ingest = lab["app"].state.ingest
    with ingest._lock:
        st = ingest._status["lin_auth"]
        ingest._status["lin_auth"] = replace(st, error="Cannot read /srv/logs/lin/auth.log")
    fresh(lab)
    (mine,) = lab["ana"].get("/api/overview").json()["sources"]
    assert mine["state"] == "error" and "/srv" not in (mine["error"] or "")
    admin = {s["source_id"]: s for s in lab["admin"].get("/api/overview").json()["sources"]}
    assert "/srv/logs" in admin["lin_auth"]["error"]


def test_each_source_has_a_typical_count_and_a_mark_per_hour(lab: dict[str, Any]) -> None:
    for v in lab["admin"].get("/api/overview").json()["volume"]:
        assert len(v["typical"]) == len(v["counts"]) == len(v["marks"]) == 24
        assert set(v["marks"]) <= {"", "busy", "quiet"}


def test_ingest_status_is_seeded_from_stored_events(lab: dict[str, Any]) -> None:
    # QA F8: after a restart, Health showed "never" for sources that had data.
    from app.ingest.watcher import IngestService
    from app.main import _seed_last_events

    ingest: IngestService = lab["app"].state.ingest
    with ingest._lock:
        ingest._status.clear()
    _seed_last_events(ingest, lab["app"].state.engine)
    status = ingest.status()
    assert status["lin_auth"].last_event_at is not None


def test_a_steady_source_that_stops_has_a_gap_and_rates_are_per_minute(
    lab: dict[str, Any],
) -> None:
    """F55: five empty hours from a source that sends every hour are called out, while the
    other sources kept flowing, with the 24 h total and a current rate per source."""
    from datetime import datetime, timedelta

    from app.ingest.writer import LakeWriter
    from tests.integration.test_schedules import _lake_rows

    o = lab["admin"].get("/api/overview").json()
    first = datetime.fromisoformat(o["hours"][0])
    lake = lab["app"].state.engine._lake
    for i in range(23):
        if 9 <= i < 14:
            continue  # nothing from 09:00 to 14:00 in the window
        LakeWriter(lake).write(
            _lake_rows("fw_gap", "generic_syslog", first + timedelta(hours=i), 3)
        )
    fresh(lab)
    o = lab["admin"].get("/api/overview").json()
    (fw,) = [v for v in o["volume"] if v["source_id"] == "fw_gap"]
    assert fw["total"] == 18 * 3
    (gap,) = fw["gaps"]
    assert gap["start"] == (first + timedelta(hours=9)).isoformat()
    assert gap["end"] == (first + timedelta(hours=14)).isoformat() and gap["hours"] == 5
    assert gap["ongoing"] is False
    assert o["events_24h"] == sum(v["total"] for v in o["volume"])
    assert all(isinstance(s["rate_per_min"], float) for s in o["sources"])
