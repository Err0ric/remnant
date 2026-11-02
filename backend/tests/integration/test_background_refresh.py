"""Default views refreshed in the background (D147, owner 2026-11-01): the 7-day
Dashboard, Microsoft 365 Overview, and AI Watch are recomputed every minute for people who
opened them, and served at once with when they were computed. A change in the app still
empties the cache; a refresh runs with the viewer's permissions read again."""

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from tests.integration.test_schedules import make_lab

VIEWS = (
    "/api/dashboard/sections?window=7d&part=attacks",
    "/api/m365/overview?window=7d",
    "/api/ai/watch/summary?days=7",
)


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    return make_lab(tmp_path)


def _queries(res: Any) -> str:
    return res.headers.get("Server-Timing", "")


@pytest.mark.parametrize("path", VIEWS)
def test_a_refreshed_view_is_served_at_once_with_its_time(lab: dict[str, Any], path: str) -> None:
    ana, app = lab["ana"], lab["app"]
    first = ana.get(path)
    assert first.status_code == 200, first.text
    stamp = datetime.fromisoformat(first.json()["updated_at"])
    assert app.state.refresher.tick() >= 1
    again = ana.get(path)
    assert 'cache;desc="hit"' in _queries(again)
    assert datetime.fromisoformat(again.json()["updated_at"]) > stamp  # the refresh's copy
    # Other windows keep the plain 60 s cache and are never refreshed.
    other = path.replace("7d", "30d").replace("days=7", "days=30")
    ana.get(other)
    assert all("30" not in str(k) for k in app.state.refresher._watched)


def test_a_change_empties_the_cache_and_the_next_load_computes(lab: dict[str, Any]) -> None:
    ana, admin, h = lab["ana"], lab["admin"], lab["h"]
    ana.get(VIEWS[0])
    lab["app"].state.refresher.tick()
    assert 'cache;desc="hit"' in _queries(ana.get(VIEWS[0]))
    admin.put("/api/ai/mcp-rules", json={"pattern": "x-tool", "status": "approved"}, headers=h)
    assert 'cache;desc="miss"' in _queries(ana.get(VIEWS[0]))


def test_refreshes_stop_for_a_disabled_viewer(lab: dict[str, Any]) -> None:
    ana, admin, h, app = lab["ana"], lab["admin"], lab["h"], lab["app"]
    ana.get(VIEWS[0])
    assert app.state.refresher._watched
    res = admin.patch(f"/api/users/{lab['ids']['ana']}", json={"disabled": True}, headers=h)
    assert res.status_code == 200
    assert app.state.refresher.tick() == 0
    assert not app.state.refresher._watched


def test_refreshes_stop_when_the_viewers_sources_change(lab: dict[str, Any]) -> None:
    ana, admin, h, app = lab["ana"], lab["admin"], lab["h"], lab["app"]
    ana.get(VIEWS[0])
    admin.put(f"/api/groups/{lab['gid']}/sources", json={"source_ids": []}, headers=h)
    assert app.state.refresher.tick() == 0  # never computed with the old scope
    assert not app.state.refresher._watched


def test_refreshes_stop_ten_minutes_after_the_last_view_and_restart_on_the_next(
    lab: dict[str, Any],
) -> None:
    """D147 as accepted: no queries run as a viewer who has left; a load, from the cache
    or not, keeps the view refreshed, and one after a lapse starts it again."""
    from app.api import cache as page_cache

    ana, app = lab["ana"], lab["app"]
    refresher = app.state.refresher
    ana.get(VIEWS[0])
    (key,) = refresher._watched
    refresher.tick()
    ana.get(VIEWS[0])  # served from the refresh: still counts as a view
    seen = refresher._watched[key].seen
    refresher._watched[key].seen = seen - page_cache.WATCH_S - 1  # nobody for 10 minutes
    assert refresher.tick() == 0 and not refresher._watched
    ana.get(VIEWS[0])  # the next view restarts it
    assert key in refresher._watched and refresher.tick() == 1


def test_health_speed_shows_refreshes_per_hour(lab: dict[str, Any]) -> None:
    lab["ana"].get(VIEWS[0])
    lab["app"].state.refresher.tick()
    body = lab["admin"].get("/api/health-checks/refreshes").json()
    assert body["views"] == 1 and len(body["hours"]) == 24
    assert body["hours"][-1]["refreshes"] == 1 and body["hours"][-1]["failed"] == 0
    assert lab["ana"].get("/api/health-checks/refreshes").status_code == 403
