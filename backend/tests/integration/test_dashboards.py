"""Dashboards at scale (ADR-0034): named dashboards, panels with section, order, and size,
headline values, Needs attention acknowledgements, access, audit, and the migration."""

import json
import sqlite3
from datetime import timedelta
from typing import Any

import pytest

from app.meta.db import MIGRATIONS
from tests.integration.test_schedules import WIN_ID, make_lab, run_now, schedule

SQL_IPS = (
    "SELECT src_endpoint_ip AS ip, count(*) AS n FROM events"
    " WHERE raw LIKE '%Failed password%' AND time BETWEEN {{start}} AND {{end}} GROUP BY 1"
)


@pytest.fixture
def lab(tmp_path: Any) -> dict[str, Any]:
    return make_lab(tmp_path)


def audit(lab: dict[str, Any], action: str) -> list[dict[str, Any]]:
    with sqlite3.connect(lab["db"]) as db:
        rows = db.execute("SELECT detail FROM audit_log WHERE action = ?", (action,)).fetchall()
    return [json.loads(r[0]) for r in rows]


def boards(client: Any) -> list[dict[str, Any]]:
    res = client.get("/api/dashboards")
    assert res.status_code == 200, res.text
    out: list[dict[str, Any]] = res.json()
    return out


def test_a_new_schedule_lands_on_the_owners_dashboard(lab: dict[str, Any]) -> None:
    assert boards(lab["ana"]) == []
    s = schedule(lab["ana"]).json()
    (mine,) = boards(lab["ana"])
    assert (mine["name"], mine["mine"], mine["can_edit"]) == ("My dashboard", True, True)
    assert [p["schedule_id"] for p in mine["panels"]] == [s["schedule_id"]]
    assert mine["panels"][0]["size"] == "third"
    assert boards(lab["bob"]) == []  # a personal dashboard is the owner's
    assert audit(lab, "dashboard.panel_add")[0]["schedule_id"] == s["schedule_id"]


def test_named_shared_dashboards_with_sections_sizes_and_order(lab: dict[str, Any]) -> None:
    a = schedule(lab["ana"], shared=True).json()["schedule_id"]
    b = schedule(lab["ana"], shared=True, name="Second").json()["schedule_id"]
    res = lab["ana"].post("/api/dashboards", json={"name": "Identity", "shared": True})
    assert res.status_code == 201
    did = res.json()["dashboard_id"]
    for sid, section, size in ((a, "Access", "tile"), (b, "Access", "half")):
        put = lab["ana"].put(
            f"/api/dashboards/{did}/panels/{sid}", json={"section": section, "size": size}
        )
        assert put.status_code == 200, put.text
    got = lab["ana"].put(f"/api/dashboards/{did}/order", json={"schedule_ids": [b, a]}).json()
    assert [(p["schedule_id"], p["size"], p["section"]) for p in got["panels"]] == [
        (b, "half", "Access"),
        (a, "tile", "Access"),
    ]
    # Bob sees the shared dashboard but cannot change it.
    seen = {d["dashboard_id"]: d for d in boards(lab["bob"])}
    assert seen[did]["can_edit"] is False
    assert (
        lab["bob"].put(f"/api/dashboards/{did}/panels/{a}", json={"size": "full"}).status_code
        == 403
    )
    assert lab["bob"].delete(f"/api/dashboards/{did}").status_code == 403
    # An auditor may look but not make dashboards.
    assert lab["aud"].post("/api/dashboards", json={"name": "Mine"}).status_code == 403
    renamed = lab["ana"].patch(f"/api/dashboards/{did}", json={"name": "Identity and access"})
    assert renamed.json()["name"] == "Identity and access"
    assert audit(lab, "dashboard.update")[0]["from"]["name"] == "Identity"
    assert lab["ana"].delete(f"/api/dashboards/{did}/panels/{a}").status_code == 204
    assert lab["ana"].delete(f"/api/dashboards/{did}").status_code == 204
    assert lab["ana"].get("/api/schedules").json()  # schedules keep running


def test_a_panel_needs_a_schedule_you_can_see(lab: dict[str, Any]) -> None:
    private = schedule(lab["ana"]).json()["schedule_id"]
    mine = lab["bob"].post("/api/dashboards", json={"name": "Bob"}).json()["dashboard_id"]
    res = lab["bob"].put(f"/api/dashboards/{mine}/panels/{private}", json={})
    assert res.status_code == 404


