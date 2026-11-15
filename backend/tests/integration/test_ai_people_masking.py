"""View people in AI usage (ADR-0029 G1 to G3, D242): the guard every AI route must pass.

ana (analyst, without the permission) reads the dns and claude sources, which name
alice@example.com (and the bare `alice`) on ws-0042: Claude telemetry, an MCP inventory,
hooks plugin records, and an AI watch alert. No route may give her a seeded name. The
administrator, who always has the permission, sees them on every route, so the guard is
never vacuous.
"""

import json
import sqlite3
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import pytest

from app.ai import people_view
from app.ai.agents import AgentMachine, AgentStatus, masked
from app.ingest.writer import LakeWriter
from app.search.entities import _Builder, _places
from app.search.identity import IdentityMap
from tests.integration.test_ai_usage import lab  # noqa: F401  # the fixture
from tests.integration.test_m365_consents import _row
from tests.integration.test_schedules import NOW

NAME = "alice"  # in every seeded form: alice@example.com, the os_user alice, card ids
PERSON = "alice@example.com"
HOOK = "a failed tool call from the Windows plugin names the Claude account"

# Routes that answer with person-level AI data, by the surface name their audit row uses.
ROUTES = {
    "ai.usage": "/api/ai/usage",
    "ai.agents": "/api/ai/agents",
    "ai.sessions": "/api/ai/sessions",
    "ai.session": "/api/ai/sessions/s-0042",
    "ai.session_summary": "/api/ai/sessions/s-0042/summary",
    "agents.accounts": "/api/agents/accounts",
    "ai.inventory": "/api/ai/inventory",
    "ai.watch.summary": "/api/ai/watch/summary",
    "ai.flow": "/api/entities/graph?mode=ai",
    "person.timeline": f"/api/people/{PERSON}/timeline",
    "alerts": "/api/alerts",
    "alert": "/api/alerts/{item}",
    "alert_lines": "/api/alerts/lines",
}
# Refused outright without the permission (D242): 403 "Needs View people in AI usage".
# The person filter on alerts is allowed, without AI Watch items (amended 2026-11-11).
REFUSED = {
    "ai.person_activity": f"/api/ai/people/{PERSON}/activity",
    "ai.sessions.person": f"/api/ai/sessions?person={PERSON}",
    "ai.flow.person": f"/api/entities/graph?mode=ai&kind=user&value={PERSON}",
}
# Counts only, never a name, for any viewer: a regression guard, not pending.
COUNTS_ONLY = {
    "agents.overview": "/api/agents/overview",
}


def _hook(event: str, minutes: int, **attr: str) -> dict[str, Any]:
    a = {"event_name": event, "session_id": "s-0042", "claude_account_email": PERSON,
         "os_user": NAME, "cwd": "/srv/app", **attr}  # fmt: skip
    return _row(
        "claude_hooks", HOOK, "claude",
        time=(NOW - timedelta(minutes=minutes)).isoformat(), event=event, attr=a,
        resource={"service_name": "claude-hooks", "host_name": "ws-0042"},
    )  # fmt: skip


@pytest.fixture
def ai_lab(lab: dict[str, Any], pin_now: Callable[[datetime], None]) -> dict[str, Any]:  # noqa: F811
    """test_ai_usage's lab plus a hooks session and an AI watch alert naming alice, with
    the analysts' group reading only the AI sources (dns and claude)."""
    pin_now(NOW + timedelta(hours=1))
    app, admin, h = lab["app"], lab["admin"], lab["h"]
    app.state.ai_watch._clock = lambda: NOW + timedelta(hours=1)  # AI Watch's "now"
    tool = {"tool_name": "mcp__notes__add", "mcp_server_name": "notes"}
    LakeWriter(app.state.engine._lake).write([
        _hook("claude_hooks.session_start", 40),
        _hook("claude_hooks.user_prompt_submit", 39),
        _hook("claude_hooks.pre_tool_use", 38, **tool),
        _hook("claude_hooks.post_tool_use", 38, **tool),
    ])  # fmt: skip
    item = app.state.alert_items.raise_item(
        "ai_watch", f"sensitive:{PERSON}", f"Sensitive data to AI: {PERSON}",
        ref_id=f"s:{PERSON}", people=[PERSON], sources=["claude"],
    )  # fmt: skip
    lab["item"] = item.item_id
    body = {"source_ids": ["dns", "claude"]}
    assert admin.put(f"/api/groups/{lab['gid']}/sources", json=body, headers=h).status_code == 200
    return lab


def _get(client: Any, path: str, ai_lab: dict[str, Any]) -> Any:
    return client.get(path.format(item=ai_lab["item"]))


@pytest.mark.parametrize("surface", [*ROUTES, *REFUSED])
def test_an_admin_sees_the_names(ai_lab: dict[str, Any], surface: str) -> None:
    """The data the guard checks is there: an administrator always has the permission."""
    res = _get(ai_lab["admin"], {**ROUTES, **REFUSED}[surface], ai_lab)
    assert res.status_code == 200, res.text
    assert NAME in res.text


@pytest.mark.parametrize("surface", list(ROUTES))
def test_no_names_without_the_permission(ai_lab: dict[str, Any], surface: str) -> None:
    res = _get(ai_lab["ana"], ROUTES[surface], ai_lab)
    assert res.status_code == 200, res.text
    body = res.json()
    if surface == "person.timeline":
        # The person page is not an AI surface: the name the caller opened, its forms, and
        # the Search behind each row are the page's own. Its AI rows are what is guarded.
        body = [{k: v for k, v in r.items() if k != "sql"} for r in body["rows"]]
    assert NAME not in json.dumps(body)


@pytest.mark.parametrize("surface", list(REFUSED))
def test_person_filters_are_refused_without_the_permission(
    ai_lab: dict[str, Any], surface: str
) -> None:
    res = _get(ai_lab["ana"], REFUSED[surface], ai_lab)
    assert res.status_code == 403, res.text
    assert "Needs View people in AI usage" in res.text
    assert NAME not in res.text


@pytest.mark.parametrize("surface", list(COUNTS_ONLY))
def test_count_only_routes_never_name_people(ai_lab: dict[str, Any], surface: str) -> None:
    for who in ("admin", "ana"):
        res = _get(ai_lab[who], COUNTS_ONLY[surface], ai_lab)
        assert res.status_code == 200, res.text
        assert NAME not in res.text


