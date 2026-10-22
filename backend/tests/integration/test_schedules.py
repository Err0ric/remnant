"""Scheduled saved searches and rules: owner, re-checks, pauses, visibility (SPEC 5.5)."""

import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.core.errors import QueryTimeoutError
from app.main import create_app

FIX = Path(__file__).parent.parent / "fixtures" / "logs"
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
ADMIN_PW = "correct horse battery"
USER_PW = "another long passphrase"
BASE = "https://siem.example.internal"
WIN_ID = "22222222-2222-4222-8222-222222222222"
WIN = f"""title: Failed logon
id: {WIN_ID}
author: Jane Doe
logsource: {{product: windows, service: security}}
detection:
  s: {{EventID: 4625}}
  condition: s
"""
SEARCH = {
    "id": "failed_ssh",
    "name": "Failed SSH",
    "sql": "SELECT source_id, count(*) AS n FROM events"
    " WHERE raw LIKE '%Failed password%' AND time BETWEEN {{start}} AND {{end}} GROUP BY 1",
    "visibility": "shared",
}


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    return make_lab(tmp_path)


def make_lab(tmp_path: Path) -> dict[str, Any]:
    """Windows and Linux fixtures ingested, a Windows rule imported and enabled, a shared
    saved search by ana, users ana and bob (analysts) and aud (auditor) in a Linux group,
    and a settable clock on the schedule service. Also used by test_alert_dispatch."""
    logs = tmp_path / "logs"
    (logs / "win").mkdir(parents=True)
    (logs / "lin").mkdir()
    shutil.copy(FIX / "windows_nxlog_json" / "sample.log", logs / "win" / "dc.log")
    shutil.copy(FIX / "linux_sshd" / "sample.log", logs / "lin" / "auth.log")
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "win.yml").write_text(WIN)
    config = load_config(
        Path("missing.yaml"),
        {
            "APP__PATHS__DATA_DIR": str(tmp_path / "data"),
            "APP__PATHS__ALLOWED_ROOTS": str(logs),
            "APP__PATHS__RULE_ROOTS": str(rules),
            "APP__SERVER__HOST": "0.0.0.0",
            "APP__SCHEDULES__KEEP_RUNS": "3",
            "APP__SERVER__PUBLIC_NAMES": "siem.example.internal",
            "APP__SCHEDULES__LAG_SECONDS": "0",  # exact ranges; the lag has its own test
            "APP__SCHEDULES__SAMPLE_ROWS": "4",
        },
    )
    app = create_app(config)
    app.state.ingest._clock = lambda: NOW
    clock = Clock()
    app.state.schedules._clock = clock
    admin = TestClient(app, base_url=BASE)
    token = app.state.auth.setup_url("siem.example.internal", 8080).split("#", 1)[1]
    csrf = admin.post(
        "/api/setup", json={"token": token, "username": "admin", "password": ADMIN_PW}
    ).json()["csrf_token"]
    h = {"X-CSRF-Token": csrf}
    for sid, tid, sub in (
        ("win_dc", "windows_nxlog_json", "win"),
        ("lin_auth", "linux_sshd", "lin"),
    ):
        body = {"source_id": sid, "format": "syslog", "path": str(logs / sub), "template_id": tid}
        assert admin.post("/api/sources", json=body, headers=h).status_code == 201
    app.state.ingest.run_once()
    admin.post("/api/rules/import", json={"path": str(rules)}, headers=h)
    admin.post("/api/rules/enabled", json={"rule_ids": [WIN_ID], "enabled": True}, headers=h)
    out: dict[str, Any] = {"app": app, "admin": admin, "h": h, "clock": clock, "ids": {}}
    for name, role in (("ana", "analyst"), ("bob", "analyst"), ("aud", "auditor")):
        res = admin.post("/api/users", json={"username": name, "role": role}, headers=h)
        out["ids"][name] = res.json()["user"]["user_id"]
        admin.post(
            "/api/account/password", json={"token": res.json()["invite_token"], "password": USER_PW}
        )
        login = TestClient(app, base_url=BASE).post(
            "/api/auth/login", json={"username": name, "password": USER_PW, "client": "cli"}
        )
        out[name] = TestClient(
            app, base_url=BASE, headers={"Authorization": f"Bearer {login.json()['token']}"}
        )
    gid = admin.post("/api/groups", json={"name": "Linux"}, headers=h).json()["group_id"]
    admin.put(f"/api/groups/{gid}/sources", json={"source_ids": ["lin_auth"]}, headers=h)
    members = [out["ids"][n] for n in ("ana", "bob", "aud")]
    admin.put(f"/api/groups/{gid}/members", json={"user_ids": members}, headers=h)
    out["gid"] = gid
    out["db"] = tmp_path / "data" / "meta.sqlite"
    assert out["ana"].post("/api/searches", json=SEARCH).status_code == 201
    return out


