"""ADR-0042 slice 1a (owner, 2026-11-02): Ask runs the SQL an answer produced, by its id,
for the person who asked, through the guard on their own view, capped, and audited like
any query with purpose `ask`. `ask.auto_run` off keeps click-to-run."""

import json
import sqlite3
from typing import Any

import pytest

from app.api import ask as ask_api
from tests.integration.test_ask import SQL, answer, ask, lab, login  # noqa: F401  # fixture


def _runs(lab: dict[str, Any]) -> list[dict[str, Any]]:  # noqa: F811
    db = sqlite3.connect(lab["tmp"] / "data" / "meta.sqlite")
    rows = db.execute(
        "SELECT detail FROM audit_log WHERE action = 'query.run' ORDER BY audit_id"
    ).fetchall()
    return [json.loads(r[0]) for r in rows]


def test_an_answer_runs_on_the_askers_view_and_is_audited(lab: dict[str, Any]) -> None:  # noqa: F811
    lab["script"].replies = [answer(SQL)]
    ana = login(lab, "ana")
    body = ask(ana).json()
    assert body["auto_run"] is True and body["ask_id"]
    res = ana.post(f"/api/ask/{body['ask_id']}/run")
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["sources"] == ["fw_edge"]  # ana's group only; hr_payroll is not hers
    assert out["rows"]
    (run,) = _runs(lab)
    assert run["purpose"] == "ask" and run["origin"] == "generated"
    assert run["ask_id"] == body["ask_id"] and run["ask_call_ids"] == body["call_ids"]
    assert run["sql"] == SQL


def test_only_the_asker_can_run_an_answer(lab: dict[str, Any]) -> None:  # noqa: F811
    lab["script"].replies = [answer(SQL)]
    ask_id = ask(login(lab, "ana")).json()["ask_id"]
    assert lab["admin"].post(f"/api/ask/{ask_id}/run", headers=lab["h"]).status_code == 404
    assert login(lab, "aud").post(f"/api/ask/{ask_id}/run").status_code == 403
    assert login(lab, "ana").post("/api/ask/not-an-id/run").status_code == 404


def test_auto_run_off_still_runs_on_click(lab: dict[str, Any]) -> None:  # noqa: F811
    lab["app"].state.config.ask.auto_run = False
    lab["script"].replies = [answer(SQL)]
    ana = login(lab, "ana")
    body = ask(ana).json()
    assert body["auto_run"] is False
    assert _runs(lab) == []  # nothing ran by itself
    assert ana.post(f"/api/ask/{body['ask_id']}/run").status_code == 200


def test_a_failed_self_check_never_runs_by_itself(lab: dict[str, Any]) -> None:  # noqa: F811
    bad = "SELECT nope FROM events"
    lab["script"].replies = [answer(bad), answer(bad), answer(bad)]
    body = ask(login(lab, "ana")).json()
    assert body["check"] == "failed" and body["auto_run"] is False


def test_rows_are_capped_and_the_range_is_at_most_90_days(
    lab: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ask_api, "ASK_ROWS", 3)
    lab["script"].replies = [answer("SELECT event_id FROM events")]
    ana = login(lab, "ana")
    ask_id = ask(ana).json()["ask_id"]  # no start: Ask reads at most 90 days
    out = ana.post(f"/api/ask/{ask_id}/run").json()
    assert out["row_count"] == 3 and out["truncated"] is True
    (run,) = _runs(lab)
    assert run["rows"] == 3