def _audit(ai_lab: dict[str, Any], action: str) -> list[dict[str, Any]]:
    with sqlite3.connect(ai_lab["db"]) as con:
        rows = con.execute(
            "SELECT detail FROM audit_log WHERE action = ? ORDER BY audit_id", (action,)
        ).fetchall()
    return [json.loads(r[0]) for r in rows]


def test_granting_the_permission_is_audited_and_shown(ai_lab: dict[str, Any]) -> None:
    admin, h, ana_id = ai_lab["admin"], ai_lab["h"], ai_lab["ids"]["ana"]
    users = {u["username"]: u for u in admin.get("/api/users").json()}
    assert users["admin"]["view_ai_people"] is True  # admins always have it (G1)
    assert users["ana"]["view_ai_people"] is False  # off by default (D242)
    assert ai_lab["ana"].get("/api/auth/state").json()["user"]["view_ai_people"] is False
    assert admin.get("/api/auth/state").json()["user"]["view_ai_people"] is True

    res = admin.patch(f"/api/users/{ana_id}", json={"view_ai_people": True}, headers=h)
    assert res.status_code == 200, res.text
    assert res.json()["view_ai_people"] is True
    assert ai_lab["ana"].get("/api/auth/state").json()["user"]["view_ai_people"] is True
    # The same value again changes nothing and writes nothing.
    admin.patch(f"/api/users/{ana_id}", json={"view_ai_people": True}, headers=h)
    admin_id = admin.get("/api/auth/state").json()["user"]["user_id"]
    with sqlite3.connect(ai_lab["db"]) as con:
        (by,) = con.execute(
            "SELECT user_id FROM audit_log WHERE action = 'admin.change'"
        ).fetchone()
    assert by == admin_id
    assert _audit(ai_lab, "admin.change") == [
        {"target": ana_id, "permission": "view_ai_people", "from": False, "to": True}
    ]

    res = admin.patch(f"/api/users/{ana_id}", json={"view_ai_people": False}, headers=h)
    assert res.json()["view_ai_people"] is False
    assert _audit(ai_lab, "admin.change")[-1]["to"] is False


def test_only_an_admin_grants_the_permission(ai_lab: dict[str, Any]) -> None:
    ana, bob_id = ai_lab["ana"], ai_lab["ids"]["bob"]
    res = ana.patch(f"/api/users/{bob_id}", json={"view_ai_people": True})
    assert res.status_code == 403
    assert _audit(ai_lab, "admin.change") == []


def test_an_admin_never_carries_the_flag_into_a_demotion(ai_lab: dict[str, Any]) -> None:
    """The flag is not set on an admin, and promotion clears it, so an admin who is later
    demoted starts without the permission (D242), with the clear in the role change row."""
    admin, h, bob_id = ai_lab["admin"], ai_lab["h"], ai_lab["ids"]["bob"]
    admin.patch(f"/api/users/{bob_id}", json={"view_ai_people": True}, headers=h)
    admin.patch(f"/api/users/{bob_id}", json={"role": "admin"}, headers=h)
    changes = _audit(ai_lab, "user.role_change")
    assert changes[-1] == {
        "target": bob_id,
        "from": "analyst",
        "to": "admin",
        "view_ai_people_cleared": True,
    }
    res = admin.patch(f"/api/users/{bob_id}", json={"view_ai_people": True}, headers=h)
    assert res.status_code == 200, res.text
    assert len(_audit(ai_lab, "admin.change")) == 1  # only the grant before the promotion
    res = admin.patch(f"/api/users/{bob_id}", json={"role": "analyst"}, headers=h)
    assert res.json()["view_ai_people"] is False
    with sqlite3.connect(ai_lab["db"]) as con:
        (flag,) = con.execute(
            "SELECT view_ai_people FROM users WHERE user_id = ?", (bob_id,)
        ).fetchone()
    assert flag == 0


# The AI usage page (ai.usage): machines in place of names, everything else alike. ana and
# bob are both in the group that reads the AI sources, so they ask the cache one question.


def _usage(client: Any) -> dict[str, Any]:
    res = client.get("/api/ai/usage", params={"start": (NOW - timedelta(days=1)).isoformat()})
    assert res.status_code == 200, res.text
    body: dict[str, Any] = res.json()
    return body


def _counts(body: dict[str, Any]) -> dict[str, Any]:
    """Everything but who: the numbers every viewer must see alike."""
    people = [
        {**{k: v for k, v in p.items() if k not in ("person", "key", "maybe")}, "network": None}
        for p in body["people"]
    ]
    services = [{**u, "top_people": []} for u in [*body["services"], *body["non_usage"]]]
    return {**body, "people": people, "services": services, "non_usage": [], "masked": None}


def _grant(ai_lab: dict[str, Any], who: str) -> None:
    res = ai_lab["admin"].patch(
        f"/api/users/{ai_lab['ids'][who]}", json={"view_ai_people": True}, headers=ai_lab["h"]
    )
    assert res.status_code == 200, res.text


def test_ai_usage_shows_machines_and_the_same_counts(ai_lab: dict[str, Any]) -> None:
    named, masked = _usage(ai_lab["admin"]), _usage(ai_lab["ana"])
    assert named["masked"] is False and masked["masked"] is True
    assert [p["key"] for p in named["people"] if p["person"] == PERSON] == [PERSON]
    assert [(p["person"], p["key"]) for p in masked["people"]] == [("ws-0042", "row-0")]
    assert all(u["top_people"] == [] for u in [*masked["services"], *masked["non_usage"]])
    assert NAME not in json.dumps(masked)
    _grant(ai_lab, "bob")  # same sources as ana, with the permission
    named = _usage(ai_lab["bob"])
    assert named["masked"] is False and named["people"][0]["person"] == PERSON
    assert _counts(_usage(ai_lab["ana"])) == _counts(named)


def test_ai_usage_audits_names_only_when_shown(ai_lab: dict[str, Any]) -> None:
    start = (NOW - timedelta(days=1)).replace(second=0, microsecond=0)
    _usage(ai_lab["ana"])
    (row,) = [r for r in _audit(ai_lab, "ai.view") if r.get("surface") == "ai.usage"]
    assert row["start"] == start.isoformat() and row["end"] is None
    assert row["sources_in_scope"] == ["claude", "dns"]
    assert _audit(ai_lab, "ai.view_people") == []
    _grant(ai_lab, "ana")
    assert _usage(ai_lab["ana"])["people"][0]["person"] == PERSON
    (row,) = _audit(ai_lab, "ai.view_people")
    assert row["surface"] == "ai.usage" and row["sources_in_scope"] == ["claude", "dns"]
    _usage(ai_lab["ana"])  # kept 60 s, and still audited as names
    assert _audit(ai_lab, "ai.view_people")[-1]["cached"] is True