def test_headline_values_over_the_whole_result(lab: dict[str, Any]) -> None:
    lab["ana"].post(
        "/api/searches",
        json={"id": "ips", "name": "Failed by address", "sql": SQL_IPS, "visibility": "shared"},
    )
    s = schedule(lab["ana"], target_id="ips").json()
    sid = s["schedule_id"]
    first = run_now(lab, lab["ana"], sid).json()
    assert first["headline"] == str(first["row_count"])  # default: rows
    for kind, column, label in (("sum", "n", "failed logins"), ("distinct", "ip", "addresses")):
        res = lab["ana"].patch(
            f"/api/schedules/{sid}",
            json={"headline_kind": kind, "headline_column": column, "headline_label": label},
        )
        assert res.status_code == 200, res.text
        assert (res.json()["headline_kind"], res.json()["headline_label"]) == (kind, label)
        lab["clock"].now += timedelta(minutes=1)
        detail = run_now(lab, lab["ana"], sid).json()
        if kind == "sum":
            assert detail["headline"] == str(sum(r[1] for r in _all_rows(lab, detail)))
        else:
            assert detail["headline"] == str(detail["row_count"])  # one row per address
    missing = lab["ana"].patch(f"/api/schedules/{sid}", json={"headline_column": "nope"})
    assert missing.status_code == 200
    lab["clock"].now += timedelta(minutes=1)
    assert run_now(lab, lab["ana"], sid).json()["headline"] is None  # not a wrong number
    bad = lab["ana"].patch(
        f"/api/schedules/{sid}", json={"headline_kind": "sum", "headline_column": ""}
    )
    assert bad.status_code == 400


def _all_rows(lab: dict[str, Any], detail: dict[str, Any]) -> list[list[Any]]:
    sql = SQL_IPS.replace("{{start}}", f"'{detail['range_start']}'").replace(
        "{{end}}", f"'{detail['range_end']}'"
    )
    res = lab["ana"].post("/api/query", json={"sql": sql, "limit": 10000})
    rows: list[list[Any]] = res.json()["rows"]
    return rows


def test_acknowledge_only_the_latest_flagged_run_and_only_if_readable(lab: dict[str, Any]) -> None:
    s = schedule(
        lab["admin"],
        lab["h"],
        kind="rule",
        target_id=WIN_ID,
        threshold_kind="above",
        threshold_value=0,
        shared=True,
    ).json()
    sid = s["schedule_id"]
    run = run_now(lab, lab["admin"], sid, lab["h"]).json()
    assert run["flagged"] is True
    did = boards(lab["admin"])[0]["dashboard_id"]
    lab["admin"].patch(f"/api/dashboards/{did}", json={"shared": True}, headers=lab["h"])
    # Ana sees the shared dashboard but not the Windows source: restricted, cannot ack.
    res = lab["ana"].post(
        f"/api/dashboards/{did}/acknowledge", json={"schedule_id": sid, "run_id": run["run_id"]}
    )
    assert res.status_code == 409 and "restricted" in res.json()["detail"]
    ok = lab["admin"].post(
        f"/api/dashboards/{did}/acknowledge",
        json={"schedule_id": sid, "run_id": run["run_id"]},
        headers=lab["h"],
    )
    assert ok.status_code == 204
    assert boards(lab["admin"])[0]["acks"] == {sid: run["run_id"]}
    assert audit(lab, "dashboard.acknowledge")[0]["reason"] == run["flag_reason"]
    lab["clock"].now += timedelta(minutes=1)
    newer = run_now(lab, lab["admin"], sid, lab["h"]).json()
    stale = lab["admin"].post(
        f"/api/dashboards/{did}/acknowledge",
        json={"schedule_id": sid, "run_id": run["run_id"]},
        headers=lab["h"],
    )
    assert stale.status_code == 409  # only the latest flagged run
    assert boards(lab["admin"])[0]["acks"][sid] != newer["run_id"]  # needs attention again


def test_migration_keeps_every_panel(tmp_path: Any) -> None:
    """Migration 46 on a database at 45: one My dashboard per owner with the D82 width and
    view, and shared schedules also on one shared dashboard."""
    db = sqlite3.connect(tmp_path / "m.sqlite")
    db.execute("PRAGMA foreign_keys = ON")
    for script in MIGRATIONS[:45]:
        if callable(script):
            script(db)
        else:
            db.executescript(script)
    cols = (
        "schedule_id, kind, target_id, name, owner_id, shared, cron, target_sha256,"
        " created_at, updated_at, panel_width, panel_view"
    )
    for sid, owner, shared, width, at in (
        ("s1", "u1", 0, "half", "2026-10-01"),
        ("s2", "u1", 1, "third", "2026-10-02"),
        ("s3", "u2", 1, "full", "2026-10-03"),
    ):
        db.execute(
            f"INSERT INTO schedules ({cols}) VALUES (?, 'search', 't', ?, ?, ?, 'x', 'h', ?, ?,"
            " ?, 'bars')",  # test data
            (sid, sid, owner, shared, at, at, width),
        )
    db.executescript(MIGRATIONS[45])  # type: ignore[arg-type]  # 46 is a script
    got = db.execute(
        "SELECT dashboard_id, schedule_id, position, size, view FROM dashboard_panels ORDER BY 1, 3"
    ).fetchall()
    assert got == [
        ("mine-u1", "s1", 1, "half", "bars"),
        ("mine-u1", "s2", 2, "third", "bars"),
        ("mine-u2", "s3", 1, "full", "bars"),
        ("shared-panels", "s2", 1, "third", "bars"),
        ("shared-panels", "s3", 2, "full", "bars"),
    ]
    names = db.execute(
        "SELECT dashboard_id, owner_id, shared FROM dashboards ORDER BY 1"
    ).fetchall()
    assert names == [("mine-u1", "u1", 0), ("mine-u2", "u2", 0), ("shared-panels", "u1", 1)]
    # 47: sections in the order of their first panel.
    db.execute("UPDATE dashboard_panels SET section = 'Data' WHERE schedule_id = 's1'")
    db.execute("UPDATE dashboard_panels SET section = 'AI' WHERE schedule_id = 's2'")
    db.executescript(MIGRATIONS[46])  # type: ignore[arg-type]  # 47 is a script
    got = db.execute(
        "SELECT dashboard_id, name, position FROM dashboard_sections ORDER BY 1, 3"
    ).fetchall()
    assert got == [("mine-u1", "Data", 1), ("mine-u1", "AI", 2), ("shared-panels", "AI", 1)]


