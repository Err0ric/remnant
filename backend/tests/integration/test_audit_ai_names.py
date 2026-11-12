"""The Audit page and export hide names in every audit row that stores a person from an AI
surface without View people in AI usage (D242)."""

import csv
import io
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from tests.integration.test_schedules import make_lab

NAMES = ("alice", "heidi", "carol", "dave", "erin", "frank", "grace")
SEEDED: list[tuple[str, dict[str, Any]]] = [
    ("ai.sighting", {"count": 2, "items": [
        "ChatGPT by alice@example.com (not approved)", "MCP github by WS-7",
    ]}),
    ("ai.sensitive", {"count": 1, "items": ["heidi@example.com: email x2, card x1"]}),
    ("ai.agent_change", {"count": 4, "items": [
        "Claude Code, carol@example.com: WS-1: new agent",
        "Personal Claude account dave@example.com on WS-2",
        "4 blocked or failed tool calls in an hour by Claude Code for erin@example.com",
        "Cursor agent (frank): new MCP server notes",
    ]}),
]  # fmt: skip
# Other rows that store a person from an AI surface, each with its own address so a test
# finds it, and what a viewer without the permission sees (None: as stored).
_AT = "2026-11-01T00:00:00+00:00"
NEW: list[tuple[str, dict[str, Any], dict[str, Any] | None]] = [
    ("ai.view_people", {"surface": "ai.sessions", "start": _AT, "end": _AT,
                        "sources_in_scope": ["lin_auth"], "person": "ivan@example.com"},
     {"surface": "ai.sessions", "start": _AT, "end": _AT,
      "sources_in_scope": ["lin_auth"], "person": "a person"}),
    ("ai.view_people", {"surface": "ai.person_activity", "sources_in_scope": None,
                        "person": "judy"},
     {"surface": "ai.person_activity", "sources_in_scope": None, "person": "a person"}),
    ("ai.view_people", {"surface": "person.timeline", "sources_in_scope": ["win_dc"],
                        "person": "jordan", "days": 7},
     {"surface": "person.timeline", "sources_in_scope": ["win_dc"],
      "person": "a person", "days": 7}),
    ("ai.view", {"surface": "ai.flow", "sources_in_scope": None, "kind": "user",
                 "value": "mallory@example.com"},
     {"surface": "ai.flow", "sources_in_scope": None, "kind": "user", "value": "a person"}),
    ("ai.view", {"surface": "ai.flow", "kind": "mcp", "value": "github"}, None),
    ("ai.inventory_exclude", {"type": "agent", "key": "cc|dana@example.com",
                              "reason": "dana's test machine"},
     {"type": "agent", "key": "cc|a person", "reason": "a person's test machine"}),
    ("ai.inventory_include", {"type": "agent", "key": "cc|j.doe"},
     {"type": "agent", "key": "cc|a person"}),
    ("ai.inventory_exclude", {"type": "agent", "key": "mcp|WS-9|notes", "reason": "lab"}, None),
    ("ai.inventory_exclude", {"type": "service", "key": "chatgpt", "reason": "lab"}, None),
    ("investigate.graph", {"mode": "ai", "kind": "user", "value": "judy@example.com",
                           "sources_in_scope": ["lin_auth"]},
     {"mode": "ai", "kind": "user", "value": "a person", "sources_in_scope": ["lin_auth"]}),
    ("investigate.graph", {"mode": "entity", "kind": "user", "value": "bob"}, None),
    ("ai.inventory_export", {"format": "csv", "days": 30, "type": "agent", "rows": 3}, None),
    ("ai.export_people", {"format": "csv", "rows": 3, "surface": "ai.inventory_export"}, None),
]  # fmt: skip
NEW_NAMES = ("ivan", "judy", "mallory", "jordan", "dana", "j.doe")
OTHER = ("source.update", {"source_id": "lin_auth", "note": "set up for alice@example.com"})


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    out = make_lab(tmp_path)
    audit = out["app"].state.auth.audit
    for action, detail in SEEDED:
        audit.write(action, "success", None, None, detail)
    review = {"agent": "cc|grace@example.com", "to": "approved", "via": "alert.close"}
    audit.write("ai.review", "success", out["ids"]["aud"], "192.0.2.10", review)
    audit.write(OTHER[0], "success", out["ids"]["aud"], None, OTHER[1])
    for i, (action, detail, _) in enumerate(NEW):
        audit.write(action, "success", out["ids"]["aud"], _ip(i), detail)
    return out