def _lookup(who: str, machine: str, minutes: int) -> dict[str, Any]:
    """A DNS lookup of claude.ai with the person and machine on the record."""
    row = _hook("claude_hooks.session_start", minutes)
    row.update(
        event_id=str(uuid.uuid4()), source_id="dns", template_id="dns_bind", class_uid=4003,
        message=None, unmapped=None, actor_user_name=who, src_endpoint_hostname=machine,
        dst_endpoint_hostname="claude.ai", device_hostname=None,
    )  # fmt: skip
    return row


def test_network_people_on_one_machine_stay_two_rows(ai_lab: dict[str, Any]) -> None:
    LakeWriter(ai_lab["app"].state.engine._lake).write([
        _lookup("dana", "ws-0099", 20), _lookup("dana", "ws-0099", 19),
        _lookup("dana", "ws-0100", 18), _lookup("dave", "ws-0099", 17),
    ])  # fmt: skip
    named = {p["person"]: p for p in _usage(ai_lab["admin"])["people"]}
    assert named["dana"]["network"]["devices"] == 2 and named["dave"]["seen_through"] == "network"
    body = _usage(ai_lab["ana"])
    rows = [(p["person"], p["key"], p["network"] and p["network"]["who"]) for p in body["people"]]
    # dana (more lookups) before dave, each as the machine used most; keys never names.
    assert rows == [
        ("ws-0042", "row-0", None),
        ("ws-0099", "row-1", "ws-0099"),
        ("ws-0099", "row-2", "ws-0099"),
    ]
    assert [p["network"]["lookups"] for p in body["people"][1:]] == [3, 1]
    assert "dana" not in json.dumps(body) and "dave" not in json.dumps(body)
    assert body["claude_seen"] == _usage(ai_lab["admin"])["claude_seen"]


def test_a_named_ai_usage_answer_is_never_served_masked_from_the_cache(
    ai_lab: dict[str, Any],
) -> None:
    _grant(ai_lab, "bob")
    assert _usage(ai_lab["bob"])["people"][0]["person"] == PERSON
    for _ in range(2):  # computed, then kept: masked both times
        body = _usage(ai_lab["ana"])
        assert body["masked"] is True and NAME not in json.dumps(body)
    rows = [r for r in _audit(ai_lab, "ai.view") if r.get("surface") == "ai.usage"]
    assert [r.get("cached", False) for r in rows] == [False, True]


def test_a_both_row_shows_the_machine_its_lookups_name(ai_lab: dict[str, Any]) -> None:
    """Seen through the plugin, with no machine on its records, and on the network, whose
    lookups name one: masked, the row is that machine, not "Hidden"."""
    hook = _hook("claude_hooks.session_start", 30, session_id="s-0077", seq="9001",
                 claude_account_email="carol@example.com", os_user="carol")  # fmt: skip
    hook.update(event_id=str(uuid.uuid4()), actor_user_name="carol@example.com",
                device_hostname=None)  # fmt: skip
    LakeWriter(ai_lab["app"].state.engine._lake).write(
        [hook, _lookup("carol@example.com", "ws-0077", 20)]
    )
    named = {p["person"]: p for p in _usage(ai_lab["admin"])["people"]}
    assert named["carol@example.com"]["seen_through"] == "both"
    assert named["carol@example.com"]["network"]["devices"] == 1
    body = _usage(ai_lab["ana"])
    assert [p["person"] for p in body["people"] if p["seen_through"] == "both"] == ["ws-0077"]
    assert "carol" not in json.dumps(body)


# Sessions and Claude accounts: machines in place of names (D242).


def test_sessions_and_accounts_show_machines(ai_lab: dict[str, Any]) -> None:
    ana, admin = ai_lab["ana"], ai_lab["admin"]
    (s,) = ana.get("/api/ai/sessions").json()
    assert (s["person"], s["account"], s["masked"]) == ("ws-0042", "ws-0042", True)
    t = ana.get("/api/ai/sessions/s-0042").json()
    assert (t["person"], t["machine"], t["masked"]) == ("ws-0042", "ws-0042", True)
    acc = ana.get("/api/agents/accounts").json()
    assert acc["masked"] is True
    assert [(r["email"], r["os_users"], r["key"], r["devices"]) for r in acc["rows"]] == [
        ("ws-0042", [], "row-0", ["ws-0042"])
    ]
    named = admin.get("/api/agents/accounts").json()
    assert acc["counts"] == named["counts"] and named["masked"] is False
    (r,) = named["rows"]
    assert (r["email"], r["os_users"], r["key"]) == (PERSON, [NAME], PERSON)
    assert admin.get("/api/ai/sessions").json()[0]["person"] == PERSON


def test_sessions_and_accounts_audit_names_only_when_shown(ai_lab: dict[str, Any]) -> None:
    at = NOW + timedelta(hours=1)
    paths = ("/api/ai/sessions", "/api/ai/sessions/s-0042", "/api/agents/accounts")
    for path in paths:
        assert ai_lab["ana"].get(path).status_code == 200
    rows = {r["surface"]: r for r in _audit(ai_lab, "ai.view") if "surface" in r}
    assert rows["ai.sessions"]["start"] == (at - timedelta(days=7)).isoformat()
    assert rows["ai.sessions"]["end"] == at.isoformat()
    assert rows["ai.session"]["session_id"] == "s-0042"
    assert rows["agents.accounts"]["start"] == (at - timedelta(days=30)).isoformat()
    # The sources the caller may read, or for accounts the ones it read.
    assert [r["sources_in_scope"] for r in rows.values()] == [
        ["claude", "dns"], ["claude", "dns"], ["claude"],
    ]  # fmt: skip
    assert _audit(ai_lab, "ai.view_people") == []
    _grant(ai_lab, "ana")
    for path in paths:
        assert NAME in ai_lab["ana"].get(path).text
    assert [r["surface"] for r in _audit(ai_lab, "ai.view_people")] == [
        "ai.sessions", "ai.session", "agents.accounts",
    ]  # fmt: skip