def schedule(client: TestClient, h: dict[str, str] | None = None, **body: Any) -> Any:
    base = {"kind": "search", "target_id": "failed_ssh", "cron": "daily", "lookback_minutes": 1440}
    return client.post("/api/schedules", json={**base, **body}, headers=h or {})


def run_now(
    lab: dict[str, Any], client: TestClient, sid: str, h: dict[str, str] | None = None
) -> Any:
    return client.post(f"/api/schedules/{sid}/run", headers=h or {})


def test_a_due_schedule_runs_as_its_owner_inside_the_owners_sources(lab: dict[str, Any]) -> None:
    res = schedule(lab["ana"], shared=True, lookback_minutes=4320)
    assert res.status_code == 201, res.text
    s = res.json()
    assert s["cron"] == "0 7 * * *" and s["next_run_at"] == "2026-10-11T07:00:00+00:00"
    svc = lab["app"].state.schedules
    assert svc.tick() == 0  # not due yet
    lab["clock"].now = datetime(2026, 10, 11, 7, 0, 20, tzinfo=UTC)
    assert svc.tick() == 1
    (run,) = lab["ana"].get("/api/schedules").json()[0]["recent"]
    assert (run["status"], run["sources_in_scope"], run["restricted"]) == (
        "ok",
        ["lin_auth"],
        False,
    )
    assert run["range_start"] == "2026-10-08T07:00:00+00:00"  # 3 days back from 07:00
    assert run["row_count"] == 1  # one row: lin_auth and its count
    detail = lab["ana"].get(f"/api/schedules/{s['schedule_id']}/runs/{run['run_id']}").json()
    assert detail["columns"] == ["source_id", "n"] and detail["sample"] == [["lin_auth", 7]]
    after = lab["ana"].get("/api/schedules").json()[0]
    assert after["next_run_at"] == "2026-10-12T07:00:00+00:00"
    with sqlite3.connect(lab["db"]) as db:
        (owner,) = db.execute(
            "SELECT user_id FROM audit_log WHERE action = 'schedule.run'"
        ).fetchone()
    assert owner == lab["ids"]["ana"]


def test_rule_schedules_store_matches_and_viewers_without_the_sources_see_restricted(
    lab: dict[str, Any],
) -> None:
    s = schedule(lab["admin"], lab["h"], kind="rule", target_id=WIN_ID, shared=True).json()
    detail = run_now(lab, lab["admin"], s["schedule_id"], lab["h"]).json()
    assert (detail["row_count"], detail["columns"]) == (6, ["event_id", "event_time", "source_id"])
    assert len(detail["sample"]) == 4 and detail["truncated"] and detail["rule_run_id"]
    (seen,) = [
        x for x in lab["ana"].get("/api/schedules").json() if x["schedule_id"] == s["schedule_id"]
    ]
    (r,) = seen["recent"]
    assert r["restricted"] is True and r["row_count"] is None and r["sources_in_scope"] == []
    got = lab["ana"].get(f"/api/schedules/{s['schedule_id']}/runs/{r['run_id']}").json()
    assert got["sample"] == [] and got["columns"] == []


def test_a_changed_saved_search_pauses_until_someone_resumes(lab: dict[str, Any]) -> None:
    sid = schedule(lab["ana"]).json()["schedule_id"]
    changed = {**SEARCH, "sql": SEARCH["sql"].replace("Failed password", "Accepted")}
    assert lab["ana"].put("/api/searches/failed_ssh", json=changed).status_code == 200
    run = run_now(lab, lab["ana"], sid).json()
    assert run["status"] == "paused" and "changed" in run["error"]
    assert run_now(lab, lab["ana"], sid).status_code == 409
    res = lab["ana"].patch(f"/api/schedules/{sid}", json={"paused": False})
    assert res.status_code == 200 and res.json()["paused"] is False
    assert run_now(lab, lab["ana"], sid).json()["status"] == "ok"


