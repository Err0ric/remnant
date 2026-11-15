"""The rail's Pinned (D259): each user's own pins of saved searches and dashboards, kept on
the server so they follow the user. A pin lists only while its target exists and the
caller may still see it; pin and unpin are audited; at most MAX_PINS per user."""

import json
import sqlite3
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.search.pins import MAX_PINS
from tests.integration.test_schedules import make_lab

PRIVATE = {
    "id": "bob_private",
    "name": "Bob's own",
    "sql": "SELECT count(*) AS n FROM events",
    "visibility": "private",
}


@pytest.fixture
def lab(tmp_path: Any) -> dict[str, Any]:
    return make_lab(tmp_path)


def _audit(lab: dict[str, Any], action: str) -> list[dict[str, Any]]:
    with sqlite3.connect(lab["db"]) as db:
        rows = db.execute("SELECT detail FROM audit_log WHERE action = ?", (action,)).fetchall()
    return [json.loads(r[0]) for r in rows]


def _pins(client: TestClient) -> list[dict[str, Any]]:
    res = client.get("/api/pins")
    assert res.status_code == 200, res.text
    out: list[dict[str, Any]] = res.json()
    return out


def test_a_user_pins_and_unpins_a_saved_search_and_a_dashboard(lab: dict[str, Any]) -> None:
    ana = lab["ana"]
    assert _pins(ana) == []
    assert ana.put("/api/pins/search/failed_ssh").status_code == 200
    board = ana.post("/api/dashboards", json={"name": "Weekly AI review"}).json()
    res = ana.put(f"/api/pins/dashboard/{board['dashboard_id']}")
    assert res.status_code == 200
    # Oldest first: a new pin goes last. The names are the targets' own.
    assert res.json() == _pins(ana)
    assert [(p["kind"], p["id"], p["name"]) for p in _pins(ana)] == [
        ("search", "failed_ssh", "Failed SSH"),
        ("dashboard", board["dashboard_id"], "Weekly AI review"),
    ]
    # Pinning again changes nothing and is not a second pin.
    assert ana.put("/api/pins/search/failed_ssh").status_code == 200
    assert len(_pins(ana)) == 2
    assert ana.delete("/api/pins/search/failed_ssh").status_code == 204
    assert [p["kind"] for p in _pins(ana)] == ["dashboard"]
    assert ana.delete("/api/pins/search/failed_ssh").status_code == 404

    added, removed = _audit(lab, "pin.add"), _audit(lab, "pin.remove")
    assert added == [
        {"kind": "search", "id": "failed_ssh"},
        {"kind": "dashboard", "id": board["dashboard_id"]},
    ]
    assert removed == [{"kind": "search", "id": "failed_ssh"}]


def test_pins_are_each_users_own(lab: dict[str, Any]) -> None:
    assert lab["ana"].put("/api/pins/search/failed_ssh").status_code == 200
    assert _pins(lab["bob"]) == []
    assert lab["bob"].delete("/api/pins/search/failed_ssh").status_code == 404
    assert len(_pins(lab["ana"])) == 1


def test_only_a_target_the_caller_may_see_is_pinned_or_listed(lab: dict[str, Any]) -> None:
    bob, ana = lab["bob"], lab["ana"]
    assert bob.post("/api/searches", json=PRIVATE).status_code == 201
    # Someone else's private search is as missing as one that does not exist.
    assert ana.put("/api/pins/search/bob_private").status_code == 404
    assert ana.put("/api/pins/search/no_such_search").status_code == 404
    assert ana.put("/api/pins/dashboard/no-such-board").status_code == 404
    assert ana.put("/api/pins/report/failed_ssh").status_code == 422

    # A shared target pinned, then made private or deleted: no longer listed.
    assert bob.put("/api/pins/search/bob_private").status_code == 200
    mine = bob.post("/api/dashboards", json={"name": "Bob's board", "shared": True}).json()
    assert ana.put(f"/api/pins/dashboard/{mine['dashboard_id']}").status_code == 200
    assert ana.put("/api/pins/search/failed_ssh").status_code == 200
    assert (
        bob.patch(f"/api/dashboards/{mine['dashboard_id']}", json={"shared": False}).status_code
        == 200
    )
    assert [p["id"] for p in _pins(ana)] == ["failed_ssh"]
    assert ana.delete("/api/searches/failed_ssh").status_code == 204
    assert _pins(ana) == []
    assert [p["id"] for p in _pins(bob)] == ["bob_private"]


def test_at_most_max_pins_and_a_gone_target_frees_its_place(lab: dict[str, Any]) -> None:
    ana = lab["ana"]
    ids = [ana.post("/api/dashboards", json={"name": f"Board {i}"}).json()["dashboard_id"]
           for i in range(MAX_PINS + 1)]  # fmt: skip
    for d in ids[:MAX_PINS]:
        assert ana.put(f"/api/pins/dashboard/{d}").status_code == 200
    full = ana.put(f"/api/pins/dashboard/{ids[-1]}")
    assert full.status_code == 409 and full.json()["code"] == "conflict"
    assert len(_pins(ana)) == MAX_PINS
    # A pinned dashboard deleted: its pin no longer counts.
    assert ana.delete(f"/api/dashboards/{ids[0]}").status_code == 204
    assert ana.put(f"/api/pins/dashboard/{ids[-1]}").status_code == 200
    assert [p["id"] for p in _pins(ana)] == ids[1:]


def test_writes_need_the_csrf_token(lab: dict[str, Any]) -> None:
    admin, h = lab["admin"], lab["h"]
    res = admin.put("/api/pins/search/failed_ssh")
    assert res.status_code == 403 and res.json()["code"] == "csrf_failed"
    assert admin.put("/api/pins/search/failed_ssh", headers=h).status_code == 200
    res = admin.delete("/api/pins/search/failed_ssh")
    assert res.status_code == 403 and res.json()["code"] == "csrf_failed"
    assert admin.delete("/api/pins/search/failed_ssh", headers=h).status_code == 204


@pytest.mark.real_auth
def test_it_needs_a_sign_in(lab: dict[str, Any]) -> None:
    stranger = TestClient(lab["app"])
    assert stranger.get("/api/pins").status_code == 401
    assert stranger.put("/api/pins/search/failed_ssh").status_code in (401, 403)