def test_a_session_summary_shows_the_machine_and_the_same_numbers(
    ai_lab: dict[str, Any],
) -> None:
    """ana (an analyst without View people) and aud (an Auditor) read the claude source:
    the person and account are the machine, every number as the administrator sees it,
    and the audit row says no names were shown."""
    path = "/api/ai/sessions/s-0042/summary"
    named = ai_lab["admin"].get(path).json()
    assert (named["person"], named["account"], named["masked"]) == (PERSON, PERSON, False)
    for who in ("ana", "aud"):
        res = ai_lab[who].get(path)
        assert res.status_code == 200, res.text
        body = res.json()
        assert (body["person"], body["account"], body["machine"], body["masked"]) == (
            "ws-0042", "ws-0042", "ws-0042", True,
        )  # fmt: skip
        assert NAME not in res.text
        same = ("person", "account", "masked")
        assert {k: v for k, v in body.items() if k not in same} == {
            k: v for k, v in named.items() if k not in same
        }
    rows = [r for r in _audit(ai_lab, "ai.view") if r.get("surface") == "ai.session_summary"]
    assert [(r["session_id"], r["sources_in_scope"]) for r in rows] == [
        ("s-0042", ["claude", "dns"]), ("s-0042", ["claude", "dns"]),
    ]  # fmt: skip
    assert [r["surface"] for r in _audit(ai_lab, "ai.view_people")] == ["ai.session_summary"]


def test_person_refusals_are_audited_and_read_nothing(ai_lab: dict[str, Any]) -> None:
    for path in REFUSED.values():
        assert ai_lab["ana"].get(path).status_code == 403
    denied = _audit(ai_lab, "access.denied")
    assert [d["reason"] for d in denied] == ["view_ai_people"] * len(REFUSED)
    assert _audit(ai_lab, "ai.view") == []  # refused before any read
    assert ai_lab["admin"].get(REFUSED["ai.person_activity"]).status_code == 200
    (row,) = _audit(ai_lab, "ai.view_people")
    assert row["surface"] == "ai.person_activity" and row["person"] == PERSON


# Agents and the AI inventory: machines in place of owners (D242).


def _agents(client: Any) -> list[dict[str, Any]]:
    res = client.get("/api/ai/agents")
    assert res.status_code == 200, res.text
    return [a for a in res.json() if a["kind"] == "Claude Code"]


def _inventory_agents(client: Any) -> list[dict[str, Any]]:
    res = client.get("/api/ai/inventory")
    assert res.status_code == 200, res.text
    return [i for i in res.json()["items"] if i["type"] == "agent" and "Claude" in i["name"]]


def test_agents_and_inventory_show_machines(ai_lab: dict[str, Any]) -> None:
    ana, admin = ai_lab["ana"], ai_lab["admin"]
    (named,) = _agents(admin)
    assert named["owners"] == [PERSON] and PERSON in named["label"] and not named["masked"]
    (masked,) = _agents(ana)
    assert (masked["owners"], masked["label"], masked["agent"], masked["masked"]) == (
        [], "Claude Code: ws-0042", "cc|row-0", True,
    )  # fmt: skip
    assert masked["owners_hidden"] == 1 and named["owners_hidden"] == 0
    keep = ("kind", "machine", "machines", "first_seen", "last_seen", "events_24h", "state")
    assert {k: masked[k] for k in keep} == {k: named[k] for k in keep}
    assert _agents(ana) == [masked]  # the same key on every request

    (item,) = _inventory_agents(ana)
    (full,) = _inventory_agents(admin)
    assert (item["key"], item["name"]) == ("cc|row-0", "Claude Code: ws-0042")
    assert (item["people"], item["devices"]) == (full["people"], full["devices"]) == (1, 1)
    assert ana.get("/api/ai/inventory").json()["masked"] is True
    assert admin.get("/api/ai/inventory").json()["masked"] is False

    # An exclusion is by the agent's own key, and shows on the masked row too.
    body = {"type": "agent", "key": full["key"], "reason": "expected"}
    res = admin.put("/api/ai/inventory/exclusions", json=body, headers=ai_lab["h"])
    assert res.status_code == 200, res.text
    (item,) = _inventory_agents(ana)
    assert item["key"] == "cc|row-0" and item["excluded"]["reason"] == "expected"


def test_inventory_export_shows_machines_without_the_permission(ai_lab: dict[str, Any]) -> None:
    for fmt in ("csv", "json"):
        res = ai_lab["ana"].get("/api/ai/inventory/export", params={"format": fmt})
        assert res.status_code == 200, res.text
        assert "Claude Code: ws-0042" in res.text and NAME not in res.text
        assert NAME in ai_lab["admin"].get("/api/ai/inventory/export", params={"format": fmt}).text
    # Only the named exports are audited as such (ADR-0029 G3, G4).
    named = _audit(ai_lab, "ai.export_people")
    assert [(r["surface"], r["format"], r["rows"] > 0) for r in named] == [
        ("ai.inventory_export", "csv", True), ("ai.inventory_export", "json", True),
    ]  # fmt: skip


def test_agents_and_inventory_audit_names_only_when_shown(ai_lab: dict[str, Any]) -> None:
    at = NOW + timedelta(hours=1)
    for path in ("/api/ai/agents", "/api/ai/inventory"):
        assert ai_lab["ana"].get(path).status_code == 200
    rows = {r["surface"]: r for r in _audit(ai_lab, "ai.view") if "surface" in r}
    assert rows["ai.agents"]["start"] == (at - timedelta(days=30)).isoformat()
    assert rows["ai.agents"]["end"] == at.isoformat()
    assert rows["ai.agents"]["sources_in_scope"] == ["claude", "dns"]
    assert rows["ai.inventory"]["start"] == (at - timedelta(days=30)).isoformat()
    assert _audit(ai_lab, "ai.view_people") == []
    _grant(ai_lab, "ana")
    assert _agents(ai_lab["ana"])[0]["owners"] == [PERSON]
    assert NAME in ai_lab["ana"].get("/api/ai/inventory").text
    assert [r["surface"] for r in _audit(ai_lab, "ai.view_people")] == [
        "ai.agents", "ai.inventory",
    ]  # fmt: skip


