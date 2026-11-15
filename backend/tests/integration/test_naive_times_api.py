"""API times without a zone read as UTC on every endpoint that takes one (owner order
2026-11-14), with the server's own zone far from UTC both ways. The lab holds what makes a
difference visible: events, AI use (with closed rollup days), and a Proxmox guest on both
sides of a UTC midnight. (Alert filters and metrics already read such a time as UTC.) The windows sit inside each zone's offset from that
midnight: a start just before it (read as local time in Los Angeles it moves past it) and
an end just after it (read as local time in Kolkata it moves before it). Each answer equals
the answer to the same times with an explicit Z, and holds the rows on both sides."""

import json
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.ingest.writer import LakeWriter
from app.search.inventory import TEMPLATE
from tests.integration.test_schedules import NOW, _lake_rows, make_lab

MIDNIGHT = datetime(2026, 10, 10, tzinfo=UTC)  # the lab's NOW is 12:00 that day
WINDOWS = {
    "start_before_midnight": ("2026-10-09T23:30:00", "2026-10-10T11:00:00"),
    "end_after_midnight": ("2026-10-09T12:00:00", "2026-10-10T00:30:00"),
}
LONG = {  # two days or more: AI usage reads closed days from its rollup
    "start_before_midnight": ("2026-10-08T23:30:00", "2026-10-10T11:00:00"),
    "end_after_midnight": ("2026-10-07T12:00:00", "2026-10-10T00:30:00"),
}
NEAR = [timedelta(minutes=-15), timedelta(minutes=15)]