def test_a_schedule_asked_onto_a_dashboard_you_cannot_change_goes_to_your_own(
    lab: dict[str, Any],
) -> None:
    team = lab["ana"].post("/api/dashboards", json={"name": "Team", "shared": True}).json()
    s = schedule(lab["bob"], dashboard_id=team["dashboard_id"], panel_size="tile")
    assert s.status_code == 201
    (bobs,) = [d for d in boards(lab["bob"]) if d["mine"]]
    assert [(p["schedule_id"], p["size"]) for p in bobs["panels"]] == [
        (s.json()["schedule_id"], "tile")
    ]
    gone = schedule(lab["bob"], dashboard_id="no-such-dashboard")
    assert gone.status_code == 201  # a forgotten id still gets a panel


def test_layout_moves_panels_between_sections_in_a_stored_order(lab: dict[str, Any]) -> None:
    ids = [schedule(lab["ana"], name=f"S{i}").json()["schedule_id"] for i in range(4)]
    did = boards(lab["ana"])[0]["dashboard_id"]
    a, b, c, d = ids
    # Drag c into a new section "Identity", put "Access" first, leave d unsectioned.
    layout = {
        "sections": [
            {"name": "", "schedule_ids": [d]},
            {"name": "Access", "schedule_ids": [b, a]},
            {"name": "Identity", "schedule_ids": [c]},
            {"name": "Empty for now", "schedule_ids": []},
        ]
    }
    res = lab["ana"].put(f"/api/dashboards/{did}/layout", json=layout)
    assert res.status_code == 200, res.text
    got = res.json()
    assert got["sections"] == ["Access", "Identity", "Empty for now"]
    order = sorted(got["panels"], key=lambda p: p["position"])
    assert [(p["schedule_id"], p["section"]) for p in order] == [
        (d, ""),
        (b, "Access"),
        (a, "Access"),
        (c, "Identity"),
    ]
    (row,) = audit(lab, "dashboard.layout")
    assert row["to"][1] == {"section": "Access", "panels": [b, a]}
    # Rename a section: its panels follow.
    ren = lab["ana"].patch(
        f"/api/dashboards/{did}/sections", json={"old": "Access", "new": "Sign-ins"}
    )
    assert ren.json()["sections"][0] == "Sign-ins"
    assert {p["section"] for p in ren.json()["panels"]} == {"", "Sign-ins", "Identity"}
    assert audit(lab, "dashboard.section_rename") == [
        {"dashboard_id": did, "from": "Access", "to": "Sign-ins"}
    ]
    # Delete a section: send the layout without it, its panels with no section.
    gone = (
        lab["ana"]
        .put(
            f"/api/dashboards/{did}/layout",
            json={
                "sections": [
                    {"name": "", "schedule_ids": [d, c]},
                    {"name": "Sign-ins", "schedule_ids": [b, a]},
                ]
            },
        )
        .json()
    )
    assert gone["sections"] == ["Sign-ins"]
    # Every panel exactly once; nobody else may change it.
    bad = {"sections": [{"name": "", "schedule_ids": [a, b, c]}]}
    assert lab["ana"].put(f"/api/dashboards/{did}/layout", json=bad).status_code == 400
    assert lab["bob"].put(f"/api/dashboards/{did}/layout", json=layout).status_code == 404
    # Setting a panel's section by name makes the section, after the others.
    lab["ana"].put(f"/api/dashboards/{did}/panels/{c}", json={"section": "Later"})
    assert boards(lab["ana"])[0]["sections"] == ["Sign-ins", "Later"]