def test_tied_agents_are_ordered_by_a_keyed_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two people on one machine read the same masked; their order is never their names'."""

    def agent(who: str) -> AgentStatus:
        return AgentStatus(
            kind="Claude Code", agent=f"cc|{who}", label=f"Claude Code, {who}: ws-1",
            owners=[who], machine="ws-1", first_seen="t", last_seen="t", events_24h=1,
            state="usual", machines=[AgentMachine("ws-1", "t", 1)],
        )  # fmt: skip

    orders = set()
    for _ in range(40):  # each run of the app has its own key
        monkeypatch.setattr(people_view, "_TIE", uuid.uuid4().bytes)
        shown = masked([agent("alice"), agent("bob")])
        assert [(a.agent, a.label, a.owners) for a, _ in shown] == [
            ("cc|row-0", "Claude Code: ws-1", []), ("cc|row-1", "Claude Code: ws-1", []),
        ]  # fmt: skip
        orders.add(tuple(o.agent for _, o in shown))
    assert orders == {("cc|alice", "cc|bob"), ("cc|bob", "cc|alice")}


# A person's Alerts tab (D242, amended 2026-11-11): rule items about the person for everyone,
# AI Watch items only with the permission.


def test_person_alerts_leave_out_ai_watch_without_the_permission(ai_lab: dict[str, Any]) -> None:
    rule = ai_lab["app"].state.alert_items.raise_item(
        "rule", "rule:r1", "Many failed sign-ins", ref_id="r1:alice", people=[PERSON],
        sources=["claude"],
    )  # fmt: skip
    path = f"/api/alerts?person={PERSON}&state=all"
    res = ai_lab["ana"].get(path)
    assert res.status_code == 200, res.text
    assert [i["item_id"] for i in res.json()["items"]] == [rule.item_id]
    assert "Sensitive data" not in res.text
    named = {i["item_id"] for i in ai_lab["admin"].get(path).json()["items"]}
    assert named == {rule.item_id, ai_lab["item"]}
    _grant(ai_lab, "ana")
    assert {i["item_id"] for i in ai_lab["ana"].get(path).json()["items"]} == named
    assert _audit(ai_lab, "access.denied") == []


# AI Watch on the Dashboard, the AI flow in Investigate, and a person's timeline (D242).


def _watch(client: Any) -> dict[str, Any]:
    res = client.get("/api/ai/watch/summary")
    assert res.status_code == 200, res.text
    body: dict[str, Any] = res.json()
    return body


def _watch_counts(s: dict[str, Any]) -> Any:
    cards = [(c["key"], c["value"], c["previous"], c["devices"]) for c in s["cards"]]
    return cards, [(n["kind"], n["first_seen"]) for n in s["new"]], s["top"], s["chart"]


def test_ai_watch_shows_machines_and_the_same_counts(ai_lab: dict[str, Any]) -> None:
    named, masked = _watch(ai_lab["admin"]), _watch(ai_lab["ana"])
    assert {c["key"]: c["context"] for c in named["cards"]}["sensitive"] == f"Most from {PERSON}"
    assert {c["key"]: c["context"] for c in masked["cards"]}["sensitive"] == "Most from ws-0042"
    (agent,) = [n for n in named["new"] if n["id"].startswith("cc|")]
    assert (agent["id"], agent["name"]) == (f"cc|{PERSON}", f"Claude Code, {PERSON}: ws-0042")
    (agent,) = [n for n in masked["new"] if n["id"].startswith("cc|")]
    assert (agent["id"], agent["name"]) == ("cc|row-0", "Claude Code: ws-0042")
    assert NAME not in json.dumps(masked)
    _grant(ai_lab, "bob")  # same sources as ana, with the permission
    assert _watch_counts(_watch(ai_lab["bob"])) == _watch_counts(masked)


def test_a_named_ai_watch_answer_is_never_served_masked_from_the_cache(
    ai_lab: dict[str, Any],
) -> None:
    app, h, ana_id = ai_lab["app"], ai_lab["h"], ai_lab["ids"]["ana"]
    _grant(ai_lab, "bob")
    assert NAME in json.dumps(_watch(ai_lab["bob"]))
    for _ in range(2):  # computed, then kept: masked both times
        assert NAME not in json.dumps(_watch(ai_lab["ana"]))
    rows = [r for r in _audit(ai_lab, "ai.view") if r.get("surface") == "ai.watch.summary"]
    assert [r.get("cached", False) for r in rows] == [False, True]
    # Granted, then taken back: the background refresh of the named view runs as ana is
    # now, so it never keeps names for her.
    _grant(ai_lab, "ana")
    assert NAME in json.dumps(_watch(ai_lab["ana"]))
    off = {"view_ai_people": False}
    assert ai_lab["admin"].patch(f"/api/users/{ana_id}", json=off, headers=h).status_code == 200
    assert app.state.refresher.tick() >= 1
    assert NAME not in json.dumps(_watch(ai_lab["ana"]))


def test_ai_watch_audits_names_only_when_shown(ai_lab: dict[str, Any]) -> None:
    _watch(ai_lab["ana"])
    (row,) = [r for r in _audit(ai_lab, "ai.view") if r.get("surface") == "ai.watch.summary"]
    assert (row["days"], row["tz"], row["sources_in_scope"]) == (7, "UTC", ["claude", "dns"])
    assert _audit(ai_lab, "ai.view_people") == []
    _watch(ai_lab["admin"])
    (row,) = _audit(ai_lab, "ai.view_people")
    assert row["surface"] == "ai.watch.summary"


def _flow(client: Any) -> dict[str, Any]:
    res = client.get("/api/entities/graph", params={"mode": "ai"})
    assert res.status_code == 200, res.text
    body: dict[str, Any] = res.json()
    return body