def _ip(i: int) -> str:
    return f"198.51.100.{i + 1}"


def _grant(lab: dict[str, Any], who: str) -> None:
    res = lab["admin"].patch(
        f"/api/users/{lab['ids'][who]}", json={"view_ai_people": True}, headers=lab["h"]
    )
    assert res.status_code == 200, res.text


def _rows(client: Any, **params: str) -> list[dict[str, Any]]:
    res = client.get("/api/audit/events", params={"limit": 500, **params})
    assert res.status_code == 200, res.text
    return list(res.json())


def _ai(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seeded = {"ai.sighting", "ai.sensitive", "ai.agent_change", "ai.review"}
    return [r for r in rows if r["action"] in seeded]


def _export(client: Any) -> list[list[str]]:
    res = client.get("/api/audit/events/export")
    assert res.status_code == 200, res.text
    return list(csv.reader(io.StringIO(res.text)))[1:]


def _named_exports(client: Any) -> list[dict[str, Any]]:
    """The ai.export_people rows audit exports wrote (NEW seeds one from the inventory)."""
    rows = _rows(client, action="ai.export_people")
    return [r for r in rows if r["detail"].get("surface") == "audit.export"]


def _stored(db: Path) -> list[tuple[Any, ...]]:
    with sqlite3.connect(db) as con:
        return list(con.execute("SELECT * FROM audit_log ORDER BY audit_id"))


def test_no_names_without_the_permission(lab: dict[str, Any]) -> None:
    rows = _ai(_rows(lab["aud"]))
    assert len(rows) == 4 and all(r["masked"] for r in rows)
    text = json.dumps(rows).lower()
    assert not [n for n in NAMES if n in text]
    by = {r["action"]: r for r in rows}
    # Nothing in a sighting row proves its owner is a machine, so the device is hidden too.
    assert by["ai.sighting"]["detail"]["items"] == [
        "ChatGPT by a person (not approved)", "MCP github by a person",
    ]  # fmt: skip
    assert by["ai.sensitive"]["detail"] == {"count": 1, "items": ["a person: email x2, card x1"]}
    assert by["ai.agent_change"]["detail"]["items"] == [
        "Claude Code, a person: WS-1: new agent",  # the machine stays
        "Personal Claude account a person on WS-2",
        "4 blocked or failed tool calls in an hour by Claude Code for a person",
        "Cursor agent (a person): new MCP server notes",
    ]
    assert by["ai.review"]["detail"]["agent"] == "cc|a person"
    assert by["ai.review"]["user_id"] == lab["ids"]["aud"]  # the actor stays
    exported = [r for r in _export(lab["aud"]) if r[3] in by]
    assert len(exported) == 4 and not [n for n in NAMES if n in str(exported).lower()]
    assert _named_exports(lab["aud"]) == []  # nothing named left


@pytest.mark.parametrize("who", ["admin", "aud"])
def test_an_admin_and_a_permitted_auditor_see_the_names(lab: dict[str, Any], who: str) -> None:
    if who == "aud":
        _grant(lab, "aud")
    rows = _ai(_rows(lab[who]))
    assert not any(r["masked"] for r in rows)
    text = json.dumps(rows).lower()
    assert all(n in text for n in NAMES)
    exported = [
        r for r in _export(lab[who]) if r[3].startswith("ai.") and r[3] != "ai.export_people"
    ]
    assert all(n in str(exported).lower() for n in NAMES)
    (named,) = _named_exports(lab[who])
    assert named["username"] == who
    assert named["detail"]["named_rows"] == 4 + sum(m is not None for _, _, m in NEW)
    assert named["detail"]["rows"] >= 6


def test_other_rows_are_unchanged(lab: dict[str, Any]) -> None:
    def others(client: Any) -> list[dict[str, Any]]:
        return [r for r in _rows(client, until="2999-01-01T00:00:00Z")
                if not r["action"].startswith(("ai.", "audit.", "investigate."))]  # fmt: skip

    masked, named = others(lab["aud"]), others(lab["admin"])
    assert masked == named and not any(r["masked"] for r in masked)
    (other,) = [r for r in masked if r["action"] == OTHER[0]]
    assert other["detail"] == OTHER[1]


def test_filters_cannot_find_a_row_by_a_hidden_name(lab: dict[str, Any]) -> None:
    aud = lab["aud"]
    for probe in ("alice", "alice@example.com", "cc|grace@example.com", "ivan", "cc|j.doe"):
        assert _rows(aud, user_id=probe) == []
        assert _rows(aud, action=probe) == []
    # The only filters are the action, actor, outcome, and time: nothing reads the detail.
    assert _ai(_rows(aud, detail="alice")) == _ai(_rows(aud, detail="nobody"))
    assert all(r["masked"] for r in _ai(_rows(aud, action="ai.")))


def test_stored_rows_are_never_changed(lab: dict[str, Any]) -> None:
    before = _stored(lab["db"])
    _rows(lab["aud"])
    _export(lab["aud"])
    _rows(lab["admin"])
    _export(lab["admin"])
    assert _stored(lab["db"])[: len(before)] == before


@pytest.mark.parametrize("i", range(len(NEW)), ids=[f"{a}-{i}" for i, (a, *_) in enumerate(NEW)])
def test_every_ai_row_with_a_person_is_masked(lab: dict[str, Any], i: int) -> None:
    action, stored, masked = NEW[i]
    before = _stored(lab["db"])

    def row(client: Any) -> dict[str, Any]:
        (r,) = [r for r in _rows(client, action=action) if r["ip"] == _ip(i)]
        return r

    def exported(client: Any) -> dict[str, Any]:
        (r,) = [r for r in _export(client) if r[5] == _ip(i)]
        return dict(json.loads(r[6]))

    seen = row(lab["aud"])
    assert seen["detail"] == (masked or stored) and seen["masked"] is (masked is not None)
    assert seen["user_id"] == lab["ids"]["aud"]  # the actor stays
    assert exported(lab["aud"]) == (masked or stored)
    if masked is not None:
        text = (json.dumps(seen) + json.dumps(exported(lab["aud"]))).lower()
        assert not [n for n in NEW_NAMES if n in text]
    shown = row(lab["admin"])
    assert shown["detail"] == stored and not shown["masked"]
    assert exported(lab["admin"]) == stored
    assert _stored(lab["db"])[: len(before)] == before


# Alert decisions (alert.close, alert.reopen, alert.mute, alert.unmute) store the item's
# subject as stored: an AI Watch item stored before codes keeps the person in it.
CODE = "{p:0123456789abcdef}"


def _decide(lab: dict[str, Any], item_id: str, note: str) -> None:
    admin, h = lab["admin"], lab["h"]
    for path, body in (("close", {"reason": "false_positive", "note": note}),
                       ("reopen", None), ("mute", {"days": 7})):  # fmt: skip
        res = admin.post(f"/api/alerts/{item_id}/{path}", json=body, headers=h)
        assert res.status_code == 200, res.text
    for m in admin.get("/api/alerts/mutes").json():  # the one mute a call left
        res = admin.delete(f"/api/alerts/mutes/{m['mute_id']}", headers=h)
        assert res.status_code == 204, res.text


def _about(rows: list[dict[str, Any]], subject: str) -> list[dict[str, Any]]:
    return [r for r in rows if r["action"].startswith("alert.")
            and r["detail"].get("subject") == subject]  # fmt: skip


def test_alert_decisions_on_ai_watch_items_are_masked(lab: dict[str, Any]) -> None:
    store = lab["app"].state.alert_items
    agent = store.raise_item(
        "ai_watch", "agent:cc|alice@example.com",
        "AI agent changed: Claude Code, alice@example.com: WS-1",
        ref_id="agent:cc|alice@example.com:Tool:Bash", people=["alice@example.com"],
    )  # fmt: skip
    sensitive = store.raise_item(
        "ai_watch", "sensitive:heidi@example.com", "Sensitive data to AI: heidi@example.com",
        ref_id="sensitive:heidi@example.com:2026-11-01", people=["heidi@example.com"],
    )  # fmt: skip
    coded = store.raise_item(
        "ai_watch", f"sensitive:{CODE}", f"Sensitive data to AI: {CODE}",
        ref_id=f"sensitive:{CODE}:2026-11-01",
    )  # fmt: skip
    rule = store.raise_item(
        "rule", "rule:r1", "Many failed sign-ins: carol@example.com", ref_id="r1:carol",
        people=["carol@example.com"],
    )  # fmt: skip
    _decide(lab, agent.item_id, "asked alice")
    _decide(lab, sensitive.item_id, "heidi knows")
    _decide(lab, coded.item_id, "checked")
    _decide(lab, rule.item_id, "carol was testing")
    masked, named = _rows(lab["aud"]), _rows(lab["admin"])
    actions = ["alert.unmute", "alert.mute", "alert.reopen", "alert.close"]

    a = _about(masked, "agent:cc|a person")
    assert [r["action"] for r in a] == actions and all(r["masked"] for r in a)
    assert a[-1]["detail"]["note"] == "asked a person"
    s = _about(masked, "sensitive:a person")
    assert [r["action"] for r in s] == actions and all(r["masked"] for r in s)
    assert s[-1]["detail"]["note"] == "a person knows"
    text = json.dumps(a + s).lower()
    assert "alice" not in text and "heidi" not in text
    # A code is not a name, and a rule item is not an AI surface: both as stored.
    for subject in (f"sensitive:{CODE}", "rule:r1"):
        rows = _about(masked, subject)
        assert [r["action"] for r in rows] == actions and not any(r["masked"] for r in rows)
        assert rows == _about(named, subject)
    assert _about(masked, "rule:r1")[-1]["detail"]["note"] == "carol was testing"
    exported = [json.loads(r[6]) for r in _export(lab["aud"]) if r[3].startswith("alert.")]
    assert "alice" not in str(exported).lower() and "heidi" not in str(exported).lower()
    assert "carol was testing" in str(exported)
    # With the permission, every name as stored.
    shown = _about(named, "agent:cc|alice@example.com")
    assert [r["action"] for r in shown] == actions and not any(r["masked"] for r in shown)


def test_approving_an_agent_from_its_alert_is_masked(lab: dict[str, Any]) -> None:
    store, agent = lab["app"].state.alert_items, "cc|grace@example.com"
    label = "Claude Code, grace@example.com: WS-3"
    standing = store.raise_item(
        "ai_watch", f"agent:{agent}", f"AI agent not reviewed: {label}",
        ref_id=f"agent:{agent}:agent", people=["grace@example.com"],
    )  # fmt: skip
    change = store.raise_item(
        "ai_watch", f"agent:{agent}", f"AI agent changed: {label}",
        ref_id=f"agent:{agent}:Tool:Bash", people=["grace@example.com"],
        why=f"{label}: new MCP server notes",
    )  # fmt: skip
    res = lab["admin"].post(
        f"/api/alerts/{change.item_id}/close", json={"reason": "approved"}, headers=lab["h"]
    )
    assert res.status_code == 200, res.text
    rows = _rows(lab["aud"])
    closes = [r for r in rows if r["action"] == "alert.close"
              and r["detail"]["item_id"] in (standing.item_id, change.item_id)]  # fmt: skip
    (review,) = [r for r in rows if r["action"] == "ai.review"
                 and r["detail"].get("closed") is not None]  # fmt: skip
    assert len(closes) == 2 and all(r["masked"] for r in [*closes, review])
    assert {r["detail"]["subject"] for r in closes} == {"agent:cc|a person"}
    assert review["detail"]["agent"] == "cc|a person"
    assert "grace" not in json.dumps([*closes, review]).lower()
    named = _rows(lab["admin"])
    assert "grace@example.com" in json.dumps([r for r in named if r["action"] == "ai.review"])
