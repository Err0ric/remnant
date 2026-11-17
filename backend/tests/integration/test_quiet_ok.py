"""Quiet is normal for up to N days on push sources (D260, owner 2026-11-14): the setting,
who may change it, its audit row, and every surface that reads a source's condition."""

import json
import sqlite3
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ingest.watcher import SourceStatus
from app.ingest.writer import LakeWriter
from app.search.gaps import Gap
from app.search.overview import SourceVolume
from tests.integration.test_schedules import NOW, _lake_rows, make_lab


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    out = make_lab(tmp_path)
    out["app"].state.overview._clock = out["clock"]
    return out


def _add(lab: dict[str, Any], source_id: str, **body: Any) -> dict[str, Any]:
    base = {"source_id": source_id, "format": "json", "kind": "otlp"}
    res = lab["admin"].post("/api/sources", json={**base, **body}, headers=lab["h"])
    assert res.status_code == 201, res.text
    ingest = lab["app"].state.ingest
    with ingest._lock:  # read by ingest, nothing spooled
        ingest._status[source_id] = SourceStatus(last_pass_at=NOW)
    out: dict[str, Any] = res.json()
    return out


def _sent(lab: dict[str, Any], source_id: str, days_ago: float) -> None:
    lake = lab["app"].state.engine._lake
    LakeWriter(lake).write(_lake_rows(source_id, "generic_json", NOW - timedelta(days_ago), 2))


def _patch(lab: dict[str, Any], source_id: str, days: int | None, **kw: Any) -> Any:
    client = kw.pop("client", lab["admin"])
    headers = kw.pop("headers", lab["h"])
    return client.patch(f"/api/sources/{source_id}", json={"quiet_ok_days": days}, headers=headers)


def _overview(lab: dict[str, Any], who: str = "admin") -> dict[str, Any]:
    lab["app"].state.overview._cache.clear()
    lab["app"].state.overview._count_cache.clear()
    out: dict[str, Any] = lab[who].get("/api/overview").json()
    return out


def _rows(o: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s["source_id"]: s for s in o["sources"]}


def _audit(lab: dict[str, Any], action: str) -> list[dict[str, Any]]:
    with sqlite3.connect(lab["db"]) as db:
        rows = db.execute("SELECT detail FROM audit_log WHERE action = ?", (action,)).fetchall()
    return [json.loads(r[0]) for r in rows]


def test_claude_code_sources_start_at_seven_days_and_others_start_off(
    lab: dict[str, Any],
) -> None:
    assert _add(lab, "claude_hooks", sender="claude")["quiet_ok_days"] == 7
    assert _add(lab, "otel_collector", sender="collector")["quiet_ok_days"] is None
    assert _add(lab, "claude_otel", sender="claude", quiet_ok_days=None)["quiet_ok_days"] is None
    listed = {s["source_id"]: s for s in lab["admin"].get("/api/sources").json()}
    assert listed["claude_hooks"]["quiet_ok_days"] == 7
    assert listed["lin_auth"]["quiet_ok_days"] is None  # a file source: never set


def test_silence_inside_the_days_is_idle_and_healthy_and_past_them_is_quiet(
    lab: dict[str, Any],
) -> None:
    _add(lab, "claude_hooks", sender="claude")  # 7 days
    _add(lab, "otel_collector", sender="collector")  # unmarked
    _add(lab, "claude_never", sender="claude")  # marked, never sent
    _sent(lab, "claude_hooks", 2)
    _sent(lab, "otel_collector", 2)
    o = _overview(lab)
    rows = _rows(o)
    hooks, other, never = rows["claude_hooks"], rows["otel_collector"], rows["claude_never"]
    assert (hooks["condition"], hooks["idle"], hooks["quiet_ok"]) == ("healthy", True, True)
    assert hooks["quiet_ok_days"] == 7
    assert (other["condition"], other["idle"]) == ("quiet", False)
    assert (never["condition"], never["idle"]) == ("quiet", False)  # never sent: still raised
    summary = o["source_summary"]
    quiet = [q["source_id"] for q in summary["quiet"]]
    assert "claude_hooks" not in quiet and "otel_collector" in quiet and "claude_never" in quiet
    assert summary["idle"] == 1
    assert (summary["longest_wait"] or {}).get("source_id") != "claude_hooks"
    # The rail's Health dot counts the same.
    count = lab["admin"].get("/api/health/count").json()
    wrong = sum(1 for s in o["sources"] if s["condition"] not in ("healthy", "paused"))
    assert (count["total"], count["not_healthy"]) == (summary["total"], wrong)
    assert hooks["problem"] is None  # held inside its days (D262): never a source problem

    # A week on, nine days after it last sent: past its seven days, quiet as before.
    lab["clock"].now = NOW + timedelta(days=7)
    rows = _rows(_overview(lab))
    assert (rows["claude_hooks"]["condition"], rows["claude_hooks"]["idle"]) == ("quiet", False)


