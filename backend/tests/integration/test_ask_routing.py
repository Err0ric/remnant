"""ADR-0042 slice 1b (owner, 2026-11-02): a question is routed in code and by one short model
call to a shipped library query, which then runs with the question's people, addresses, and
time as bound filters; the agent writes SQL only when no library query fits. The route is
shown (data or general guidance) with a switch, and every step is audited."""

import json
import sqlite3
from typing import Any

import pytest

from app.llm.locality import Endpoint
from app.llm.provider import ProviderResponse
from app.llm.registry import ProviderRecord, ProviderStore
from tests.integration.test_schedules import make_lab

ROUTE_PROMPT = "You route a security analyst's question"


@pytest.fixture
def lab(tmp_path: Any) -> dict[str, Any]:
    out = make_lab(tmp_path)
    app = out["app"]
    calls: dict[str, Any] = {"route": {"kind": "data", "query": None, "params": {}}, "seen": []}
    agent_sql = "SELECT actor_user_name, count(*) AS n FROM events GROUP BY 1"

    class Fake:
        def __init__(self, record: ProviderRecord, endpoint: Endpoint) -> None:
            self.provider_id, self.locality = record.provider_id, endpoint.locality

        def chat(self, messages: list[Any], *_: object, **__: object) -> ProviderResponse:
            calls["seen"].append(messages)
            if ROUTE_PROMPT in messages[0].content:
                return ProviderResponse(text=json.dumps(calls["route"]), model="m")
            body = {"sql": agent_sql, "explanation": "By user.", "assumptions": []}
            return ProviderResponse(text=json.dumps(body), model="m")

    app.state.gate._factory = lambda r, _s, e: Fake(r, e)
    store: ProviderStore = app.state.providers
    local = store.all()[0]
    store.update(local.provider_id, None, "http://127.0.0.1:11434/v1", "m", True, None, False)
    out["calls"] = calls
    return out


def ask(lab: dict[str, Any], question: str, **body: Any) -> dict[str, Any]:
    res = lab["ana"].post("/api/ask", json={"question": question, **body})
    assert res.status_code == 200, res.text
    out: dict[str, Any] = res.json()
    return out


def test_a_library_query_answers_with_the_named_person_as_a_bound_filter(
    lab: dict[str, Any],
) -> None:
    lab["calls"]["route"] = {"kind": "data", "query": "linux_auth/ssh_logins", "params": {}}
    body = ask(lab, "SSH logins for alice@example.com this week", tz="UTC")
    route = body["route"]
    assert route["kind"] == "data" and route["by"] == "model"
    assert route["library"]["ref"] == "linux_auth/ssh_logins"
    assert route["filters"] == ["user = alice@example.com (also alice)"]
    assert route["time"] == "this week"
    assert body["check"] == "library" and body["auto_run"] is True
    assert "alice" not in body["sql"]  # the person is a parameter, not SQL text
    # Only the routing call went to the model: no SQL was generated.
    assert len(lab["calls"]["seen"]) == 1
    sent = lab["calls"]["seen"][0][-1].content
    assert "linux_auth/ssh_logins" in sent and "why" not in json.loads(sent)["candidates"][0]
    # The fixture's events are from 2026-10-09: "this week" holds none of them.
    run = lab["ana"].post(f"/api/ask/{body['ask_id']}/run").json()
    assert run["rows"] == []
    db = sqlite3.connect(lab["db"])
    (detail,) = db.execute(
        "SELECT detail FROM audit_log WHERE action = 'query.run' ORDER BY audit_id DESC LIMIT 1"
    ).fetchone()
    assert json.loads(detail)["origin"] == "linux_auth/ssh_logins@1.0.0"


def test_the_filter_keeps_only_that_persons_rows(lab: dict[str, Any]) -> None:
    lab["calls"]["route"] = {"kind": "data", "query": "linux_auth/ssh_logins", "params": {}}
    body = ask(lab, "SSH logins for alice@example.com")
    rows = lab["ana"].post(f"/api/ask/{body['ask_id']}/run").json()["rows"]
    assert rows and {r[0] for r in rows} == {"alice"}


def test_no_fitting_query_falls_back_to_the_agent(lab: dict[str, Any]) -> None:
    body = ask(lab, "how many events per user")
    assert body["route"]["library"] is None
    assert body["route"]["reason"] == "No library query fits this question"
    assert body["check"] == "ok" and "actor_user_name" in body["sql"]
    assert len(body["call_ids"]) == 2  # the route and the SQL


