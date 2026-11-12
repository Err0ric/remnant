"""A pause or failure that stops detection is never silent (D33 as amended, owner
2026-11-10): one helper, used by schedule self-pauses, sources and connectors, AI Watch
steps, intel feeds, and integrity checks. With no targets of its own, every alert target
hears about it; a blip inside the grace sends nothing; it stops and runs again once each."""

import json
import time
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.alerts.stops import FLAP_WINDOW, GRACE, DetectionStops
from app.enrich.updater import INTEL_GRACE
from app.ingest import otlp
from tests.integration.test_schedules import NOW, WIN_ID, make_lab, run_now, schedule


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> Any:
        return self.now


@pytest.fixture
def lab(tmp_path: Path) -> Any:
    out = make_lab(tmp_path)
    app = out["app"]
    out["targets"] = [
        out["admin"]
        .post(
            "/api/alert-targets",
            json={"name": name, "kind": "webhook", "url": f"http://127.0.0.1:9/hook/{name}"},
            headers=out["h"],
        )
        .json()["target_id"]
        for name in ("One", "Two")
    ]
    out["at"] = clock = Clock()
    stops: DetectionStops = app.state.detection_stops
    stops._clock = clock
    app.state.ingest._clock = clock
    return out


def sent(lab: dict[str, Any]) -> list[tuple[str, str, str]]:
    """(kind, title, target) for every message queued, oldest first."""
    with lab["app"].state.meta.connect() as con:
        rows = con.execute(
            "SELECT alert, target_id FROM alert_deliveries ORDER BY created_at, target_id"
        ).fetchall()
    return [(json.loads(a)["kind"], json.loads(a)["title"], t) for a, t in rows]


def everyone(lab: dict[str, Any], kind: str, title: str) -> list[tuple[str, str, str]]:
    return [(kind, title, t) for t in sorted(lab["targets"])]


def test_the_helper_waits_out_the_grace_then_sends_once_each_way(lab: dict[str, Any]) -> None:
    stops: DetectionStops = lab["app"].state.detection_stops
    stops.failing("x:1", "Thing", "broken")
    lab["at"].now += GRACE - timedelta(minutes=1)
    stops.working("x:1")  # a blip: nothing was sent, nothing to clear
    assert sent(lab) == []
    stops.failing("x:1", "Thing", "broken")
    lab["at"].now += GRACE
    stops.failing("x:1", "Thing", "broken")
    stops.failing("x:1", "Thing", "still broken")
    assert sent(lab) == everyone(lab, "stopped", "Thing")
    stops.working("x:1")
    stops.working("x:1")
    assert sent(lab)[2:] == everyone(lab, "stopped_cleared", "Thing")
    assert stops.recipients(["only"]) == ["only"]
    with lab["app"].state.meta.connect() as con:
        actions = [r[0] for r in con.execute("SELECT action FROM audit_log")]
    assert actions.count("detection.stopped") == 1 and actions.count("detection.resumed") == 1


def test_a_schedule_that_pauses_itself_with_no_targets_tells_every_target(
    lab: dict[str, Any],
) -> None:
    s = schedule(lab["admin"], lab["h"], kind="rule", target_id=WIN_ID).json()
    assert s["target_ids"] == []
    lab["admin"].post(
        "/api/rules/enabled", json={"rule_ids": [WIN_ID], "enabled": False}, headers=lab["h"]
    )
    run_now(lab, lab["admin"], s["schedule_id"], lab["h"])
    assert sent(lab) == everyone(lab, "pause", s["name"])


def test_a_source_that_stops_reading_is_never_silent(lab: dict[str, Any]) -> None:
    ingest = lab["app"].state.ingest
    ingest.listener_errors = lambda: {"win_dc": "Port 514 is in use"}
    ingest.run_once()
    lab["at"].now += GRACE
    ingest.run_once()
    assert sent(lab) == everyone(lab, "stopped", "Source win_dc")
    ingest.listener_errors = lambda: {}
    ingest.run_once()
    assert sent(lab)[2:] == everyone(lab, "stopped_cleared", "Source win_dc")


def test_a_failing_ai_watch_step_is_never_silent(lab: dict[str, Any]) -> None:
    watch = lab["app"].state.ai_watch

    def boom() -> int:
        raise RuntimeError("engine gone")

    watch._steps = lambda: [("events", boom)]
    watch.tick()
    lab["at"].now += GRACE
    watch.tick()
    assert sent(lab) == everyone(lab, "stopped", "AI Watch: events")
    watch._steps = lambda: [("events", lambda: 0)]
    watch.tick()
    assert [k for k, _, _ in sent(lab)].count("stopped_cleared") == 2