def test_ai_flow_shows_machines_for_people(ai_lab: dict[str, Any]) -> None:
    named, masked = _flow(ai_lab["admin"]), _flow(ai_lab["ana"])
    assert named["masked"] is False and masked["masked"] is True
    lane0 = sorted((c["id"], c["label"], c["group"]) for c in masked["cards"] if c["lane"] == 0)
    # alice@example.com and the bare alice are two people here (no organization domain).
    assert lane0 == [
        ("0:m:10.20.1.5", "10.20.1.5", "Addresses"),
        ("0:m:10.20.1.6", "10.20.1.6", "Addresses"),
        ("0:m:10.20.1.7", "10.20.1.7", "Addresses"),
        ("0:row-0", "ws-0042", "People"),
        ("0:row-1", "ws-0042", "People"),
    ]
    people = [c for c in masked["cards"] if c["group"] == "People"]
    assert all("'ws-0042'" in (c["search_sql"] or "") for c in people)
    ids = {c["id"] for c in masked["cards"]}
    assert all(e["source"] in ids and e["target"] in ids for e in masked["edges"])
    assert NAME not in json.dumps(masked)
    # Everything but the people is alike, and so are the people's numbers.
    rest = [(c["id"], c["events"], c["badges"]) for c in named["cards"] if c["lane"]]
    assert [(c["id"], c["events"], c["badges"]) for c in masked["cards"] if c["lane"]] == rest
    assert sorted(c["events"] for c in named["cards"] if c["lane"] == 0) == sorted(
        c["events"] for c in masked["cards"] if c["lane"] == 0
    )
    assert sum(e["events"] for e in named["edges"]) == sum(e["events"] for e in masked["edges"])


def test_tied_flow_people_are_ordered_by_a_keyed_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two people on one machine read the same masked; their place is never their names'."""
    rows = [(w, "Claude Code", None, None, 1, 0, False, True, "ws-1") for w in ("alice", "bob")]
    orders = set()
    for _ in range(40):  # each run of the app has its own key
        monkeypatch.setattr(people_view, "_TIE", uuid.uuid4().bytes)
        b = _Builder(["People", "AI clients", "Tools and MCP servers", "Destinations"])
        people = _places(rows, IdentityMap(), b).people
        assert sorted(people.values()) == [("row-0", ["ws-1"]), ("row-1", ["ws-1"])]
        assert [c.label for c in b.cards.values()] == ["ws-1", "ws-1"]
        orders.add((people["alice"][0], people["bob"][0]))
    assert orders == {("row-0", "row-1"), ("row-1", "row-0")}


def test_ai_flow_audits_names_only_when_shown(ai_lab: dict[str, Any]) -> None:
    _flow(ai_lab["ana"])
    (row,) = [r for r in _audit(ai_lab, "ai.view") if r.get("surface") == "ai.flow"]
    assert row["kind"] is None and row["sources_in_scope"]
    assert _audit(ai_lab, "ai.view_people") == []
    _flow(ai_lab["admin"])
    (row,) = _audit(ai_lab, "ai.view_people")
    assert row["surface"] == "ai.flow"
    assert len(_audit(ai_lab, "investigate.graph")) == 2  # the existing row, for both


def _timeline(client: Any) -> list[dict[str, Any]]:
    res = client.get(f"/api/people/{PERSON}/timeline")
    assert res.status_code == 200, res.text
    rows: list[dict[str, Any]] = res.json()["rows"]
    return rows