@pytest.fixture(params=["America/Los_Angeles", "Asia/Kolkata"])
def zone(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv("TZ", request.param)
    time.tzset()
    yield request.param
    monkeypatch.undo()
    time.tzset()


@pytest.fixture(scope="module")
def lab(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    from app.core import clock

    clock.pin(NOW)
    out = make_lab(tmp_path_factory.mktemp("naive_api"))
    app = out["app"]
    rows = []
    for day in (MIDNIGHT - timedelta(days=1), MIDNIGHT):
        for d in NEAR:
            (r,) = _lake_rows("mid", "dns_bind", day + d, 1)
            rows.append({**r, "dst_endpoint_hostname": "claude.ai",
                         "src_endpoint_ip": "10.0.0.5", "actor_user_name": "alice@example.com",
                         "device_hostname": "ws-01.example.internal"})  # fmt: skip
    guest = {"vmid": 101, "name": "guest-a.example.internal", "ips": [{"ip": "192.0.2.10"}]}
    (g,) = _lake_rows("pve", TEMPLATE, MIDNIGHT + timedelta(minutes=15), 1)
    rows.append({**g, "raw": json.dumps(guest)})
    LakeWriter(app.state.engine._lake).write(rows)
    rollup = app.state.ai_rollup
    rollup._clock = lambda: NOW
    for _ in range(20):
        if not rollup.run().pending:
            break
    return out


@pytest.fixture(autouse=True)
def _now(pin_now: Callable[[datetime], None]) -> None:
    pin_now(NOW)


def _get(lab: dict[str, Any], path: str, s: str, e: str, z: str) -> Any:
    res = lab["admin"].get(path.format(s=s + z, e=e + z), headers=lab["h"])
    assert res.status_code == 200, (path, res.text)
    return res.json()


def _post(lab: dict[str, Any], path: str, body: dict[str, Any], s: str, e: str, z: str) -> Any:
    res = lab["admin"].post(path, json={**body, "start": s + z, "end": e + z}, headers=lab["h"])
    assert res.status_code == 200, (path, res.text)
    return res.json()


def _both(fetch: Callable[[str], Any]) -> Any:
    """The answer to the times with no zone, checked equal to the answer with Z."""
    bare, with_z = fetch(""), fetch("Z")
    assert bare == with_z
    return bare


def _drop(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _drop(x) for k, x in v.items() if k not in ("elapsed_ms", "updated_at")}
    if isinstance(v, list):
        return [_drop(x) for x in v]
    return v


@pytest.mark.parametrize("window", WINDOWS)
def test_logs_reads_both_sides_of_midnight(lab: dict[str, Any], zone: str, window: str) -> None:
    s, e = WINDOWS[window]
    sql = {"sql": "SELECT count(*) FROM events WHERE source_id = 'mid'"}
    got = _both(lambda z: _post(lab, "/api/query", sql, s, e, z)["rows"])
    assert got == [[2]]
    text = {"text": ""}
    facets = _both(lambda z: _drop(_post(lab, "/api/search/facets", text, s, e, z)))
    assert any(f["field"] == "source_id" for f in facets["facets"])


@pytest.mark.parametrize("window", WINDOWS)
def test_an_entity_summary(lab: dict[str, Any], zone: str, window: str) -> None:
    s, e = WINDOWS[window]
    path = "/api/entities/summary?kind=host&value=ws-01.example.internal&start={s}&end={e}"

    def summary(z: str) -> Any:
        out = _drop(_get(lab, path, s, e, z))
        out["targets"] = sorted(out["targets"], key=str)  # tied counts come in any order
        return out

    got = _both(summary)
    assert got["events"] == 2  # 23:45 and 00:15
    assert (got["first_seen"], got["last_seen"]) == (
        "2026-10-09T23:45:00+00:00", "2026-10-10T00:15:00+00:00")  # fmt: skip


@pytest.mark.parametrize("window", LONG)
def test_ai_usage_with_closed_rollup_days(lab: dict[str, Any], zone: str, window: str) -> None:
    s, e = LONG[window]
    got = _both(lambda z: _drop(_get(lab, "/api/ai/usage?start={s}&end={e}", s, e, z)))
    (claude,) = [x for x in got["services"] if x["service"]["id"] == "claude"]
    assert claude["events"] == 4  # both sides of both midnights


def test_an_inventory_match_at_the_end_of_the_window(lab: dict[str, Any], zone: str) -> None:
    s, e = WINDOWS["end_after_midnight"]
    path = "/api/inventory/matches?value=192.0.2.10&start={s}&end={e}"
    got = _both(lambda z: _get(lab, path, s, e, z)["matches"]["192.0.2.10"])
    assert [m["name"] for m in got] == ["guest-a.example.internal"]


def test_audit_filters_take_a_time_without_a_zone(lab: dict[str, Any], zone: str) -> None:
    res = lab["admin"].get("/api/audit/events?since=2026-10-09T23:30:00", headers=lab["h"])
    assert res.status_code == 200  # it used to be refused


def test_a_rule_run_over_midnight_takes_a_time_without_a_zone(
    lab: dict[str, Any], zone: str
) -> None:
    from tests.integration.test_schedules import WIN_ID

    def run(z: str) -> Any:
        body = {"start": "2026-10-09T19:30:00" + z, "end": "2026-10-10T00:30:00" + z}
        res = lab["admin"].post(f"/api/rules/{WIN_ID}/run", json=body, headers=lab["h"])
        assert res.status_code == 200, res.text  # it used to be refused
        out = res.json()
        return out["match_count"], out["range_start"], out["range_end"], out["status"]

    assert _both(run) == (6, "2026-10-09T19:30:00+00:00", "2026-10-10T00:30:00+00:00", "ok")
    bad = {"start": "2026-10-09 nineteen", "end": "2026-10-10T00:30:00Z"}
    res = lab["admin"].post(f"/api/rules/{WIN_ID}/run", json=bad, headers=lab["h"])
    assert res.status_code == 422 and "start" in res.text  # a malformed time is still refused


@pytest.mark.parametrize("window", WINDOWS)
def test_a_saved_search_timestamp_parameter(lab: dict[str, Any], zone: str, window: str) -> None:
    s, e = WINDOWS[window]
    body = {
        "id": f"between_{window}_{zone.split('/')[1].lower()}",
        "name": "Between two times",
        "sql": "SELECT count(*) FROM events WHERE source_id = 'mid'"
        " AND time >= {{since}} AND time <= {{until}}",
        "params": [{"name": "since", "type": "timestamp"}, {"name": "until", "type": "timestamp"}],
    }
    made = lab["admin"].post("/api/searches", json=body, headers=lab["h"])
    assert made.status_code == 201, made.text
    sid = made.json()["id"]

    def run(z: str) -> Any:
        values = {"since": s + z, "until": e + z}
        res = lab["admin"].post(f"/api/searches/{sid}/run", json={"params": values},
                                headers=lab["h"])  # fmt: skip
        assert res.status_code == 200, res.text  # a time without a zone used to be refused
        return res.json()["rows"]

    assert _both(run) == [[2]]