def test_a_longer_period_finds_the_last_event_beyond_seven_days(lab: dict[str, Any]) -> None:
    _add(lab, "claude_hooks", sender="claude", quiet_ok_days=30)
    _sent(lab, "claude_hooks", 12)
    rows = _rows(_overview(lab))
    assert rows["claude_hooks"]["condition"] == "healthy" and rows["claude_hooks"]["idle"]
    assert rows["claude_hooks"]["last_event_at"] == (NOW - timedelta(days=12)).isoformat()


def test_an_error_still_counts_on_a_marked_source(lab: dict[str, Any]) -> None:
    _add(lab, "claude_hooks", sender="claude")
    _sent(lab, "claude_hooks", 1)
    ingest = lab["app"].state.ingest
    with ingest._lock:
        ingest._status["claude_hooks"] = SourceStatus(last_pass_at=NOW, error="Spool is full")
    rows = _rows(_overview(lab))
    assert (rows["claude_hooks"]["condition"], rows["claude_hooks"]["idle"]) == ("error", False)


def test_an_admin_changes_it_and_it_is_audited(lab: dict[str, Any]) -> None:
    _add(lab, "otel_collector", sender="collector")
    res = _patch(lab, "otel_collector", 3)
    assert res.status_code == 200, res.text
    assert res.json()["quiet_ok_days"] == 3
    assert _patch(lab, "otel_collector", None).json()["quiet_ok_days"] is None
    assert _audit(lab, "source.quiet_ok_change") == [
        {"source_id": "otel_collector", "from": None, "to": 3},
        {"source_id": "otel_collector", "from": 3, "to": None},
    ]


def test_only_offered_days_on_push_sources_and_never_the_built_in(lab: dict[str, Any]) -> None:
    _add(lab, "otel_collector", sender="collector")
    assert _patch(lab, "otel_collector", 5).status_code == 422  # not one of 1, 3, 7, 14, 30
    file_source = _patch(lab, "lin_auth", 7)
    assert file_source.status_code == 400 and "OTLP and syslog" in file_source.text
    assert _patch(lab, "nope", 7).status_code == 404
    lab["app"].state.server_events.ensure_source()
    assert _patch(lab, "server_events", 7).status_code == 400
    bad = lab["admin"].post(
        "/api/sources",
        json={"source_id": "x", "format": "syslog", "path": "/", "quiet_ok_days": 7},
        headers=lab["h"],
    )
    assert bad.status_code == 422
    assert _audit(lab, "source.quiet_ok_change") == []


def test_analysts_and_auditors_cannot_change_it(lab: dict[str, Any]) -> None:
    _add(lab, "otel_collector", sender="collector")
    for who in ("ana", "aud"):
        assert _patch(lab, "otel_collector", 7, client=lab[who], headers={}).status_code == 403
    assert _audit(lab, "source.quiet_ok_change") == []


def test_a_change_needs_the_csrf_token(lab: dict[str, Any]) -> None:
    _add(lab, "otel_collector", sender="collector")
    assert _patch(lab, "otel_collector", 7, headers={}).status_code == 403
    assert _audit(lab, "source.quiet_ok_change") == []


@pytest.mark.real_auth
def test_a_change_needs_a_sign_in(lab: dict[str, Any]) -> None:
    stranger = TestClient(lab["app"])
    assert _patch(lab, "lin_auth", 7, client=stranger, headers={}).status_code == 401


