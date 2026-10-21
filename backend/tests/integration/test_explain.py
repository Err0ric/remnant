"""POST /api/explain: only the chosen, readable events go out; claims are checked (rule 4)."""

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from app.llm.provider import ProviderResponse
from tests.integration.test_ask import INJECTION, login, make_lab


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    return make_lab(tmp_path)


def ids(lab: dict[str, Any], source: str) -> list[str]:
    res = lab["admin"].post(
        "/api/query",
        json={"sql": f"SELECT event_id FROM events WHERE source_id = '{source}' ORDER BY time"},
        headers=lab["h"],
    )
    return [str(r[0]) for r in res.json()["rows"]]


def reply(claims: list[dict[str, object]]) -> ProviderResponse:
    return ProviderResponse(text=json.dumps({"claims": claims}), model="m")


def test_only_the_chosen_events_are_sent_and_cited_claims_are_verified(lab: dict[str, Any]) -> None:
    fw = ids(lab, "fw_edge")
    lab["script"].replies.append(reply([{"text": "Two events.", "event_ids": fw[:2]}]))
    ana = login(lab, "ana")
    res = ana.post("/api/explain", json={"event_ids": fw[:2], "question": "what happened?"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["citation_check"] == "pass" and body["claims"][0]["verified"] is True
    assert body["events_sent"] == fw[:2] and body["sources"] == ["fw_edge"]
    (messages,) = lab["script"].seen
    system, user = messages[0].content, messages[1].content
    assert INJECTION not in system  # log text never reaches the instructions
    data = json.loads(user)["data"]
    assert [e["event_id"] for e in data["events"]] == fw[:2] and data[
        "question"
    ] == "what happened?"
    assert lab["script"].tools == [None]  # no tools for explain
    db = sqlite3.connect(lab["tmp"] / "data" / "meta.sqlite")
    purpose, check, cited = db.execute(
        "SELECT purpose, citation_check, cited_event_ids FROM llm_calls"
    ).fetchone()
    assert (purpose, check, json.loads(cited)) == ("explain", "pass", sorted(fw[:2]))
    (outcome,) = db.execute(
        "SELECT outcome FROM audit_log WHERE action = 'explain.request'"
    ).fetchone()
    assert outcome == "success"


def test_claims_citing_unsent_or_no_events_are_unverified(lab: dict[str, Any]) -> None:
    fw = ids(lab, "fw_edge")
    lab["script"].replies.append(
        reply(
            [
                {"text": "Good.", "event_ids": [fw[0]]},
                {"text": "Made up.", "event_ids": [fw[0], fw[5]]},  # fw[5] was not sent
                {"text": "No source.", "event_ids": []},
            ]
        )
    )
    body = login(lab, "ana").post("/api/explain", json={"event_ids": fw[:2]}).json()
    assert [c["verified"] for c in body["claims"]] == [True, False, False]
    assert body["citation_check"] == "fail"


def test_events_outside_the_callers_sources_are_never_fetched_or_sent(lab: dict[str, Any]) -> None:
    fw, hr = ids(lab, "fw_edge"), ids(lab, "hr_payroll")
    ana = login(lab, "ana")
    res = ana.post("/api/explain", json={"event_ids": hr[:2]})
    assert res.status_code == 400 and lab["script"].seen == []
    lab["script"].replies.append(reply([{"text": "x", "event_ids": [fw[0]]}]))
    body = ana.post("/api/explain", json={"event_ids": [fw[0], hr[0]]}).json()
    assert body["not_found"] == 1 and body["events_sent"] == [fw[0]]
    sent = json.loads(lab["script"].seen[0][1].content)["data"]["events"]
    assert [e["source_id"] for e in sent] == ["fw_edge"]


def test_limits_and_roles(lab: dict[str, Any]) -> None:
    ana = login(lab, "ana")
    assert ana.post("/api/explain", json={"event_ids": ["x"] * 51}).status_code == 422
    assert ana.post("/api/explain", json={"event_ids": ["not-a-uuid"]}).status_code == 400
    assert (
        login(lab, "aud")
        .post("/api/explain", json={"event_ids": ids(lab, "fw_edge")[:1]})
        .status_code
        == 403
    )
    assert lab["script"].seen == []


def test_a_wrong_shape_answer_is_refused(lab: dict[str, Any]) -> None:
    fw = ids(lab, "fw_edge")
    lab["script"].replies.append(ProviderResponse(text='{"claims": []}', model="m"))
    res = login(lab, "ana").post("/api/explain", json={"event_ids": fw[:1]})
    assert res.status_code >= 400 and "shape" in res.text


def test_cited_ids_are_compared_without_case_or_spaces(lab: dict[str, Any]) -> None:
    fw = ids(lab, "fw_edge")
    lab["script"].replies.append(reply([{"text": "x", "event_ids": [f" {fw[0].upper()} "]}]))
    body = login(lab, "ana").post("/api/explain", json={"event_ids": fw[:1]}).json()
    assert body["claims"][0]["verified"] is True and body["citation_check"] == "pass"