def test_person_timeline_leaves_out_ai_rows_without_the_permission(
    ai_lab: dict[str, Any],
) -> None:
    def ai(rows: list[dict[str, Any]]) -> list[str]:
        return [
            r["title"] for r in rows
            if r["kind"] in ("session", "ai_first", "alert")
            or r["title"].startswith(("claude", "anthropic."))
        ]  # fmt: skip

    # An Anthropic report row per person (on by default), stored with the email as the user.
    day = (NOW - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
    report = _row("anthropic_reports", "Claude Code per user", "claude", date=day)
    LakeWriter(ai_lab["app"].state.engine._lake).write([report])
    assert ai(_timeline(ai_lab["ana"])) == []
    (row,) = [r for r in _audit(ai_lab, "ai.view") if r.get("surface") == "person.timeline"]
    assert "person" not in row  # the search.timeline row holds who the page is about
    assert (row["days"], row["sources_in_scope"]) == (7, ["claude", "dns"])
    _grant(ai_lab, "ana")
    shown = ai(_timeline(ai_lab["ana"]))
    assert "Claude session on ws-0042" in shown and "claude_code.user_prompt" in shown
    assert "anthropic.claude_code" in shown
    (row,) = _audit(ai_lab, "ai.view_people")
    assert row["surface"] == "person.timeline"
    assert len(_audit(ai_lab, "search.timeline")) == 2


# AI Watch items on Alerts (D242): masked at read time, items stored with names included.


def _alerts(client: Any, path: str = "/api/alerts?state=all") -> dict[str, Any]:
    res = client.get(path)
    assert res.status_code == 200, res.text
    body: dict[str, Any] = res.json()
    return body


def test_alert_items_name_no_one_without_the_permission(ai_lab: dict[str, Any]) -> None:
    app, item_id = ai_lab["app"], ai_lab["item"]
    rule = app.state.alert_items.raise_item(
        "rule", "rule:r1", f"Many failed sign-ins: {PERSON}", ref_id="r1:alice",
        people=[PERSON], sources=["claude"],
    )  # fmt: skip
    masked = {i["item_id"]: i for i in _alerts(ai_lab["ana"])["items"]}
    shown = masked[item_id]
    assert (shown["title"], shown["subject"], shown["ref_id"]) == (
        "Sensitive data to AI: a person", "sensitive:a person", "s:a person",
    )  # fmt: skip
    assert (shown["people"], shown["people_hidden"], shown["masked"]) == ([], 1, True)
    # A rule item is not an AI surface: unchanged, names and all.
    assert masked[rule.item_id]["title"] == f"Many failed sign-ins: {PERSON}"
    assert masked[rule.item_id]["people"] == [PERSON] and not masked[rule.item_id]["masked"]
    detail = ai_lab["ana"].get(f"/api/alerts/{item_id}").json()
    assert detail["title"] == shown["title"] and NAME not in json.dumps(detail)
    before = _alerts(ai_lab["ana"])
    _grant(ai_lab, "ana")
    after = _alerts(ai_lab["ana"])
    named = {i["item_id"]: i for i in after["items"]}[item_id]
    assert (named["title"], named["people"], named["masked"]) == (
        f"Sensitive data to AI: {PERSON}", [PERSON], False,
    )  # fmt: skip
    keep = ("open", "restricted", "muted", "by_severity")
    assert {k: before[k] for k in keep} == {k: after[k] for k in keep}
    assert [i["item_id"] for i in before["items"]] == [i["item_id"] for i in after["items"]]
    assert ai_lab["ana"].get(f"/api/alerts/{item_id}").json()["title"] == named["title"]


def test_alert_mutes_and_decisions_without_the_permission(ai_lab: dict[str, Any]) -> None:
    """A muted AI Watch subject names no one; Approved on a masked agent item still decides
    the stored agent and closes its other open items."""
    app, admin, h, ana = ai_lab["app"], ai_lab["admin"], ai_lab["h"], ai_lab["ana"]
    res = admin.post(f"/api/alerts/{ai_lab['item']}/mute", json={"days": 7}, headers=h)
    assert res.status_code == 200, res.text
    mutes = ana.get("/api/alerts/mutes").json()
    assert [m["title"] for m in mutes] == ["Sensitive data to AI: a person"]
    assert NAME in admin.get("/api/alerts/mutes").text
    store, agent = app.state.alert_items, f"cc|{PERSON}"
    label = f"Claude Code, {PERSON}: ws-0042"
    standing = store.raise_item(
        "ai_watch", f"agent:{agent}", f"AI agent not reviewed: {label}",
        ref_id=f"agent:{agent}:agent", people=[PERSON], why="In use; owner x; device ws-0042",
        sources=["claude"],
    )  # fmt: skip
    change = store.raise_item(
        "ai_watch", f"agent:{agent}", f"AI agent changed: {label}",
        ref_id=f"agent:{agent}:Tool:Bash", people=[PERSON], sources=["claude"],
        why=f"{label}: new MCP server notes", group=(f"agent:{agent}", "agent_change"),
    )  # fmt: skip
    res = ana.post(f"/api/alerts/{change.item_id}/close", json={"reason": "approved"})
    assert res.status_code == 200, res.text
    assert res.json()["title"] == "AI agent changed: Claude Code, a person: ws-0042"
    assert NAME not in res.text
    assert admin.get(f"/api/alerts/{standing.item_id}").json()["state"] == "closed"


def test_device_people_name_no_one_without_the_permission(ai_lab: dict[str, Any]) -> None:
    """Who used a device comes from the hooks plugin: AI usage data, so masked (D242)."""
    item = ai_lab["app"].state.alert_items.raise_item(
        "ai_watch", "service:openai", "AI service not reviewed: OpenAI", ref_id="service:openai",
        devices=["ws-0042"], sources=["dns"], range_start=(NOW - timedelta(hours=2)).isoformat(),
        range_end=(NOW + timedelta(hours=1)).isoformat(),
    )  # fmt: skip
    (named,) = ai_lab["admin"].get(f"/api/alerts/{item.item_id}").json()["device_people"]
    assert named["people"] and named["level"] == "attributed"
    (masked,) = ai_lab["ana"].get(f"/api/alerts/{item.item_id}").json()["device_people"]
    assert masked == {**named, "people": []}


def test_alerts_audit_names_only_when_shown(ai_lab: dict[str, Any]) -> None:
    ana, item_id = ai_lab["ana"], ai_lab["item"]
    _alerts(ana, "/api/alerts?state=closed")  # no AI Watch item: not an AI view
    assert _audit(ai_lab, "ai.view") == []
    _alerts(ana)
    ana.get(f"/api/alerts/{item_id}")
    rows = [r for r in _audit(ai_lab, "ai.view") if r["surface"] in ("alerts", "alert")]
    assert [(r["surface"], r["sources_in_scope"]) for r in rows] == [
        ("alerts", ["claude", "dns"]), ("alert", ["claude", "dns"]),
    ]  # fmt: skip
    assert rows[0]["state"] == "all" and rows[1]["item_id"] == item_id
    assert _audit(ai_lab, "ai.view_people") == []
    _grant(ai_lab, "ana")
    _alerts(ana)
    ana.get(f"/api/alerts/{item_id}")
    assert [r["surface"] for r in _audit(ai_lab, "ai.view_people")] == ["alerts", "alert"]


def test_an_item_stored_before_people_were_kept_names_no_one(ai_lab: dict[str, Any]) -> None:
    """A service item from before migration 57: no people, names only in its detail, and
    closed, so never refreshed. Masked on Alerts all the same."""
    store, admin, ana = ai_lab["app"].state.alert_items, ai_lab["admin"], ai_lab["ana"]
    old = store.raise_item(
        "ai_watch", "service:openai", "AI service not reviewed: OpenAI", ref_id="service:openai",
        detail=f"2 people: {PERSON}, {NAME}. 1 device not matched to a person: ws-0042",
        sources=["claude"],
    )  # fmt: skip
    res = admin.post(f"/api/alerts/{old.item_id}/close", json={"reason": "expected"},
                     headers=ai_lab["h"])  # fmt: skip
    assert res.status_code == 200, res.text
    shown = {i["item_id"]: i for i in _alerts(ana)["items"]}[old.item_id]
    assert shown["state"] == "closed" and shown["masked"] is True
    assert shown["people_hidden"] >= 1  # so the People row says names are hidden
    assert shown["detail"] == (
        "2 people: a person, a person. 1 device not matched to a person: ws-0042"
    )
    assert NAME not in json.dumps(shown)
    assert PERSON in json.dumps({i["item_id"]: i for i in _alerts(admin)["items"]}[old.item_id])


def test_close_reopen_and_mute_answers_are_audited_views(ai_lab: dict[str, Any]) -> None:
    """Each answer with an AI Watch item is an AI view (ADR-0029 G3), named only when it
    showed a name."""
    admin, ana, h, item_id = ai_lab["admin"], ai_lab["ana"], ai_lab["h"], ai_lab["item"]
    res = ana.post(f"/api/alerts/{item_id}/close", json={"reason": "expected"})
    assert res.status_code == 200 and NAME not in res.text
    res = ana.post(f"/api/alerts/{item_id}/reopen")
    assert res.status_code == 200 and NAME not in res.text
    assert admin.post(f"/api/alerts/{item_id}/mute", json={"days": 7}, headers=h).status_code == 200
    rows = [r for r in _audit(ai_lab, "ai.view") if r["surface"] == "alert"]
    assert [r["item_id"] for r in rows] == [item_id, item_id]  # ana's close and reopen
    (named,) = _audit(ai_lab, "ai.view_people")  # the admin's mute
    assert (named["surface"], named["item_id"]) == ("alert", item_id)


def test_a_machine_keyed_item_keeps_the_machine_and_names_no_one(ai_lab: dict[str, Any]) -> None:
    """Blocked calls on a machine where no person was seen: AI Watch lists the machine as a
    device, so it stays for every viewer and an administrator's view names no one."""
    app = ai_lab["app"]
    attr = {"event_name": "claude_hooks.post_tool_use_failure", "session_id": "s-0099",
            "tool_name": "Bash", "outcome": "failure"}  # fmt: skip
    LakeWriter(app.state.engine._lake).write([
        _row("claude_hooks", HOOK, "claude", time=(NOW - timedelta(minutes=m)).isoformat(),
             event=attr["event_name"], attr=attr,
             resource={"service_name": "claude-hooks", "host_name": "ws-0099"})
        for m in range(10, 22)
    ])  # fmt: skip
    app.state.ai_watch._account_and_blocked(NOW + timedelta(minutes=5))
    (item,) = [i for i in _alerts(ai_lab["admin"])["items"] if i["subject"] == "agent:cc|ws-0099"]
    named = len(_audit(ai_lab, "ai.view_people"))  # the list has the item naming alice
    item = ai_lab["admin"].get(f"/api/alerts/{item['item_id']}").json()
    assert (item["people"], item["devices"], item["device_people"]) == ([], ["ws-0099"], [])
    assert len(_audit(ai_lab, "ai.view_people")) == named
    assert _audit(ai_lab, "ai.view")[-1]["item_id"] == item["item_id"]
    masked = ai_lab["ana"].get(f"/api/alerts/{item['item_id']}").json()
    assert masked["title"] == "AI agent: blocked or failed calls, ws-0099"
    assert masked["people_hidden"] == 0


def _risk_users(client: Any) -> list[dict[str, Any]]:
    start, end = (NOW - timedelta(days=1)).isoformat(), (NOW + timedelta(hours=2)).isoformat()
    res = client.get("/api/entities/risk", params={"start": start, "end": end})
    assert res.status_code == 200, res.text
    return [u for u in res.json()["users"] if NAME in json.dumps([u["value"], u["names"]])]


def test_people_and_devices_keeps_ai_watch_flags_from_people_without_the_permission(
    ai_lab: dict[str, Any],
) -> None:
    """People & devices is not an AI surface and lists people by name, but the AI Watch
    flags and AI Watch alerts on a person's row are AI usage by person (audit 2026-11 H2):
    without the permission they are left off people, and stay on machines (G2)."""
    app = ai_lab["app"]
    clock, app.state.auth.clock = app.state.auth.clock, lambda: NOW  # raised inside the range
    try:
        app.state.alert_items.raise_item(
            "ai_watch", f"account:{PERSON}", f"Personal Claude account {PERSON} on ws-0042",
            people=[PERSON], devices=["ws-0042"], sources=["claude"],
        )  # fmt: skip
    finally:
        app.state.auth.clock = clock
    seen = _risk_users(ai_lab["admin"])
    assert seen and any(u["ai_flags"] for u in seen)  # the administrator sees them
    assert sum(u["alerts"] for u in seen) >= 1  # and the AI Watch alert about alice
    hidden = _risk_users(ai_lab["ana"])
    assert hidden  # alice is still listed: her other signals are not AI usage
    for u in hidden:
        assert u["ai_flags"] == [] and "ai_flags" not in u["parts"]
        assert u["alerts"] == 0 and "alerts" not in u["parts"]
    # The machine keeps its AI Watch alert for every viewer (G2: machines, never names).
    for who in ("admin", "ana"):
        start, end = (NOW - timedelta(days=1)).isoformat(), (NOW + timedelta(hours=2)).isoformat()
        hosts = ai_lab[who].get("/api/entities/risk", params={"start": start, "end": end}).json()
        assert [h["alerts"] for h in hosts["hosts"] if h["value"] == "ws-0042"] == [1]
    # One audit row per People & devices load (owner, 2026-11-12). G3: the administrator's
    # answers named people with AI usage, so each is an `ai.view_people` row; ana's named
    # no one, so each is the page's `investigate.risk` row, which says so.
    shown = [d for d in _audit(ai_lab, "ai.view_people") if d["surface"] == "investigate.risk"]
    assert len(shown) == 2 and shown[0]["sources_in_scope"]  # the two administrator reads
    assert not [d for d in _audit(ai_lab, "ai.view") if d["surface"] == "investigate.risk"]
    page = _audit(ai_lab, "investigate.risk")
    assert len(page) == 2  # ana's two reads; none besides the administrator's rows above
    assert all(d["ai_view"] == "no_names" and d["start"] and d["end"] for d in page)
    body = ai_lab["ana"].get("/api/entities/risk").json()
    assert body["ai_people_hidden"] is True
    assert ai_lab["admin"].get("/api/entities/risk").json()["ai_people_hidden"] is False


def test_an_ai_watch_alert_counted_on_a_person_is_a_named_answer(ai_lab: dict[str, Any]) -> None:
    """A person with no AI watch flag in the range, only an AI Watch alert: the count on
    their row is still AI usage by person, so the answer is `ai.view_people` (G3)."""
    app = ai_lab["app"]
    then = NOW - timedelta(days=20)  # before the seeded AI activity: no flag in this range
    clock, app.state.auth.clock = app.state.auth.clock, lambda: then
    try:
        app.state.alert_items.raise_item(
            "ai_watch", "sensitive:bob@example.com", "Sensitive data to AI: bob@example.com",
            people=["bob@example.com"], sources=["claude"],
        )  # fmt: skip
    finally:
        app.state.auth.clock = clock
    # bob is seen in the range (a plain session start: nothing AI Watch flags).
    attr = {"event_name": "claude_hooks.session_start", "session_id": "s-bob",
            "os_user": "bob@example.com", "cwd": "/srv/app"}  # fmt: skip
    LakeWriter(app.state.engine._lake).write([
        _row("claude_hooks", HOOK, "claude", time=then.isoformat(),
             event="claude_hooks.session_start", attr=attr,
             resource={"service_name": "claude-hooks", "host_name": "ws-0099"}),
    ])  # fmt: skip
    window = {"start": (then - timedelta(hours=1)).isoformat(),
              "end": (then + timedelta(hours=1)).isoformat()}  # fmt: skip
    res = ai_lab["admin"].get("/api/entities/risk", params=window)
    assert res.status_code == 200, res.text
    assert not any(u["ai_flags"] for u in res.json()["users"])
    named = [d for d in _audit(ai_lab, "ai.view_people") if d["surface"] == "investigate.risk"]
    counted = any(u["alerts"] for u in res.json()["users"])
    assert counted and len(named) == 1
    assert not _audit(ai_lab, "investigate.risk")  # that row is the load's only one
