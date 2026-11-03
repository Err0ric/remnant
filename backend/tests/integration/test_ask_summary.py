"""ADR-0042 slice 1c (owner, 2026-11-02): after the query runs, code writes the headline;
with `ask.summarize` on, one zero-tool model call writes statements about the kept rows,
and only statements that cite rows that were sent are shown (C1). If a summary cannot
cite, there is none: the headline and the rows stand alone."""

import json
import sqlite3
from typing import Any

import pytest

from app.core.errors import ClassificationBlockedError
from app.llm.ask_summary import summarize
from app.llm.provider import ProviderResponse
from app.search.ask_summary import sample
from tests.integration.test_ask import INJECTION, answer, ask, lab, login  # noqa: F401  # fixture

SQL = "SELECT event_id, message FROM events ORDER BY time"


def _said(claims: list[dict[str, Any]]) -> ProviderResponse:
    return ProviderResponse(text=json.dumps({"claims": claims}), model="m")


def _audit(lab: dict[str, Any], action: str) -> list[dict[str, Any]]:  # noqa: F811
    db = sqlite3.connect(lab["tmp"] / "data" / "meta.sqlite")
    rows = db.execute(
        "SELECT detail FROM audit_log WHERE action = ? ORDER BY audit_id", (action,)
    ).fetchall()
    return [json.loads(r[0]) for r in rows]


def _ran(lab: dict[str, Any], sql: str = SQL) -> tuple[Any, str, dict[str, Any]]:  # noqa: F811
    lab["script"].replies = [answer(sql)]
    ana = login(lab, "ana")
    ask_id = ask(ana).json()["ask_id"]
    out = ana.post(f"/api/ask/{ask_id}/run").json()
    return ana, ask_id, out


def test_cited_statements_stay_and_uncited_ones_are_removed(lab: dict[str, Any]) -> None:  # noqa: F811
    ana, ask_id, out = _ran(lab)
    assert out["headline"].startswith("8 rows. First row: message ")
    assert out["summarize"] is True and out["summary_note"] is None
    first, second = out["rows"][0][0], out["rows"][1][0]
    lab["script"].replies = [
        _said(
            [
                {"text": "The first event asks for a table to be dropped.", "event_ids": [first]},
                {"text": "Nothing else happened.", "event_ids": []},
                {"text": "Made up.", "event_ids": ["0190a1b2-0000-7000-8000-00000000ffff"]},
                {"text": "Two firewall events.", "event_ids": [first.upper(), second]},
            ]
        )
    ]
    res = ana.post(f"/api/ask/{ask_id}/answer")
    assert res.status_code == 200, res.text
    got = res.json()
    assert [c["text"] for c in got["claims"]] == [
        "The first event asks for a table to be dropped.",
        "Two firewall events.",
    ]
    assert got["claims"][1]["event_ids"] == [first, second]
    assert got["removed"] == 2
    assert got["note"] == "2 statements removed: they cited no events from these rows."
    assert got["headline"] == out["headline"]
    # The rows went under `data`, the injection with them, and only ana's source.
    sent = lab["script"].seen[-1]
    assert "summarize the result of a query" in sent[0].content
    body = json.loads(sent[-1].content)
    assert set(body) == {"data"} and INJECTION in json.dumps(body)
    assert sent[-1].data_sources == ("fw_edge",)
    (row,) = _audit(lab, "ask.answer")
    assert row["kept"] == 2 and row["removed"] == 2 and row["ask_id"] == ask_id
    db = sqlite3.connect(lab["tmp"] / "data" / "meta.sqlite")
    purpose, prompt = db.execute(
        "SELECT purpose, prompt_ref FROM llm_calls WHERE call_id = ?", (got["call_id"],)
    ).fetchone()
    assert purpose == "ask" and prompt.startswith("ask_answer.v1")


def test_when_nothing_cites_there_is_no_summary(lab: dict[str, Any]) -> None:  # noqa: F811
    ana, ask_id, _ = _ran(lab)
    lab["script"].replies = [_said([{"text": "All fine.", "event_ids": []}])]
    got = ana.post(f"/api/ask/{ask_id}/answer").json()
    assert got["claims"] == [] and got["removed"] == 1
    assert got["note"] == "No summary: the model's statements did not cite these rows."


def test_a_bad_reply_leaves_the_rows_without_a_summary(lab: dict[str, Any]) -> None:  # noqa: F811
    ana, ask_id, _ = _ran(lab)
    bad = ProviderResponse(text="Here is my summary: all good", model="m")
    lab["script"].replies = [bad, bad]
    res = ana.post(f"/api/ask/{ask_id}/answer")
    assert res.status_code == 200
    assert res.json()["claims"] == [] and res.json()["note"].startswith("No summary: ")
    assert _audit(lab, "ask.answer")[0]["error"]


def test_rows_without_event_ids_get_only_the_headline(lab: dict[str, Any]) -> None:  # noqa: F811
    calls = len(lab["script"].seen)
    ana, ask_id, out = _ran(lab, "SELECT source_id, count(*) AS events FROM events GROUP BY 1")
    assert out["headline"] == "source_id: fw_edge; events: 8"
    assert out["summarize"] is False
    assert out["summary_note"] == "No summary: these rows have no event ids to cite."
    after_run = len(lab["script"].seen)
    got = ana.post(f"/api/ask/{ask_id}/answer").json()
    assert got["claims"] == [] and got["call_id"] is None
    assert len(lab["script"].seen) == after_run > calls  # no model call for the answer


def test_summaries_off_means_no_model_call_after_the_query(lab: dict[str, Any]) -> None:  # noqa: F811
    lab["app"].state.config.ask.summarize = False
    ana, ask_id, out = _ran(lab)
    assert out["summarize"] is False and out["summary_note"] is None and out["headline"]
    assert ana.post(f"/api/ask/{ask_id}/answer").status_code >= 400
    assert _audit(lab, "ask.answer") == []


def test_only_the_asker_and_only_after_the_run(lab: dict[str, Any]) -> None:  # noqa: F811
    lab["script"].replies = [answer(SQL)]
    ana = login(lab, "ana")
    ask_id = ask(ana).json()["ask_id"]
    assert ana.post(f"/api/ask/{ask_id}/answer").status_code == 404  # not run yet
    ana.post(f"/api/ask/{ask_id}/run")
    assert lab["admin"].post(f"/api/ask/{ask_id}/answer", headers=lab["h"]).status_code == 404


def test_a_cloud_model_never_summarizes_local_only_rows(lab: dict[str, Any]) -> None:  # noqa: F811
    store = lab["app"].state.providers
    cloud = store.add("Cloud", "https://203.0.113.10/v1", "m", None)
    store.update(cloud.provider_id, None, None, None, True, None, False)
    rows = sample(["event_id", "message"], [["0190a1b2-0000-7000-8000-00000000000a", "x"]], False)
    assert rows is not None
    db = sqlite3.connect(lab["tmp"] / "data" / "meta.sqlite")
    (admin_id,) = db.execute("SELECT user_id FROM users WHERE username = 'admin'").fetchone()
    with pytest.raises(ClassificationBlockedError):
        summarize(lab["app"].state.gate, admin_id, cloud.provider_id, "q", rows, ["hr_payroll"])