def test_losing_a_source_or_the_account_pauses_the_schedule(lab: dict[str, Any]) -> None:
    sid = schedule(lab["ana"]).json()["schedule_id"]
    lab["admin"].put(f"/api/groups/{lab['gid']}/sources", json={"source_ids": []}, headers=lab["h"])
    run = run_now(lab, lab["ana"], sid).json()
    assert run["status"] == "paused" and "lost access to 1 source" in run["error"]
    # Resuming accepts the smaller scope on purpose.
    assert lab["ana"].patch(f"/api/schedules/{sid}", json={"paused": False}).status_code == 200
    lab["admin"].patch(f"/api/users/{lab['ids']['ana']}", json={"disabled": True}, headers=lab["h"])
    s = lab["app"].state.schedules.get(sid)
    run2 = lab["app"].state.schedules.run(s)
    assert run2.status == "paused" and "disabled" in (run2.error or "")


def test_a_disabled_rule_pauses_its_schedule(lab: dict[str, Any]) -> None:
    s = schedule(lab["admin"], lab["h"], kind="rule", target_id=WIN_ID).json()
    lab["admin"].post(
        "/api/rules/enabled", json={"rule_ids": [WIN_ID], "enabled": False}, headers=lab["h"]
    )
    run = run_now(lab, lab["admin"], s["schedule_id"], lab["h"]).json()
    assert run["status"] == "paused" and "disabled" in run["error"]


def test_thresholds_flag_runs_and_only_the_newest_runs_are_kept(lab: dict[str, Any]) -> None:
    s = schedule(
        lab["admin"],
        lab["h"],
        kind="rule",
        target_id=WIN_ID,
        threshold_kind="above",
        threshold_value=5,
    ).json()
    for _ in range(5):
        lab["clock"].now += timedelta(minutes=1)
        detail = run_now(lab, lab["admin"], s["schedule_id"], lab["h"]).json()
    assert detail["flagged"] is True and detail["flag_reason"] == "6 is above 5"
    recent = lab["admin"].get("/api/schedules").json()[0]["recent"]
    assert len(recent) == 3  # keep_runs


def test_who_can_do_what(lab: dict[str, Any]) -> None:
    assert schedule(lab["aud"]).status_code == 403
    private = schedule(lab["ana"]).json()["schedule_id"]
    shared = schedule(lab["ana"], shared=True).json()["schedule_id"]
    bob_sees = {x["schedule_id"] for x in lab["bob"].get("/api/schedules").json()}
    assert bob_sees == {shared}
    assert lab["bob"].patch(f"/api/schedules/{shared}", json={"paused": True}).status_code == 403
    assert lab["bob"].delete(f"/api/schedules/{private}").status_code == 404
    assert (
        lab["admin"]
        .patch(f"/api/schedules/{private}", json={"name": "x"}, headers=lab["h"])
        .status_code
        == 200
    )
    assert lab["ana"].delete(f"/api/schedules/{private}").status_code == 204
    assert schedule(lab["ana"], cron="61 * * * *").status_code == 400
    assert schedule(lab["ana"], cron="0 0 31 2 *").status_code == 400
    assert schedule(lab["ana"], target_id="nope").status_code == 404
    assert schedule(lab["ana"], params={"x": 1}).status_code == 400
    with sqlite3.connect(lab["db"]) as db:
        actions = [
            a for (a,) in db.execute("SELECT action FROM audit_log WHERE action LIKE 'schedule.%'")
        ]
    assert actions.count("schedule.create") == 2 and "schedule.delete" in actions


