"""ADR-0036: live mode follows new event rows of a row query over server-sent events, on
the caller's own view, with per-user limits, a time limit, access checks, and one audit
row at start and one at stop."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.core.errors import ConflictError, QueryRejectedError
from app.ingest.writer import LakeWriter
from app.search import live as lv
from tests.integration.test_dashboards import audit
from tests.integration.test_m365_consents import _row
from tests.integration.test_schedules import make_lab

SQL = "SELECT time, source_id, message, event_id FROM events WHERE source_id = 'lin_auth'"


@pytest.mark.parametrize(
    ("sql", "what"),
    [
        ("SELECT source_id, count(*) FROM events GROUP BY 1", "GROUP BY"),
        ("SELECT count(*) FROM events", "aggregate"),
        ("SELECT DISTINCT source_id FROM events", "DISTINCT"),
        ("SELECT message FROM events LIMIT 5", "LIMIT"),
        ("SELECT message FROM events UNION SELECT message FROM events", "UNION"),
        ("WITH x AS (SELECT * FROM events) SELECT * FROM x", "WITH"),
        ("SELECT message, row_number() OVER () FROM events", "window"),
        ("SELECT message FROM events WHERE {{ip}} = src_endpoint_ip", "parameters"),
    ],
)
def test_only_row_queries_go_live(sql: str, what: str) -> None:
    with pytest.raises(QueryRejectedError, match=what):
        lv.live_sql(sql)


def test_a_row_query_gets_the_cursor() -> None:
    out = lv.live_sql(SQL + " ORDER BY time DESC")
    assert "_live_t" in out and "_live_id" in out and "$since" in out
    assert "ORDER BY time_observed" in out and "LIMIT 1001" in out


def _events(engine: Any, n: int, source: str = "lin_auth") -> None:
    """n events that arrive a minute from now, so the stream (cursor: now) picks them up."""
    later = datetime.now(UTC) + timedelta(minutes=1)
    rows = []
    for i in range(n):
        r = _row("m365_signin", "successful sign-in", source)
        r["time_observed"] = later + timedelta(milliseconds=i)
        r["time"] = datetime.now(UTC)
        rows.append(r)
    LakeWriter(engine._lake).write(rows)


def _read(res: Any) -> list[tuple[str, Any]]:
    out, event = [], ""
    for line in res.iter_lines():
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: "):
            out.append((event, json.loads(line[6:])))
    return out


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    out = make_lab(tmp_path)
    reg: lv.LiveRegistry = out["app"].state.live
    reg.poll_s = 0.05
    reg.limit_override_s = 0.6
    return out


def test_live_streams_new_rows_lag_and_ends_on_the_time_limit(lab: dict[str, Any]) -> None:
    engine = lab["app"].state.engine
    _events(engine, 3)
    _events(engine, 2, source="win_dc")  # ana cannot read it
    with lab["ana"].stream("GET", "/api/search/live", params={"q": SQL}) as res:
        assert res.status_code == 200
        assert res.headers["x-accel-buffering"] == "no"
        got = _read(res)
    kinds = [k for k, _ in got]
    assert kinds[0] == "start" and kinds[-1] == "end" and "lag" in kinds
    rows = [r for k, d in got if k == "rows" for r in d["rows"]]
    assert len(rows) == 3  # once each, never the Windows rows
    assert got[-1][1]["reason"] == "time_limit"
    lag = next(d for k, d in got if k == "lag")["sources"]
    assert {s["source"] for s in lag} <= {"lin_auth"}
    start = audit(lab, "search.live_start")
    stop = audit(lab, "search.live_stop")
    assert start and start[-1]["sql"] == SQL
    assert stop and stop[-1]["reason"] == "time limit" and stop[-1]["events_sent"] == 3
    assert lab["app"].state.live.mine(lab["ids"]["ana"]) == []  # closed


def test_two_streams_per_user_and_a_third_is_refused_by_name(lab: dict[str, Any]) -> None:
    reg: lv.LiveRegistry = lab["app"].state.live
    now = datetime.now(UTC)
    reg.open(lab["ids"]["ana"], "cli", now)
    reg.open(lab["ids"]["ana"], "browser", now)
    with pytest.raises(ConflictError, match="tail -f since"):
        reg.open(lab["ids"]["ana"], "browser", now)
    res = lab["ana"].get("/api/search/live", params={"q": SQL})
    assert res.status_code == 409 and "2 live searches open" in res.text
    mine = lab["ana"].get("/api/search/live/streams").json()
    assert [s["client"] for s in mine] == ["cli", "browser"]
    assert lab["bob"].delete(f"/api/search/live/streams/{mine[0]['stream_id']}").status_code == 404


def test_a_group_query_is_refused_before_any_stream(lab: dict[str, Any]) -> None:
    res = lab["ana"].get("/api/search/live", params={"q": "SELECT count(*) FROM events"})
    assert res.status_code == 400 and "Live works on event rows" in res.text
    assert lab["app"].state.live.mine(lab["ids"]["ana"]) == []


def test_access_change_ends_the_stream(lab: dict[str, Any], monkeypatch: Any) -> None:
    import app.api.live as api_live

    calls = {"n": 0}
    real = api_live.permitted_sources

    def shrinking(meta: Any, user: Any) -> Any:
        calls["n"] += 1
        return real(meta, user) if calls["n"] == 1 else []

    monkeypatch.setattr(api_live, "permitted_sources", shrinking)
    with lab["ana"].stream("GET", "/api/search/live", params={"q": SQL}) as res:
        got = _read(res)
    assert got[-1][1]["reason"] == "access"
    assert audit(lab, "search.live_stop")[-1]["reason"] == "access changed"


def test_live_limit_is_an_audited_admin_setting(lab: dict[str, Any]) -> None:
    assert lab["ana"].put("/api/settings/live", json={"minutes": 5}).status_code == 403
    res = lab["admin"].put("/api/settings/live", json={"minutes": 45}, headers=lab["h"])
    assert res.json() == {"minutes": 45}
    assert audit(lab, "settings.live_limit")[-1] == {"from": 30, "to": 45}


def test_resume_sends_what_arrived_while_paused_up_to_1000(lab: dict[str, Any]) -> None:
    engine = lab["app"].state.engine
    _events(engine, 1_200)
    since = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    with lab["ana"].stream("GET", "/api/search/live", params={"q": SQL, "since": since}) as res:
        got = _read(res)
    notes = [d["message"] for k, d in got if k == "notice"]
    assert notes == [lv.MSG_BACKFILL]
    rows = [r for k, d in got if k == "rows" for r in d["rows"]]
    assert len(rows) == 1_000
    assert audit(lab, "search.live_start")[-1]["resumed"] is True
    # Without Resume, the same burst in one poll stops the stream and says why.
    _events(engine, 1_200)
    with lab["ana"].stream("GET", "/api/search/live", params={"q": SQL}) as res:
        got = _read(res)
    assert got[-1][1]["reason"] == "too_many"
