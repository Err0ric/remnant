"""MCP run_query with {{person:...}} (owner, 2026-11-04; D208, T67): the Identities lookup
runs inside the token owner's own scope, placeholders are filled before the guard and the
read-only connection, and `local_only` still withholds the rows, person and account
grouping included, from an endpoint not marked local."""

import json
import time
from typing import Any

from fastapi.testclient import TestClient

from app.search.library import LIBRARY_DIR, load
from tests.integration.test_claude_hooks import lab  # noqa: F401  # the fixture
from tests.integration.test_mcp import settings, tool
from tests.integration.test_schedules import ADMIN_PW, BASE

Q = next(
    q for q in load(LIBRARY_DIR / "ai_agents" / "pack.yaml").queries
    if q.id == "agents_claude_code_users"
)  # fmt: skip
SINCE = {"since_hours": 24}


def _record(session: str, host: str, email: str) -> dict[str, Any]:
    attrs = {
        "event_name": "claude_hooks.session_start", "role": "session",
        "session_id": session, "claude_account_email": email,
    }  # fmt: skip
    return {
        "timeUnixNano": f"{int(time.time())}000000000",
        "body": {"stringValue": "claude_hooks.session_start"},
        "attributes": [{"key": k, "value": {"stringValue": v}} for k, v in attrs.items()],
    }


def _send(lab: dict[str, Any], host: str, *records: dict[str, Any]) -> None:  # noqa: F811
    resource = {"attributes": [
        {"key": "service.name", "value": {"stringValue": "claude-hooks"}},
        {"key": "host.name", "value": {"stringValue": host}},
    ]}  # fmt: skip
    body = {"resourceLogs": [{"resource": resource, "scopeLogs": [
        {"scope": {"name": "claude-hooks"}, "logRecords": list(records)}
    ]}]}  # fmt: skip
    res = lab["admin"].post(
        "/api/otlp/v1/logs", json=body, headers={"Authorization": f"Bearer {lab['token']}"}
    )
    assert res.status_code == 200, res.text


def _setup(lab: dict[str, Any]) -> TestClient:  # noqa: F811
    """dana's two accounts (linked by an administrator) and erin's, on the claude source;
    returns an MCP client for the administrator (a token, as MCP requires)."""
    _send(lab, "ws-alpha", _record("s1", "ws-alpha", "dana@example.com"),
          _record("s2", "ws-alpha", "dana@example.org"))  # fmt: skip
    _send(lab, "ws-zulu", _record("s3", "ws-zulu", "erin@example.com"))
    lab["app"].state.ingest.run_once()
    admin, h = lab["admin"], lab["h"]
    assert (
        admin.put(
            "/api/identities/domains", json={"domains": ["example.com"]}, headers=h
        ).status_code
        == 200
    )
    link = {"alias": "dana@example.org", "person": "dana"}
    assert admin.put("/api/identities/aliases", json=link, headers=h).status_code == 200
    login = TestClient(lab["app"], base_url=BASE).post(
        "/api/auth/login", json={"username": "admin", "password": ADMIN_PW, "client": "cli"}
    )
    return TestClient(
        lab["app"], base_url=BASE, headers={"Authorization": f"Bearer {login.json()['token']}"}
    )


def _people(out: dict[str, Any]) -> dict[str, str]:
    p, a = out["columns"].index("person"), out["columns"].index("accounts")
    return {r[p]: r[a] for r in out["rows"]}


def test_the_lookup_runs_inside_the_token_owners_scope(lab: dict[str, Any]) -> None:  # noqa: F811
    """The admin may read the claude source and gets dana as one person; ana's token
    reaches only her Linux group, so the same query names no one for her: Identities
    never adds rows the owner cannot read."""
    admin = _setup(lab)
    settings(lab, True, True)  # endpoint local: local_only is not what is tested here
    err, out = tool(admin, "run_query", {"sql": Q.sql, **SINCE})
    assert not err, out
    assert _people(out) == {
        "dana": "dana@example.com (work), dana@example.org (personal)",
        "erin": "erin@example.com (work)",
    }
    err, out = tool(lab["ana"], "run_query", {"sql": Q.sql, **SINCE})
    assert not err, out
    assert out["rows"] == [] and "claude" not in out["sources_read"]


def test_placeholders_are_filled_before_the_guard(lab: dict[str, Any]) -> None:  # noqa: F811
    """The expanded SQL is what the guard checks and the read-only connection runs: a
    placeholder cannot carry a statement or a function the guard refuses, and text that
    only looks like a placeholder is left as it is and fails to parse."""
    admin = _setup(lab)
    settings(lab, True, True)
    for sql in (
        "SELECT {{person:actor_user_name}} AS p FROM read_csv('/etc/passwd')",
        "SELECT {{person:actor_user_name}} AS p FROM events; DROP TABLE events",
        "SELECT {{person:actor_user_name) FROM events --}} AS p FROM events",
        "COPY (SELECT {{person:actor_user_name}} FROM events) TO '/tmp/x.csv'",
    ):
        err, out = tool(admin, "run_query", {"sql": sql, **SINCE})
        assert err and out["error"], sql
    # The events are all still there: nothing ran but SELECTs.
    err, out = tool(admin, "run_query", {"sql": "SELECT count(*) FROM events", **SINCE})
    assert not err and out["rows"][0][0] >= 3


def test_local_only_withholds_the_people_and_accounts(lab: dict[str, Any]) -> None:  # noqa: F811
    """claude is local_only (the default): with the endpoint not marked local, a cloud
    client gets no rows from it, so no person, account, or link between them."""
    admin = _setup(lab)
    settings(lab, True, False)
    err, out = tool(admin, "run_query", {"sql": Q.sql, **SINCE})
    assert not err, out
    assert out["rows"] == [] and "claude" in out["withheld_sources"]
    text = json.dumps(out)
    assert "dana@example.org" not in text and "(personal)" not in text
