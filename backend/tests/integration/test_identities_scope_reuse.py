"""The scoped Identities set kept between a page's calls (T70, D219) is never one user's
for another, and a grant or an Identities change takes effect on the next call. Also a
search that uses only {{org_domains}} runs (it once failed with "excess parameters").

Same lab as test_identities_not_selectable.py: dana's two accounts are on the claude
source, which ana (Linux group) cannot read."""

from typing import Any

from fastapi.testclient import TestClient

from tests.integration.test_claude_hooks import lab  # noqa: F401  # the fixture
from tests.integration.test_mcp_identities import _setup
from tests.integration.test_schedules import BASE, USER_PW

RANGE = {"start": "2000-01-01T00:00:00Z", "end": "2100-01-01T00:00:00Z"}
SUMMARY = "/api/entities/summary?kind=user&value=dana&start=2000-01-01T00:00:00Z"
ORG_ONLY = (
    "SELECT {{org_domains}} AS d, count(*) AS n FROM events"
    " WHERE time >= {{start}} AND time < {{end}}"
)


def _sql(client: Any, h: dict[str, str] | None = None) -> str:
    res = client.get(SUMMARY, headers=h or {})
    assert res.status_code == 200, res.text
    return str(res.json()["search_sql"])


def test_one_users_set_never_reaches_another(lab: dict[str, Any]) -> None:  # noqa: F811
    _setup(lab)
    # The administrator first, so a kept set exists when ana asks right after.
    assert "dana@example.org" in _sql(lab["admin"], lab["h"])
    assert "dana@example.org" not in _sql(lab["ana"])
    assert "dana@example.org" in _sql(lab["admin"], lab["h"])


def test_a_grant_change_takes_effect_at_once(lab: dict[str, Any]) -> None:  # noqa: F811
    _setup(lab)
    admin, h, gid = lab["admin"], lab["h"], lab["gid"]
    assert "dana@example.org" not in _sql(lab["ana"])
    body = {"source_ids": ["lin_auth", "claude"]}
    assert admin.put(f"/api/groups/{gid}/sources", json=body, headers=h).status_code == 200
    assert "dana@example.org" in _sql(lab["ana"])
    body = {"source_ids": ["lin_auth"]}
    assert admin.put(f"/api/groups/{gid}/sources", json=body, headers=h).status_code == 200
    assert "dana@example.org" not in _sql(lab["ana"])


def test_an_identities_change_takes_effect_at_once(lab: dict[str, Any]) -> None:  # noqa: F811
    _setup(lab)
    admin, h = lab["admin"], lab["h"]
    assert "dana@example.org" in _sql(admin, h)
    gone = {"alias": "dana@example.org", "person": None}
    assert admin.put("/api/identities/aliases", json=gone, headers=h).status_code == 200
    assert "dana@example.org" not in _sql(admin, h)


def test_a_search_with_only_org_domains_runs(lab: dict[str, Any]) -> None:  # noqa: F811
    _setup(lab)
    admin, h = lab["admin"], lab["h"]
    made = admin.post(
        "/api/searches", json={"id": "org_only", "name": "Org only", "sql": ORG_ONLY}, headers=h
    )
    assert made.status_code == 201, made.text
    res = admin.post("/api/searches/org_only/run", json=RANGE, headers=h)
    assert res.status_code == 200, res.text
    assert res.json()["rows"][0][0] == ["example.com"]
    res = admin.post("/api/query", json={"sql": ORG_ONLY, **RANGE}, headers=h)
    assert res.status_code == 200, res.text
    assert res.json()["rows"][0][0] == ["example.com"]
    # ana sees no account in example.com, so the list holds no domain for her.
    res = lab["ana"].post("/api/query", json={"sql": ORG_ONLY, **RANGE})
    assert res.status_code == 200, res.text
    assert res.json()["rows"][0][0] == [""]


GUESS = "SELECT {{person:u}} AS p FROM (VALUES ('mallory@example.net'), ('dana@example.org')) t(u)"


def _guess(lab: dict[str, Any], client: Any, h: dict[str, str] | None = None) -> Any:  # noqa: F811
    res = client.post("/api/query", json={"sql": GUESS, **RANGE}, headers=h or {})
    assert res.status_code == 200, res.text
    return res.json()["rows"]


def _mallory(lab: dict[str, Any]) -> None:  # noqa: F811
    """mallory@example.net linked to dana, with no events anywhere."""
    _setup(lab)
    link = {"alias": "mallory@example.net", "person": "dana"}
    assert (
        lab["admin"].put("/api/identities/aliases", json=link, headers=lab["h"]).status_code == 200
    )


def test_an_administrator_gets_the_whole_map(lab: dict[str, Any]) -> None:  # noqa: F811
    """D223: the Identities page shows an administrator the whole map, so their queries
    bind it with no scan, an alias with no events included."""
    _mallory(lab)
    assert _guess(lab, lab["admin"], lab["h"]) == [["dana"], ["dana"]]


def test_an_analyst_holding_every_source_group_stays_scoped(lab: dict[str, Any]) -> None:  # noqa: F811
    """D223 is by role, not by sources: an analyst who reads every source still gets only
    what the range shows, so a guess at an alias with no events is its own person."""
    _mallory(lab)
    admin, h = lab["admin"], lab["h"]
    gid = admin.post("/api/groups", json={"name": "All"}, headers=h).json()["group_id"]
    body = {"source_ids": ["win_dc", "lin_auth", "claude"]}
    assert admin.put(f"/api/groups/{gid}/sources", json=body, headers=h).status_code == 200
    members = {"user_ids": [lab["ids"]["bob"]]}
    assert admin.put(f"/api/groups/{gid}/members", json=members, headers=h).status_code == 200
    assert _guess(lab, lab["bob"]) == [["mallory@example.net"], ["dana"]]


def test_an_administrator_demoted_is_scoped_on_the_next_call(lab: dict[str, Any]) -> None:  # noqa: F811
    _mallory(lab)
    admin, h = lab["admin"], lab["h"]
    made = admin.post("/api/users", json={"username": "judy", "role": "admin"}, headers=h)
    uid, invite = made.json()["user"]["user_id"], made.json()["invite_token"]
    admin.post("/api/account/password", json={"token": invite, "password": USER_PW})
    login = TestClient(lab["app"], base_url=BASE).post(
        "/api/auth/login", json={"username": "judy", "password": USER_PW, "client": "cli"}
    )
    judy = TestClient(
        lab["app"], base_url=BASE, headers={"Authorization": f"Bearer {login.json()['token']}"}
    )
    assert _guess(lab, judy) == [["dana"], ["dana"]]
    res = admin.patch(f"/api/users/{uid}", json={"role": "analyst"}, headers=h)
    assert res.status_code == 200, res.text
    assert _guess(lab, judy) == [["mallory@example.net"], ["dana@example.org"]]