def _add_listener(lab: dict[str, Any], source_id: str = "fw_syslog") -> dict[str, Any]:
    """A syslog listener source; the test app runs no listeners, so the port is only stored."""
    body: dict[str, Any] = {"source_id": source_id, "kind": "syslog", "format": "syslog"}
    body["syslog"] = {"protocol": "udp", "port": 5514}
    res = lab["admin"].post("/api/sources", json=body, headers=lab["h"])
    assert res.status_code == 201, res.text
    ingest = lab["app"].state.ingest
    with ingest._lock:
        ingest._status[source_id] = SourceStatus(last_pass_at=NOW)
    out: dict[str, Any] = res.json()
    return out


def test_a_syslog_listener_source_takes_it_too(lab: dict[str, Any]) -> None:
    assert _add_listener(lab)["quiet_ok_days"] is None  # starts off, as other push sources
    _sent(lab, "fw_syslog", 2)
    rows = _rows(_overview(lab))
    assert rows["fw_syslog"]["condition"] == "quiet"
    res = _patch(lab, "fw_syslog", 14)
    assert res.status_code == 200, res.text
    listed = {s["source_id"]: s for s in lab["admin"].get("/api/sources").json()}
    assert listed["fw_syslog"]["quiet_ok_days"] == 14
    rows = _rows(_overview(lab))
    assert (rows["fw_syslog"]["condition"], rows["fw_syslog"]["idle"]) == ("healthy", True)
    assert _audit(lab, "source.quiet_ok_change") == [
        {"source_id": "fw_syslog", "from": None, "to": 14}
    ]


def test_a_change_shows_on_the_next_read_without_waiting_for_the_caches(
    lab: dict[str, Any],
) -> None:
    _add(lab, "otel_collector", sender="collector")
    _sent(lab, "otel_collector", 2)

    def judged() -> tuple[str, int]:
        o = lab["admin"].get("/api/overview").json()
        row = _rows(o)["otel_collector"]
        return row["condition"], lab["admin"].get("/api/health/count").json()["not_healthy"]

    before, wrong = judged()  # both answers are cached now (60 s and 300 s)
    assert before == "quiet"
    assert _patch(lab, "otel_collector", 7).status_code == 200
    after, wrong_after = judged()  # no cache cleared by hand
    assert after == "healthy" and wrong_after == wrong - 1


# --- How long a source has been quiet: from its newest dated event, not its last receipt ---


def _dated(
    lab: dict[str, Any], source_id: str, dated_ago: timedelta, received_ago: timedelta
) -> None:
    """Events dated `dated_ago` that arrived `received_ago` (a queue or an import)."""
    from app.ingest.normalizer import Normalizer, SourceSpec
    from app.ingest.records import DecodedLine

    received = NOW - received_ago
    norm = Normalizer(SourceSpec(source_id=source_id, format="json"), clock=lambda: received)
    when = (NOW - dated_ago).isoformat()
    row = norm.normalize(DecodedLine(f'{{"time": "{when}", "message": "x"}}', False, False))
    assert row is not None
    LakeWriter(lab["app"].state.engine._lake).write([{**row, "template_id": "generic_json"}])


MIN = timedelta(minutes=1)
DURATION_CASES = [
    # (case, marked days, dated ago, received ago, condition, idle, quiet-from ago)
    ("old and received long ago, unmarked", None, timedelta(days=2), timedelta(days=2),
     "quiet", False, timedelta(days=2)),
    ("old and received long ago, marked", 7, timedelta(days=2), timedelta(days=2),
     "healthy", True, timedelta(days=2)),
    ("old but received just now, unmarked", None, timedelta(days=2), MIN,
     "quiet", False, timedelta(days=2)),
    ("old but received just now, marked", 7, timedelta(days=2), MIN,
     "healthy", True, timedelta(days=2)),
    ("old but received just now, past a 1-day mark", 1, timedelta(days=2), MIN,
     "quiet", False, timedelta(days=2)),
    ("recent, unmarked", None, timedelta(hours=1), timedelta(hours=1),
     "healthy", False, timedelta(hours=1)),
    ("recent, marked", 7, timedelta(hours=1), timedelta(hours=1),
     "healthy", False, timedelta(hours=1)),
    ("never sent, unmarked", None, None, None, "quiet", False, None),
    ("never sent, marked", 7, None, None, "quiet", False, None),
]  # fmt: skip


