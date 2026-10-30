"""The daily AI rollup (ADR-0035 Part 1): closed days built from events, read through a
per-query view scoped like `events`, rebuilt on late events and catalog changes, removed
with retention, never visible to user SQL, and giving AI usage the same answer as events."""

import json
import shutil
from datetime import datetime, timedelta
from typing import Any

import pytest
from structlog.testing import capture_logs

from app.ai.rollup import AiRollup
from app.ai.usage import Usage
from app.engine.duckdb import QueryScope
from app.ingest.writer import LakeWriter
from tests.integration.test_schedules import NOW, _lake_rows, make_lab


def _dns(source: str, at: datetime, n: int, host: str = "chatgpt.com") -> list[dict[str, Any]]:
    rows = _lake_rows(source, "dns_bind", at, n)
    return [
        {
            **r,
            "dst_endpoint_hostname": host,
            "src_endpoint_ip": f"10.0.0.{5 + i % 3}",
            "classification": "local_only",
        }
        for i, r in enumerate(rows)
    ]


@pytest.fixture
def lab(tmp_path: Any) -> dict[str, Any]:
    out = make_lab(tmp_path)
    app = out["app"]
    lake = app.state.engine._lake
    for back in (1, 2, 3):  # three closed days
        LakeWriter(lake).write(_dns("dns_a", NOW - timedelta(days=back), 6))
    LakeWriter(lake).write(_dns("dns_a", NOW - timedelta(hours=1), 4))  # today, live
    LakeWriter(lake).write(_dns("dns_b", NOW - timedelta(days=2), 5, host="claude.ai"))
    rollup: AiRollup = app.state.ai_rollup
    rollup._clock = lambda: NOW
    out["rollup"] = rollup
    return out


def week() -> QueryScope:
    return QueryScope(None, NOW - timedelta(days=7), NOW)


def _by_service(usage: Usage, scope: QueryScope) -> dict[str, tuple[int, int, int]]:
    found, _ = usage.services(scope)
    return {u.service.id: (u.events, u.people, u.machines) for u in found}


def test_closed_days_are_built_with_classification_and_today_stays_live(
    lab: dict[str, Any],
) -> None:
    report = lab["rollup"].run()
    # Every closed source day is built, the lab's other sources too (with no AI rows).
    assert report.built == 6 and report.removed == 0
    data = lab["rollup"]._dir
    built = {p.parent.parent.name for p in data.glob("source=*/day=*/part-0.parquet")}
    assert {"source=dns_a", "source=dns_b"} <= built
    assert len(list(data.glob("source=dns_a/day=*/part-0.parquet"))) == 3
    today = NOW.date().isoformat()
    assert not (data / "source=dns_a" / f"day={today}").exists()
    rows = (
        lab["app"]
        .state.engine.run(
            "SELECT DISTINCT classification FROM ai_rollup", QueryScope(None), rollup=True
        )
        .rows
    )
    assert rows == [["local_only"]]  # never upgraded (ADR-0035 row 4)
    assert lab["rollup"].run().built == 0  # nothing stale the second time


def test_ai_usage_gives_the_same_answer_from_the_rollup(lab: dict[str, Any]) -> None:
    app = lab["app"]
    live = _by_service(Usage(app.state.engine, app.state.ai_catalog), week())
    lab["rollup"].run()
    covered = lab["rollup"].covered(week())
    assert {c for c in covered if c.startswith("dns_")} == {
        f"dns_a|{(NOW - timedelta(days=d)).date()}" for d in (1, 2, 3)
    } | {f"dns_b|{(NOW - timedelta(days=2)).date()}"}
    assert _by_service(app.state.ai_usage, week()) == live
    assert live["chatgpt"][0] == 3 * 6 + 4  # closed days from the rollup plus today live


def test_the_rollup_is_scoped_like_events_and_hidden_from_user_sql(
    lab: dict[str, Any],
) -> None:
    lab["rollup"].run()
    engine = lab["app"].state.engine
    only_b = QueryScope(["dns_b"], NOW - timedelta(days=7), NOW)
    rows = engine.run("SELECT DISTINCT source_id FROM ai_rollup", only_b, rollup=True).rows
    assert rows == [["dns_b"]]
    assert all(c.startswith("dns_b|") for c in lab["rollup"].covered(only_b))
    res = lab["admin"].post("/api/query", json={"sql": "SELECT * FROM ai_rollup"}, headers=lab["h"])
    assert res.status_code == 400 and "Unknown table" in res.text


def test_late_events_and_catalog_changes_rebuild_and_retention_removes(
    lab: dict[str, Any],
) -> None:
    rollup = lab["rollup"]
    rollup.run()
    lake = lab["app"].state.engine._lake
    LakeWriter(lake).write(_dns("dns_a", NOW - timedelta(days=2, hours=3), 2))  # late
    assert rollup.run().built == 1
    assert _by_service(lab["app"].state.ai_usage, week())["chatgpt"][0] == 3 * 6 + 4 + 2
    key = rollup.catalog_key()
    lab["app"].state.ai_catalog.domain_table = lambda: [("chatgpt", "chatgpt.com")]
    assert rollup.catalog_key() != key
    assert rollup.run().built == 6  # every closed day rebuilt for the new domains
    day = (NOW - timedelta(days=3)).date().isoformat()
    shutil.rmtree(lake / "source=dns_a" / f"day={day}")
    report = rollup.run()
    assert report.removed == 1
    assert not (rollup._dir / "source=dns_a" / f"day={day}").exists()
    manifest = json.loads(next(rollup._dir.glob("source=dns_a/day=*/_built.json")).read_text())
    assert manifest["catalog"] == rollup.catalog_key()


