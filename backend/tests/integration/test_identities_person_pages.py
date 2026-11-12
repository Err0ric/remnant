"""The person pages, AI usage, and alert filters use only the part of Identities the
caller's scope shows (T70, D219), and the whole map for an administrator (D223).

ana (analyst, Linux group) reads lin_auth and a second hooks source, hooks_a, where she
sees `dana` (bare) and `frank@example.net`. The claude source, which she cannot read,
holds dana@example.org (linked to dana@example.com, so dana's email form is in
example.com) and erin@example.com. Organization domains: example.com first, then
example.net. Nothing from the claude side may reach her: not the alias, not that it is
dana, not example.com (her events show no account in it)."""

import time
from typing import Any

from tests.integration.test_claude_hooks import lab  # noqa: F401  # the fixture
from tests.integration.test_mcp_identities import _record, _setup

ALIAS = "dana@example.org"


def _send(lab: dict[str, Any], token: str, host: str, *records: dict[str, Any]) -> None:  # noqa: F811
    resource = {"attributes": [
        {"key": "service.name", "value": {"stringValue": "claude-hooks"}},
        {"key": "host.name", "value": {"stringValue": host}},
    ]}  # fmt: skip
    body = {"resourceLogs": [{"resource": resource, "scopeLogs": [
        {"scope": {"name": "claude-hooks"}, "logRecords": list(records)}
    ]}]}  # fmt: skip
    res = lab["admin"].post(
        "/api/otlp/v1/logs", json=body, headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 200, res.text


def _lab(lab: dict[str, Any]) -> dict[str, Any]:  # noqa: F811
    _setup(lab)
    admin, h = lab["admin"], lab["h"]
    res = admin.post(
        "/api/sources",
        json={"source_id": "hooks_a", "kind": "otlp", "format": "json", "template_id": "auto"},
        headers=h,
    )
    assert res.status_code == 201, res.text
    _send(lab, res.json()["otlp_token"], "ws-alpha", _record("s9", "ws-alpha", "dana"))
    _send(lab, res.json()["otlp_token"], "ws-beta", _record("s8", "ws-beta", "frank@example.net"))
    lab["app"].state.ingest.run_once()
    body = {"source_ids": ["lin_auth", "hooks_a"]}
    assert admin.put(f"/api/groups/{lab['gid']}/sources", json=body, headers=h).status_code == 200
    doms = {"domains": ["example.com", "example.net"]}
    assert admin.put("/api/identities/domains", json=doms, headers=h).status_code == 200
    link = {"alias": ALIAS, "person": "dana@example.com"}
    assert admin.put("/api/identities/aliases", json=link, headers=h).status_code == 200
    lab["app"].state.alert_items.raise_item(
        "ai_watch", "sensitive:dana", "Sensitive data to AI: dana", ref_id="s:dana",
        people=["dana"], sources=["hooks_a"],
    )  # fmt: skip
    return lab


def _grant(lab: dict[str, Any]) -> None:  # noqa: F811
    """View people in AI usage for ana: person filters are refused without it (D242)."""
    grant = {"view_ai_people": True}
    res = lab["admin"].patch(f"/api/users/{lab['ids']['ana']}", json=grant, headers=lab["h"])
    assert res.status_code == 200, res.text


def _clean(text: str) -> None:
    assert ALIAS not in text and "example.com" not in text, text


def _get(client: Any, path: str, **params: Any) -> Any:
    res = client.get(path, params=params)
    assert res.status_code == 200, res.text
    return res


def test_person_timeline(lab: dict[str, Any]) -> None:  # noqa: F811
    ana = _lab(lab)["ana"]
    # Without View people in AI usage the AI rows and AI Watch alerts are left out (D242).
    rows = _get(ana, "/api/people/dana/timeline", days=1).json()["rows"]
    assert not [r for r in rows if r["kind"] in ("alert", "session", "ai_first")]
    _grant(lab)
    got = _get(ana, "/api/people/dana/timeline", days=1)
    _clean(got.text)
    assert got.json()["forms"] == ["dana"]
    assert [r["title"] for r in got.json()["rows"] if r["kind"] == "alert"] == [
        "Sensitive data to AI: dana"
    ]
    # The alias as the person: its own person, with none of dana's rows or alerts.
    got = _get(ana, f"/api/people/{ALIAS}/timeline", days=1).json()
    assert got["person"] == ALIAS and got["forms"] == [] and got["rows"] == []
    assert "example.com" not in str(got)


def test_person_hosts(lab: dict[str, Any]) -> None:  # noqa: F811
    ana = _lab(lab)["ana"]
    assert _get(ana, "/api/people/dana/hosts", days=1).json()["hosts"] != []
    got = _get(ana, f"/api/people/{ALIAS}/hosts", days=1).json()
    assert got["hosts"] == [] and got["addresses"] == []


def test_person_ai_activity(lab: dict[str, Any]) -> None:  # noqa: F811
    ana = _lab(lab)["ana"]
    _grant(lab)
    _clean(_get(ana, "/api/ai/people/dana/activity", days=1).text)
    got = _get(ana, f"/api/ai/people/{ALIAS}/activity", days=1).json()
    assert got["person"] == ALIAS and got["sessions"] == [] and got["accounts"] == []


def test_sessions_by_person(lab: dict[str, Any]) -> None:  # noqa: F811
    ana = _lab(lab)["ana"]
    _grant(lab)
    assert len(_get(ana, "/api/ai/sessions", days=1, person="dana").json()) == 1
    assert _get(ana, "/api/ai/sessions", days=1, person=ALIAS).json() == []


def test_alerts_by_person(lab: dict[str, Any]) -> None:  # noqa: F811
    ana = _lab(lab)["ana"]
    _grant(lab)
    assert len(_get(ana, "/api/alerts", state="all", person="dana").json()["items"]) == 1
    assert _get(ana, "/api/alerts", state="all", person=ALIAS).json()["items"] == []


def test_ai_usage_people_get_no_unseen_domain(lab: dict[str, Any]) -> None:  # noqa: F811
    """With the whole map, bare `dana` showed as dana@example.com and frank@example.net as
    frank@example.com: the first organization domain, which ana's events never show."""
    ana = _lab(lab)["ana"]
    start = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 86400))
    got = _get(ana, "/api/ai/usage", start=start)  # without the permission: machines (D242)
    assert sorted(p["person"] for p in got.json()["people"]) == ["ws-alpha", "ws-beta"]
    _grant(lab)
    got = _get(ana, "/api/ai/usage", start=start)
    _clean(got.text)
    assert sorted(p["person"] for p in got.json()["people"]) == ["dana", "frank@example.net"]


def test_inventory_and_accounts(lab: dict[str, Any]) -> None:  # noqa: F811
    ana = _lab(lab)["ana"]
    _clean(_get(ana, "/api/ai/inventory", days=1).text)
    _clean(_get(ana, "/api/agents/accounts", days=1).text)
    _grant(lab)
    _clean(_get(ana, "/api/agents/accounts", days=1).text)


def test_an_administrator_gets_the_whole_map(lab: dict[str, Any]) -> None:  # noqa: F811
    """D223: the same pages for an administrator use every link."""
    admin = _lab(lab)["admin"]
    assert _get(admin, f"/api/people/{ALIAS}/timeline", days=1).json()["person"] == "dana"
    got = _get(admin, "/api/ai/sessions", days=1, person=ALIAS).json()
    assert "s9" in [x["session_id"] for x in got]  # ana's dana, under the alias
    assert len(_get(admin, "/api/alerts", state="all", person=ALIAS).json()["items"]) == 1