def test_last_interval_ranges_follow_on_and_change_flags(lab: dict[str, Any]) -> None:
    s = schedule(
        lab["admin"],
        lab["h"],
        kind="rule",
        target_id=WIN_ID,
        cron="hourly",
        lookback_minutes=None,
        threshold_kind="change_pct",
        threshold_value=50,
    ).json()
    svc = lab["app"].state.schedules
    lab["clock"].now = datetime(2026, 10, 10, 13, 0, 5, tzinfo=UTC)
    svc.tick()
    lab["clock"].now = datetime(2026, 10, 10, 14, 0, 5, tzinfo=UTC)
    svc.tick()
    second, first = lab["admin"].get("/api/schedules").json()[0]["recent"]
    assert (first["range_start"], first["range_end"]) == (
        "2026-10-10T12:00:00+00:00", "2026-10-10T13:00:00+00:00"
    )  # fmt: skip
    assert second["range_start"] == first["range_end"]  # no gap, no overlap
    assert not first["flagged"] and not second["flagged"]  # 0 then 0
    assert s["lookback_minutes"] is None


def test_counts_are_not_capped_by_the_sample_and_failed_runs_are_covered_again(
    lab: dict[str, Any],
) -> None:
    body = {**SEARCH, "id": "all_lines", "name": "All lines", "sql": "SELECT event_id FROM events"
            " WHERE coalesce(time, time_observed) BETWEEN {{start}} AND {{end}}"}  # fmt: skip
    assert lab["admin"].post("/api/searches", json=body, headers=lab["h"]).status_code == 201
    s = schedule(
        lab["admin"], lab["h"], target_id="all_lines", lookback_minutes=None, cron="hourly"
    )
    svc = lab["app"].state.schedules
    sched = svc.get(s.json()["schedule_id"])
    lab["clock"].now = datetime(2026, 10, 10, 13, 0, tzinfo=UTC)
    ok = svc.run(sched, lab["clock"].now)
    # Re-run over the fixture day with a wide lookback to see a large count.
    wide = svc.update(sched, lookback_minutes=60 * 48)
    big = svc.run(wide, lab["clock"].now)
    assert (
        big.row_count is not None and big.row_count > 4 and len(big.sample) == 4 and big.truncated
    )
    narrow = svc.update(wide, lookback_minutes=0)
    # A failed run (engine error) must not move the next run's start forward.
    real = svc._engine.run
    svc._engine.run = lambda *a, **k: (_ for _ in ()).throw(QueryTimeoutError("slow"))  # type: ignore[method-assign]  # inject a failure
    lab["clock"].now = datetime(2026, 10, 10, 14, 0, tzinfo=UTC)
    failed = svc.run(narrow, lab["clock"].now)
    svc._engine.run = real  # type: ignore[method-assign]  # restore
    lab["clock"].now = datetime(2026, 10, 10, 15, 0, tzinfo=UTC)
    after = svc.run(narrow, lab["clock"].now)
    assert failed.status == "failed"
    assert after.range_start == big.range_end == ok.range_end  # 13:00, not 14:00


def test_runs_end_before_their_fire_time_by_the_lag(lab: dict[str, Any]) -> None:
    svc = lab["app"].state.schedules
    svc._config = svc._config.model_copy(update={"lag_seconds": 120})
    s = schedule(
        lab["admin"], lab["h"], kind="rule", target_id=WIN_ID, cron="hourly", lookback_minutes=None
    )
    lab["clock"].now = datetime(2026, 10, 10, 13, 0, 3, tzinfo=UTC)
    run = svc.run(svc.get(s.json()["schedule_id"]), datetime(2026, 10, 10, 13, 0, tzinfo=UTC))
    assert (run.range_start, run.range_end) == (
        "2026-10-10T11:58:00+00:00", "2026-10-10T12:58:00+00:00"
    )  # fmt: skip


def test_a_reimported_rule_with_new_content_pauses_its_schedules(
    lab: dict[str, Any], tmp_path: Path
) -> None:
    s = schedule(lab["admin"], lab["h"], kind="rule", target_id=WIN_ID).json()
    rules = tmp_path / "rules"
    (rules / "win.yml").write_text(WIN.replace("4625", "4624"))
    lab["admin"].post("/api/rules/import", json={"path": str(rules)}, headers=lab["h"])
    run = run_now(lab, lab["admin"], s["schedule_id"], lab["h"]).json()
    assert run["status"] == "paused" and "re-imported" in run["error"]