def test_a_query_that_cannot_filter_on_a_named_machine_is_not_used(lab: dict[str, Any]) -> None:
    lab["calls"]["route"] = {"kind": "data", "query": "linux_auth/ssh_failures_by_source"}
    body = ask(lab, "failed SSH logins by source on web-01")
    assert body["route"]["library"] is None
    assert "cannot be narrowed to web-01" in body["route"]["reason"]
    assert body["check"] == "ok"  # the agent wrote it instead


def test_an_unknown_ref_is_no_match(lab: dict[str, Any]) -> None:
    lab["calls"]["route"] = {"kind": "data", "query": "m365/does_not_exist"}
    assert ask(lab, "ssh logins")["route"]["library"] is None


def test_general_guidance_is_shown_with_a_switch_to_the_data(lab: dict[str, Any]) -> None:
    lab["calls"]["route"] = {"kind": "knowhow", "query": None, "params": {}}
    body = ask(lab, "how should I harden sshd?")
    assert body["route"]["kind"] == "knowhow" and body["ask_id"] is None and body["sql"] == ""
    # Check your data instead: the same question, routed as a data question.
    forced = ask(lab, "how should I harden sshd?", route="data")
    assert forced["route"]["kind"] == "data" and forced["route"]["by"] == "forced"
    assert forced["ask_id"]


def test_follow_ups_refine_with_the_agent(lab: dict[str, Any]) -> None:
    history = [{"question": "ssh logins", "sql": "SELECT 1"}]
    body = ask(lab, "only failures", history=history)
    assert body["route"]["by"] == "follow_up"
    assert not any(ROUTE_PROMPT in m[0].content for m in lab["calls"]["seen"])


def test_suggestions_without_a_model(lab: dict[str, Any]) -> None:
    """C4: with no AI provider, Ask still offers library checks found by keyword."""
    res = lab["ana"].get("/api/ask/suggest", params={"q": "failed ssh logins by source"})
    assert res.status_code == 200
    refs = [s["ref"] for s in res.json()]
    assert refs[0] == "linux_auth/ssh_failures_by_source" and len(refs) <= 3
    assert lab["aud"].get("/api/ask/suggest", params={"q": "ssh"}).status_code == 403


# --- "Show events" per row (owner, 2026-11-02; D173) --------------------------------------


def test_each_row_of_a_library_answer_opens_its_own_events(lab: dict[str, Any]) -> None:
    lab["calls"]["route"] = {"kind": "data", "query": "linux_auth/ssh_logins", "params": {}}
    body = ask(lab, "SSH logins for alice@example.com")
    run = lab["ana"].post(f"/api/ask/{body['ask_id']}/run").json()
    assert run["drill_keys"] == ["user", "client", "result"]
    cols, first = run["columns"], run["rows"][0]
    values = {k: first[cols.index(k)] for k in run["drill_keys"]}
    seen = len(lab["calls"]["seen"])
    res = lab["ana"].post(f"/api/ask/{body['ask_id']}/drill", json={"values": values})
    assert res.status_code == 200, res.text
    out = res.json()
    assert len(lab["calls"]["seen"]) == seen  # no model call
    assert "{{start}}" in out["sql"] and "FROM events" in out["sql"]
    assert "'alice'" in out["sql"] and "template_id = 'linux_sshd'" in out["sql"]
    # It runs like any query, through the guard on ana's view, and finds that row's events.
    q = lab["ana"].post(
        "/api/query",
        json={"sql": out["sql"], "start": "2000-01-01T00:00:00Z", "end": "2100-01-01T00:00:00Z"},
    )
    assert q.status_code == 200, q.text
    attempts = first[cols.index("attempts")]
    assert len(q.json()["rows"]) == attempts
    assert {r[3] for r in q.json()["rows"]} == {"alice"}


def test_show_events_needs_the_keys_and_a_library_answer(lab: dict[str, Any]) -> None:
    lab["calls"]["route"] = {"kind": "data", "query": "linux_auth/ssh_logins", "params": {}}
    body = ask(lab, "SSH logins for alice@example.com")
    ana, url = lab["ana"], f"/api/ask/{body['ask_id']}/drill"
    assert ana.post(url, json={"values": {"user": "alice"}}).status_code == 404  # not run yet
    ana.post(f"/api/ask/{body['ask_id']}/run")
    assert ana.post(url, json={"values": {"user": "alice"}}).status_code == 400  # keys missing
    # A generated answer has no group keys: nothing to drill into.
    lab["calls"]["route"] = {"kind": "data", "query": None, "params": {}}
    generated = ask(lab, "how many events per user")
    run = ana.post(f"/api/ask/{generated['ask_id']}/run").json()
    assert run["drill_keys"] == []
    bad = ana.post(f"/api/ask/{generated['ask_id']}/drill", json={"values": {}})
    assert bad.status_code == 400
