"""Server-Timing on query endpoints, and rollup status on Health (owner, 2026-11-01)."""

import re
from pathlib import Path

from app.main import _each_tick, _rollups
from tests.integration.test_schedules import make_lab

TIMING = re.compile(
    r'(cache;desc="(hit|miss)", )?wait;dur=[\d.]+, db;dur=[\d.]+;desc="(\d+) queries",'
    r" app;dur=[\d.]+, total;dur=[\d.]+"
)


def test_a_query_reports_where_its_time_went(tmp_path: Path) -> None:
    lab = make_lab(tmp_path)
    res = lab["admin"].post(
        "/api/query", json={"sql": "SELECT count(*) FROM events"}, headers=lab["h"]
    )
    assert res.status_code == 200, res.text
    m = TIMING.fullmatch(res.headers["Server-Timing"])
    assert m and m.group(1) is None and m.group(3) == "1"


def test_a_cached_page_says_hit(tmp_path: Path) -> None:
    lab = make_lab(tmp_path)
    c = lab["admin"]
    first = c.get("/api/dashboard/sections", params={"window": "7d", "part": "attacks"})
    second = c.get("/api/dashboard/sections", params={"window": "7d", "part": "attacks"})
    assert first.status_code == second.status_code == 200
    one, two = (TIMING.fullmatch(r.headers["Server-Timing"]) for r in (first, second))
    assert one and one.group(2) == "miss" and int(one.group(3)) > 0
    assert two and two.group(2) == "hit" and two.group(3) == "0"


def test_no_header_without_queries(tmp_path: Path) -> None:
    lab = make_lab(tmp_path)
    assert "Server-Timing" not in lab["admin"].get("/api/auth/me").headers


def test_health_shows_each_rollup_and_today(tmp_path: Path) -> None:
    lab = make_lab(tmp_path)
    app, c = lab["app"], lab["admin"]
    before = {r["name"]: r for r in c.get("/api/health-checks").json()["rollups"]}
    assert set(before) == {"auth_rollup", "m365_rollup", "ai_rollup"}
    assert all(r["pending"] is None and r["state"] != "healthy" for r in before.values())
    _rollups(app)
    _each_tick(app)
    after = {r["name"]: r for r in c.get("/api/health-checks").json()["rollups"]}
    for r in after.values():
        assert r["pending"] == 0 and r["last_run"] and r["today_built"], r
        assert r["state"] == "healthy", r
    assert after["auth_rollup"]["label"] == "Attacks and access"
    assert after["auth_rollup"]["days_built"] > 0  # the lab's sshd days


def test_a_failed_build_is_unhealthy(tmp_path: Path) -> None:
    lab = make_lab(tmp_path)
    app = lab["app"]

    def broken() -> None:
        raise RuntimeError("disk")

    app.state.m365_rollup.run = broken
    _rollups(app)
    _each_tick(app)
    rows = {r["name"]: r for r in lab["admin"].get("/api/health-checks").json()["rollups"]}
    assert rows["m365_rollup"]["state"] == "unhealthy"
    assert rows["auth_rollup"]["state"] == "healthy"