def test_a_threat_feed_that_cannot_update_for_a_day_is_never_silent(lab: dict[str, Any]) -> None:
    updater = lab["app"].state.feed_updater
    updater.update("intel_threatfox", None)  # no Auth-Key: fails
    lab["at"].now += INTEL_GRACE - timedelta(hours=1)
    updater.update("intel_threatfox", None)
    assert sent(lab) == []  # an hourly list a few hours stale is not yet a gap
    lab["at"].now += timedelta(hours=1)
    updater.update("intel_threatfox", None)
    assert [k for k, _, _ in sent(lab)] == ["stopped", "stopped"]
    assert "Threat feed" in sent(lab)[0][1]


def test_a_failed_integrity_check_with_no_targets_tells_every_target(
    lab: dict[str, Any],
) -> None:
    failure = SimpleNamespace(kind="file_changed", path="lake/a.parquet")
    result = SimpleNamespace(status="failed", failures=[failure], checked_at=NOW.isoformat())
    lab["app"].state.integrity_service._notify(result, 1, "sig")
    assert sent(lab) == everyone(lab, "integrity_failed", "Log integrity")


def test_no_new_events_lag_and_quiet_periods_never_start_the_clock(lab: dict[str, Any]) -> None:
    """Guard 1 (owner, 2026-11-10): only errors count."""
    ingest = lab["app"].state.ingest
    for _ in range(9):  # two hours of passes with nothing new
        ingest.run_once()
        with ingest._lock:  # a connector far behind, with warnings, is still not an error
            for sid, st in ingest._status.items():
                ingest._status[sid] = replace(st, behind_s=7200.0, warnings=("slow",))
        lab["at"].now += GRACE
    assert sent(lab) == []
    with lab["app"].state.meta.connect() as con:
        assert tuple(con.execute("SELECT count(*) FROM detection_stops").fetchone()) == (0,)


def test_a_full_spool_is_an_error_that_starts_the_clock(
    lab: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    ingest = lab["app"].state.ingest
    ingest.run_once()
    monkeypatch.setitem(otlp._full_at, "win_dc", time.monotonic())
    assert ingest.status()["win_dc"].error == "Spool full: new messages are being refused"
    ingest.run_once()
    lab["at"].now += GRACE
    ingest.run_once()
    assert sent(lab) == everyone(lab, "stopped", "Source win_dc")


def _cycle(
    lab: dict[str, Any], stops: DetectionStops, up: timedelta = timedelta(minutes=5)
) -> None:
    """Down for the grace, then up for `up`."""
    stops.failing("x:1", "Thing", "broken")
    lab["at"].now += GRACE
    stops.failing("x:1", "Thing", "broken")
    stops.working("x:1")
    lab["at"].now += up


def kinds(lab: dict[str, Any]) -> list[str]:
    return [k for k, _, t in sent(lab) if t == min(lab["targets"])]


def test_flapping_sends_one_pair_then_one_flap_message_until_stable(lab: dict[str, Any]) -> None:
    """Guard 2 (owner, 2026-11-10): at most one stopped and running-again pair an hour."""
    stops: DetectionStops = lab["app"].state.detection_stops
    _cycle(lab, stops)
    assert kinds(lab) == ["stopped", "stopped_cleared"]
    _cycle(lab, stops)  # a second stop inside the hour: the flap message instead
    assert kinds(lab)[2:] == ["stopped_flapping"]
    with lab["app"].state.meta.connect() as con:
        (alert,) = con.execute(
            "SELECT alert FROM alert_deliveries WHERE alert LIKE '%flapping%' LIMIT 1"
        ).fetchone()
    assert "Still flapping: 2 failures in the last hour" in json.loads(alert)["detail"]
    for _ in range(4):
        _cycle(lab, stops)
    assert kinds(lab)[3:] == []  # nothing more while it flaps
    # Up since the last cycle, 5 minutes ago.
    lab["at"].now += FLAP_WINDOW - timedelta(minutes=6)
    stops.working("x:1")
    assert kinds(lab)[3:] == []  # not yet stable for an hour
    lab["at"].now += timedelta(minutes=1)
    stops.working("x:1")
    stops.working("x:1")
    assert kinds(lab)[3:] == ["stopped_cleared"]  # settled: one message
    lab["at"].now += FLAP_WINDOW
    _cycle(lab, stops)  # an hour after that pair: a normal pair again
    assert kinds(lab)[4:] == ["stopped", "stopped_cleared"]


def test_flapping_that_settles_down_says_stopped_once(lab: dict[str, Any]) -> None:
    stops: DetectionStops = lab["app"].state.detection_stops
    _cycle(lab, stops)
    _cycle(lab, stops)
    stops.failing("x:1", "Thing", "broken")
    for _ in range(4):
        lab["at"].now += GRACE
        stops.failing("x:1", "Thing", "broken")
    stops.failing("x:1", "Thing", "broken")
    assert kinds(lab) == ["stopped", "stopped_cleared", "stopped_flapping", "stopped"]