def test_each_closed_day_records_what_was_first_seen_there(lab: dict[str, Any]) -> None:
    """F63: the first-seen index lives in the day manifests and is scoped by source."""
    lab["rollup"].run()
    usage: Usage = lab["app"].state.ai_usage
    everything = usage.first_seen(None)
    assert everything["service:chatgpt"].date() == (NOW - timedelta(days=3)).date()
    assert everything["service:claude"].date() == (NOW - timedelta(days=2)).date()
    only_b = usage.first_seen(["dns_b"])
    assert "service:claude" in only_b and "service:chatgpt" not in only_b


def test_days_built_before_the_index_get_it_without_a_rebuild(lab: dict[str, Any]) -> None:
    rollup = lab["rollup"]
    rollup.run()
    for m in rollup._dir.glob("source=*/day=*/_built.json"):
        body = json.loads(m.read_text())
        del body["first"]
        m.write_text(json.dumps(body))
    assert lab["app"].state.ai_usage.first_seen(None) == {}
    assert rollup.covered(week())  # still read from the rollup meanwhile
    report = rollup.run()
    assert report.built == 0 and report.indexed == 6
    assert "service:chatgpt" in lab["app"].state.ai_usage.first_seen(None)


def test_new_in_24_hours_knows_use_older_than_the_window(lab: dict[str, Any]) -> None:
    """A service last seen 40 days ago is not new today: the index remembers it, so the
    summary never scans 30 days of events to find out (F63)."""
    app, a = lab["app"], lab["admin"]
    lake = app.state.engine._lake
    LakeWriter(lake).write(_dns("dns_a", NOW - timedelta(days=40), 3, host="gemini.google.com"))
    LakeWriter(lake).write(_dns("dns_a", NOW - timedelta(hours=2), 3, host="gemini.google.com"))
    app.state.ai_watch._clock = lambda: NOW
    before = {n["id"] for n in a.get("/api/ai/watch/summary").json()["new"]}
    assert "gemini" in before  # not seen in the window, and no index yet
    lab["rollup"].run()
    summary = a.get("/api/ai/watch/summary").json()
    assert "gemini" not in {n["id"] for n in summary["new"]}
    # Top services show when a service was first seen at all, not the start of the window.
    (top,) = [t for t in summary["top"] if t["service_id"] == "gemini"]
    assert top["first_seen"][:10] == (NOW - timedelta(days=40)).date().isoformat()


def test_a_range_query_reads_only_its_days_and_not_the_skipped_ones(lab: dict[str, Any]) -> None:
    engine = lab["app"].state.engine
    day = (NOW - timedelta(days=2)).date().isoformat()
    # A broken file in a day outside the range would fail the query if it were opened.
    old = engine._lake / "source=dns_a" / "day=2026-01-01"
    old.mkdir(parents=True)
    (old / "part-0.parquet").write_bytes(b"not parquet")
    sql = "SELECT count(*) FROM events WHERE source_id = 'dns_a'"
    assert engine.run(sql, week()).rows == [[22]]
    assert engine.run(sql, week(), skip_days=[f"dns_a|{day}"]).rows == [[16]]


def _with_user_id(app: Any) -> datetime:
    day = NOW - timedelta(days=2)
    uid = [
        {**r, "src_endpoint_ip": "10.0.0.5", "actor_user_name": "alice", "activity_id": 1}
        for r in _lake_rows("userid", "paloalto_userid", day - timedelta(hours=1), 1)
    ]
    LakeWriter(app.state.engine._lake).write(uid)
    return day


def test_people_on_closed_days_come_from_the_days_identity_file(lab: dict[str, Any]) -> None:
    """Who had an address on a closed day comes from the rollup's small identity file,
    never from that day's events: people were 0 after F63, and reading the events instead
    (#276) ran out of memory on a busy install (owner, 2026-10-29)."""
    app = lab["app"]
    day = _with_user_id(app)
    live = _by_service(Usage(app.state.engine, app.state.ai_catalog), week())
    assert live["chatgpt"][1] == 1  # alice, from User-ID
    lab["rollup"].run()
    covered = lab["rollup"].covered(week())
    assert f"userid|{day.date()}" in covered and f"dns_a|{day.date()}" in covered
    assert lab["rollup"].pending(covered) == 0
    assert _by_service(app.state.ai_usage, week()) == live


def test_days_built_before_the_identity_file_load_without_people_then_recheck(
    lab: dict[str, Any],
) -> None:
    app = lab["app"]
    _with_user_id(app)
    rollup = lab["rollup"]
    rollup.run()
    for f in rollup._dir.glob("source=*/day=*/ident.parquet"):
        f.unlink()  # as built by an earlier version
    covered = rollup.covered(week())
    assert rollup.pending(covered) == len(covered)
    # The page loads (no events opened for those days), without people meanwhile.
    found = _by_service(app.state.ai_usage, week())
    assert found["chatgpt"][1] == 0
    with capture_logs() as logs:
        assert rollup.recheck(budget_s=0.0) == 1  # at least one day per step
        assert rollup.recheck() == len(covered) - 1
        assert rollup.recheck() == 0
    events = [e["event"] for e in logs]
    assert events[0] == "rollup.recheck.started" and events[-1] == "rollup.recheck.finished"
    assert events.count("rollup.recheck.day") == len(covered)
    assert all(e["log_level"] == "info" for e in logs)
    assert rollup.pending(rollup.covered(week())) == 0
    assert _by_service(app.state.ai_usage, week())["chatgpt"][1] == 1
