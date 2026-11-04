"""Alert items (ADR-0037): one queue for flagged runs, rule matches, and gaps on watched
sources; Close with a reason, reopen, admin-only mutes that expire, Restricted counting,
deep links in alert messages, audit, and the migration of acknowledgements."""

import json
import sqlite3
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from app.meta.db import MIGRATIONS
from tests.integration.test_dashboards import audit
from tests.integration.test_schedules import NOW, WIN_ID, make_lab, run_now, schedule


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    out = make_lab(tmp_path)
    out["app"].state.alert_items._clock = out["clock"]
    return out


def flagged_rule(lab: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """A shared Windows rule schedule (Ana cannot read Windows) that flags every run."""
    sid = schedule(
        lab["admin"], lab["h"], kind="rule", target_id=WIN_ID, threshold_kind="above",
        threshold_value=0, shared=True,
    ).json()["schedule_id"]  # fmt: skip
    run = run_now(lab, lab["admin"], sid, lab["h"]).json()
    assert run["flagged"] is True
    return sid, run


def alerts(client: Any, state: str = "open") -> dict[str, Any]:
    res = client.get(f"/api/alerts?state={state}")
    assert res.status_code == 200, res.text
    out: dict[str, Any] = res.json()
    return out


def test_a_flagged_run_is_an_item_restricted_for_viewers_without_its_sources(
    lab: dict[str, Any],
) -> None:
    sid, run = flagged_rule(lab)
    got = alerts(lab["admin"])
    (item,) = got["items"]
    assert (item["kind"], item["subject"], item["ref_id"]) == ("rule", WIN_ID, run["run_id"])
    assert item["sources"] == ["win_dc"] and item["state"] == "open"
    assert item["schedule_id"] == sid  # the run's schedule, for its rows
    assert got["open"] == 1 and got["restricted"] == 0
    # Ana (Linux only) sees the count, never the item.
    ana = alerts(lab["ana"])
    assert (ana["items"], ana["open"], ana["restricted"]) == ([], 0, 1)
    assert lab["ana"].get(f"/api/alerts/{item['item_id']}").status_code == 403
    # One item per run: running the check again for the same run adds nothing.
    lab["app"].state.schedules._notify(
        lab["app"].state.schedules.get(sid), lab["app"].state.schedules.runs(sid, 1)[0]
    )
    assert len(alerts(lab["admin"])["items"]) == 1


def test_close_needs_a_reason_and_a_note_for_false_positive_then_reopen(
    lab: dict[str, Any],
) -> None:
    flagged_rule(lab)
    iid = alerts(lab["admin"])["items"][0]["item_id"]
    url = f"/api/alerts/{iid}"
    bad = lab["admin"].post(f"{url}/close", json={"reason": "false_positive"}, headers=lab["h"])
    assert bad.status_code == 400 and "note" in bad.text
    assert (
        lab["admin"].post(f"{url}/close", json={"reason": "muted"}, headers=lab["h"]).status_code
        == 422
    )
    ok = lab["admin"].post(
        f"{url}/close",
        json={"reason": "false_positive", "note": "Backup job, tune the rule"},
        headers=lab["h"],
    )
    assert ok.status_code == 200, ok.text
    done = ok.json()
    assert (done["state"], done["close_reason_label"], done["closed_by"]) == (
        "closed", "False positive", "admin",
    )  # fmt: skip
    assert alerts(lab["admin"])["open"] == 0
    assert alerts(lab["admin"], "closed")["items"][0]["item_id"] == iid
    again = lab["admin"].post(f"{url}/close", json={"reason": "expected"}, headers=lab["h"])
    assert again.status_code == 409
    back = lab["admin"].post(f"{url}/reopen", headers=lab["h"]).json()
    assert back["state"] == "open" and [h["action"] for h in back["history"]] == [
        "close",
        "reopen",
    ]
    assert audit(lab, "alert.close")[0] == {
        "item_id": iid, "kind": "rule", "subject": WIN_ID, "reason": "false_positive",
        "note": "Backup job, tune the rule",
    }  # fmt: skip
    assert audit(lab, "alert.reopen")[0]["item_id"] == iid


def test_auditors_read_but_do_not_close(lab: dict[str, Any]) -> None:
    sid = schedule(lab["ana"], threshold_kind="above", threshold_value=0, shared=True).json()[
        "schedule_id"
    ]
    assert run_now(lab, lab["ana"], sid).json()["flagged"] is True
    (item,) = alerts(lab["aud"])["items"]
    res = lab["aud"].post(f"/api/alerts/{item['item_id']}/close", json={"reason": "expected"})
    assert res.status_code == 403
    assert (
        lab["ana"]
        .post(f"/api/alerts/{item['item_id']}/close", json={"reason": "expected"})
        .status_code
        == 200
    )
    assert item["kind"] == "schedule" and item["subject"] == sid


def test_mute_is_admin_only_closes_new_items_and_expires(lab: dict[str, Any]) -> None:
    sid, _ = flagged_rule(lab)
    iid = alerts(lab["admin"])["items"][0]["item_id"]
    assert lab["ana"].post(f"/api/alerts/{iid}/mute", json={"days": 7}).status_code == 403
    assert (
        lab["admin"]
        .post(f"/api/alerts/{iid}/mute", json={"days": 14}, headers=lab["h"])
        .status_code
        == 422
    )
    res = lab["admin"].post(f"/api/alerts/{iid}/mute", json={"days": 7}, headers=lab["h"])
    assert res.status_code == 200 and res.json()["muted_until"]
    assert alerts(lab["admin"])["muted"] == 1
    lab["clock"].now += timedelta(minutes=1)
    # ADR-0043: a repeat the same day joins the open item; a mute closes new items.
    run_now(lab, lab["admin"], sid, lab["h"])
    assert alerts(lab["admin"])["open"] == 1
    closed = lab["admin"].post(
        f"/api/alerts/{iid}/close", json={"reason": "expected"}, headers=lab["h"]
    )
    assert closed.status_code == 200, closed.text
    lab["clock"].now += timedelta(minutes=1)
    run_now(lab, lab["admin"], sid, lab["h"])
    newest = alerts(lab["admin"], "all")["items"][0]
    assert (newest["state"], newest["close_reason"]) == ("closed", "muted")
    assert newest["note"].startswith("Muted until ")
    assert alerts(lab["admin"])["open"] == 0
    # Eight days on, the mute has expired on its own.
    lab["clock"].now += timedelta(days=8)
    assert alerts(lab["admin"])["muted"] == 0
    later = lab["app"].state.alert_items.raise_item("rule", WIN_ID, "Same rule", ref_id="r9")
    assert later.state == "open"
    assert audit(lab, "alert.mute")[0]["days"] == 7


def test_unmute_ends_it_early(lab: dict[str, Any]) -> None:
    flagged_rule(lab)
    iid = alerts(lab["admin"])["items"][0]["item_id"]
    lab["admin"].post(f"/api/alerts/{iid}/mute", json={"days": 7}, headers=lab["h"])
    (mute,) = lab["admin"].get("/api/alerts/mutes").json()
    assert mute["kind"] == "rule" and mute["created_by"] == "admin"
    url = f"/api/alerts/mutes/{mute['mute_id']}"
    assert lab["ana"].delete(url).status_code == 403
    assert lab["admin"].delete(url, headers=lab["h"]).status_code == 204
    assert lab["admin"].get("/api/alerts/mutes").json() == []
    assert audit(lab, "alert.unmute")[0]["subject"] == WIN_ID


def test_a_gap_on_a_watched_source_is_an_item_and_the_message_links_to_it(
    lab: dict[str, Any],
) -> None:
    app = lab["app"]
    app.state.quiet._clock = lab["clock"]
    app.state.quiet._link = "https://siem.example.internal:8080"
    app.state.quiet._received = lambda: {"lin_auth": NOW, "win_dc": NOW}
    lab["clock"].now = NOW
    sent: list[Any] = []
    app.state.quiet._dispatcher.enqueue = lambda alert, *a, **k: sent.append(alert)
    for body in ({"quiet_after_s": None}, {"quiet_after_s": 3600}):  # restart its clock
        res = lab["admin"].put(
            "/api/sources/lin_auth/watch", json={**body, "target_ids": []}, headers=lab["h"]
        )
    assert res.status_code == 200, res.text
    lab["clock"].now = NOW + timedelta(minutes=61)
    app.state.quiet.tick()
    (item,) = alerts(lab["ana"])["items"]  # Ana reads Linux
    assert (item["kind"], item["subject"], item["title"]) == (
        "gap", "lin_auth", "lin_auth stopped sending",
    )  # fmt: skip
    assert sent == []  # no targets: an item, no message
    # It sends again: the item says so and stays open until someone closes it.
    app.state.quiet._received = lambda: {"lin_auth": NOW + timedelta(minutes=70)}
    lab["clock"].now = NOW + timedelta(minutes=71)
    app.state.quiet.tick()
    (item,) = alerts(lab["ana"])["items"]
    assert item["resolved"] == "Events arriving again after 1 h 10 min"
    # Quiet again after 20 minutes back (past the flap guard): with a target, the message
    # links to the item.
    lab["clock"].now = NOW + timedelta(minutes=91)
    w = replace(app.state.quiet.all()[0], target_ids=["t1"])
    app.state.quiet._alert(w, "quiet", "No events received for 2 h", NOW, NOW)
    newest = alerts(lab["ana"])["items"][0]
    assert sent[-1].link == f"https://siem.example.internal:8080/alerts#item={newest['item_id']}"


def test_migration_turns_acknowledged_and_open_flags_into_items(tmp_path: Path) -> None:
    db = sqlite3.connect(tmp_path / "m.sqlite")
    db.execute("PRAGMA foreign_keys = ON")
    for script in MIGRATIONS[:47]:
        if callable(script):
            script(db)
        else:
            db.executescript(script)
    t = "2026-10-01T00:00:00+00:00"
    for sid, shared in (("s1", 1), ("s2", 0)):
        db.execute(
            "INSERT INTO schedules (schedule_id, kind, target_id, name, owner_id, shared, cron,"
            " target_sha256, created_at, updated_at) VALUES (?, 'search', 'q', ?, 'u1', ?,"
            " '* * * * *', 'x', ?, ?)",
            (sid, f"Name {sid}", shared, t, t),
        )
        for n in (1, 2):
            db.execute(
                "INSERT INTO schedule_runs (run_id, schedule_id, started_at, status, row_count,"
                " sources_in_scope, flagged, flag_reason) VALUES (?, ?, ?, 'ok', 5, ?, 1, 'over')",
                (f"{sid}-r{n}", sid, f"2026-10-0{n}T00:00:00+00:00", json.dumps(["lin"])),
            )
    db.execute("INSERT INTO dashboards VALUES ('d', 'My dashboard', 'u1', 0, ?, ?)", (t, t))
    db.execute(
        "INSERT INTO dashboard_acks VALUES ('d', 's1', 's1-r2', 'u1', '2026-10-03T00:00:00+00:00')"
    )
    db.executescript(MIGRATIONS[47])  # type: ignore[arg-type]  # 48 is a script
    rows = db.execute(
        "SELECT ref_id, state, close_reason, note, shared FROM alert_items ORDER BY ref_id"
    ).fetchall()
    assert rows == [
        ("s1-r2", "closed", "benign", "Acknowledged before Close existed", 1),
        ("s2-r2", "open", None, None, 0),
    ]
    assert db.execute("SELECT action FROM alert_item_history").fetchall() == [("close",)]


def test_an_item_records_who_and_which_devices_fired(lab: dict[str, Any]) -> None:
    """ADR-0038 rows 27 and 28: the person page lists the alerts about that person."""
    flagged_rule(lab)
    (item,) = alerts(lab["admin"])["items"]
    assert item["devices"], "the Windows rows name their machine"
    people = item["people"]
    if people:
        who = people[0]
        found = lab["admin"].get("/api/alerts", params={"person": who.upper()}).json()
        assert [i["item_id"] for i in found["items"]] == [item["item_id"]]
    none = lab["admin"].get("/api/alerts", params={"person": "nobody-here"}).json()
    assert none["items"] == []
    store = lab["app"].state.alert_items
    raised = store.raise_item(
        "ai_watch", "sensitive:dana", "Sensitive data to AI: dana", ref_id="s:1",
        people=["Dana@example.com", "dana@example.com", " "],
    )  # fmt: skip
    assert raised.people == ["Dana@example.com", "dana@example.com"]


def test_new_reasons_old_labels_bulk_close_and_mute_choices(lab: dict[str, Any]) -> None:
    """ADR-0043 rows 16, 18, 19: four reasons; stored reasons from before read as the new
    ones; bulk close audits each alert; mute is 7 or 30 days."""
    got = alerts(lab["admin"])
    assert got["reasons"] == {
        "expected": "Expected", "approved": "Approved", "false_positive": "False positive",
        "resolved": "Resolved",
    }  # fmt: skip
    store = lab["app"].state.alert_items
    ids = [store.raise_item("gap", f"src{i}", f"src{i} stopped sending").item_id for i in range(3)]
    with lab["app"].state.meta.connect() as con:  # one closed the old way
        store._set_closed(con, ids[2], None, "follow_up", "check the relay", "2026-11-01T00:00:00")
    old = lab["admin"].get(f"/api/alerts/{ids[2]}").json()
    assert (
        old["close_reason_label"] == "Resolved" and old["history"][0]["reason_label"] == "Resolved"
    )
    assert (
        lab["admin"]
        .post(f"/api/alerts/{ids[0]}/close", json={"reason": "follow_up"}, headers=lab["h"])
        .status_code
        == 422
    )  # gone from the choices
    res = lab["admin"].post(
        "/api/alerts/close", json={"item_ids": ids, "reason": "resolved"}, headers=lab["h"]
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["closed"] == ids[:2] and ids[2] in body["skipped"]
    rows = [r for r in audit(lab, "alert.close") if r.get("bulk")]
    assert sorted(r["item_id"] for r in rows) == sorted(ids[:2])
    bulk_fp = lab["admin"].post(
        "/api/alerts/close", json={"item_ids": [ids[0]], "reason": "false_positive"},
        headers=lab["h"],
    )  # fmt: skip
    assert bulk_fp.json()["skipped"]  # already closed
    assert (
        lab["aud"]
        .post("/api/alerts/close", json={"item_ids": ids, "reason": "expected"})
        .status_code
        == 403
    )
    item = store.raise_item("gap", "src9", "src9 stopped sending")
    for days, code in ((7, 200), (30, 200), (1, 422), (14, 422)):
        r = lab["admin"].post(
            f"/api/alerts/{item.item_id}/mute", json={"days": days}, headers=lab["h"]
        )
        assert r.status_code == code, (days, r.text)


def test_approved_on_an_agent_alert_marks_the_agent_reviewed(lab: dict[str, Any]) -> None:
    store = lab["app"].state.alert_items
    agent = "agent:cc|dana@example.com"
    review = store.raise_item(
        "ai_watch", agent, "AI agent not reviewed: dana", ref_id=f"{agent}:agent"
    )
    change = store.raise_item(
        "ai_watch", agent, "AI agent changed: dana", why="new MCP server wiki",
        group=(agent, "agent_change"),
    )  # fmt: skip
    other = store.raise_item("ai_watch", "agent:cc|erin@example.com", "AI agent not reviewed: erin",
                             ref_id="agent:cc|erin@example.com:agent")  # fmt: skip
    res = lab["admin"].post(
        f"/api/alerts/{change.item_id}/close", json={"reason": "approved"}, headers=lab["h"]
    )
    assert res.status_code == 200, res.text
    state = {i["item_id"]: i for i in alerts(lab["admin"], "all")["items"]}
    assert state[review.item_id]["state"] == "closed"
    assert state[review.item_id]["close_reason_label"] == "Approved"
    assert state[other.item_id]["state"] == "open"
    (rev,) = audit(lab, "ai.review")
    assert rev["agent"] == "cc|dana@example.com" and rev["closed"] == 1