@pytest.mark.parametrize(
    ("days", "dated", "received", "cond", "is_idle", "quiet_from"),
    [c[1:] for c in DURATION_CASES],
    ids=[c[0] for c in DURATION_CASES],
)
def test_quiet_and_idle_count_from_the_newest_dated_event(
    lab: dict[str, Any],
    days: int | None,
    dated: timedelta | None,
    received: timedelta | None,
    cond: str,
    is_idle: bool,
    quiet_from: timedelta | None,
) -> None:
    _add(lab, "otel_collector", sender="collector", quiet_ok_days=days)
    if dated is not None and received is not None:
        _dated(lab, "otel_collector", dated, received)
    o = _overview(lab)
    row = _rows(o)["otel_collector"]
    assert (row["condition"], row["idle"]) == (cond, is_idle)
    expect = (NOW - quiet_from).isoformat() if quiet_from is not None else None
    assert row["newest_event_at"] == expect
    # "Last received" stays when a record last arrived.
    assert row["last_event_at"] == ((NOW - received).isoformat() if received else None)
    waits = {q["source_id"]: q["last_event_at"] for q in o["source_summary"]["quiet"]}
    if cond == "quiet":
        assert waits["otel_collector"] == expect  # "1 quiet: otel_collector 2 d"


def _firing(
    lab: dict[str, Any], monkeypatch: pytest.MonkeyPatch, gap_hours: dict[str, bool]
) -> None:
    """Each source in `gap_hours` gets a firing quiet watch, and gap hours on its 24-hour
    chart (True) or none (False): the two inputs of the red rule, set on purpose."""
    since = (NOW - timedelta(hours=3)).isoformat()
    watches = [SimpleNamespace(source_id=s, state="quiet", quiet_since=since) for s in gap_hours]
    monkeypatch.setattr(lab["app"].state.quiet, "all", lambda: watches)
    gap = Gap(since, None, 3, True, False)

    def with_gaps(o: Any) -> Any:
        have = {v.source_id for v in o.volume}
        volume = [
            replace(v, gaps=[gap] if gap_hours[v.source_id] else [])
            if v.source_id in gap_hours
            else v
            for v in o.volume
        ] + [
            SourceVolume(s, [0] * 24, [None] * 24, [""] * 24, 0, [gap] if g else [])
            for s, g in gap_hours.items()
            if s not in have
        ]
        return replace(o, volume=volume)

    svc = lab["app"].state.overview
    get, count = svc.get, svc.for_count
    monkeypatch.setattr(svc, "get", lambda user: (with_gaps(get(user)[0]), True))
    monkeypatch.setattr(svc, "for_count", lambda user: with_gaps(count(user)))


def test_the_dot_is_red_only_for_what_health_draws_red(
    lab: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Designer check of 637: unhealthy (red on the rail) is a firing quiet watch WITH gap
    hours on the chart; without them Health draws the source greyed, so it needs attention.
    A source marked "Quiet is normal" inside its days shows no gap hours (D262), so even with
    an alert that already fired it is never red."""
    _add(lab, "otel_gapped", sender="collector")
    _add(lab, "otel_only_quiet", sender="collector")
    _add(lab, "claude_hooks", sender="claude")  # Quiet is normal for 7 days
    for s in ("otel_gapped", "otel_only_quiet", "claude_hooks"):
        _sent(lab, s, 2)
    _firing(lab, monkeypatch, {"otel_gapped": True, "otel_only_quiet": False, "claude_hooks": True})
    rows = _rows(_overview(lab))
    gapped, only_quiet, hooks = (
        rows["otel_gapped"],
        rows["otel_only_quiet"],
        rows["claude_hooks"],
    )
    assert (gapped["condition"], gapped["problem"]) == ("quiet", "unhealthy")
    assert (only_quiet["condition"], only_quiet["problem"]) == ("quiet", "attention")
    assert hooks["quiet_ok"] is True and hooks["quiet_since"]
    assert (hooks["condition"], hooks["problem"]) == ("quiet", "attention")
    count = lab["admin"].get("/api/health/count").json()
    assert count["unhealthy"] == sum(1 for r in rows.values() if r["problem"] == "unhealthy")
    assert count["unhealthy"] >= 1
