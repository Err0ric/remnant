"""Ask as a background job (D269) with a time limit per model call (D270).

The owner's report (2026-11-17): a CPU-only model took 220 s for one Ask, a reverse proxy
gave up at about 120 s, and the page said it could not reach the server. Here the model
is a fake behind the real gate that takes as long as it is told, stopping at the gate's
deadline the way the HTTP client does (tests/unit/test_gate_timeout.py tests the real
client). No request may block: submit and status are timed.
"""

import json
import sqlite3
import time
from collections.abc import Callable
from typing import Any

import pytest

from app.api.ask import SQL_TIMED_OUT, SUMMARY_TIMED_OUT
from app.core.errors import ModelTimeoutError
from app.llm.locality import Endpoint
from app.llm.provider import ChatMessage, ProviderResponse
from app.llm.provider_http import deadline_left
from app.llm.registry import ProviderRecord, ProviderStore
from tests.integration.test_ask import (  # noqa: F401  # fixture
    ROUTE_PROMPT,
    USER_PW,
    answer,
    lab,
    login,
)

SQL = "SELECT event_id, message FROM events ORDER BY time"
SUMMARY_PROMPT = "summarize the result of a query"
FAST_S = 1.0  # the longest a submit or a status call may take here


def _said(event_id: str) -> ProviderResponse:
    claims = [{"text": "The first event asks for a table to be dropped.", "event_ids": [event_id]}]
    return ProviderResponse(text=json.dumps({"claims": claims}), model="m")


def _slow(lab: dict[str, Any], sql_s: float = 0.0, summary_s: float = 0.0) -> None:  # noqa: F811
    """The SQL and summary calls take this long; routing answers at once."""
    inner = lab["app"].state.gate._factory

    def factory(record: ProviderRecord, store: ProviderStore, endpoint: Endpoint) -> Any:
        fake = inner(record, store, endpoint)

        class Slow:
            provider_id, locality = fake.provider_id, fake.locality

            def chat(self, messages: list[ChatMessage], **kw: Any) -> ProviderResponse:
                head = messages[0].content
                wait = (
                    0.0 if ROUTE_PROMPT in head else summary_s if SUMMARY_PROMPT in head else sql_s
                )
                left = deadline_left()
                if left is not None and left < wait:
                    time.sleep(max(left, 0))
                    raise ModelTimeoutError("The model took too long to answer.")
                time.sleep(wait)
                return fake.chat(messages, **kw)  # type: ignore[no-any-return]  # test double

            def models(self) -> list[str]:
                return ["m"]

        return Slow()

    lab["app"].state.gate._factory = factory


def _timed(call: Callable[[], Any]) -> Any:
    t0 = time.monotonic()
    res = call()
    assert time.monotonic() - t0 < FAST_S, "a request blocked on the model"
    return res


def _until(c: Any, job_id: str, done: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    end = time.monotonic() + 10
    while time.monotonic() < end:
        res = _timed(lambda: c.get(f"/api/ask/jobs/{job_id}"))
        assert res.status_code == 200, res.text  # never a 5xx, failed or not
        body: dict[str, Any] = res.json()
        if done(body):
            return body
        time.sleep(0.02)
    raise AssertionError("the job did not get there in time")


def _submit(c: Any, **body: object) -> dict[str, Any]:
    res = _timed(lambda: c.post("/api/ask/jobs", json={"question": "events by host", **body}))
    assert res.status_code == 202, res.text
    out: dict[str, Any] = res.json()
    return out


def _audit(lab: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:  # noqa: F811
    db = sqlite3.connect(lab["tmp"] / "data" / "meta.sqlite")
    rows = db.execute("SELECT action, outcome, detail FROM audit_log ORDER BY audit_id")
    return [(a, o, json.loads(d or "{}")) for a, o, d in rows.fetchall()]


def _llm_errors(lab: dict[str, Any]) -> list[str | None]:  # noqa: F811
    db = sqlite3.connect(lab["tmp"] / "data" / "meta.sqlite")
    rows = db.execute("SELECT prompt_ref, error FROM llm_calls ORDER BY ts").fetchall()
    return [e for p, e in rows if not p.startswith("ask_route")]


def test_rows_come_first_and_the_summary_after(lab: dict[str, Any]) -> None:  # noqa: F811
    lab["app"].state.gate.model_timeout_s = 5
    _slow(lab, summary_s=1.5)
    lab["script"].replies = [answer(SQL)]
    ana = login(lab, "ana")
    job = _submit(ana)
    assert job["state"] == "running" and job["result"] is None
    mid = _until(ana, job["job_id"], lambda b: b["result"] is not None)
    assert mid["state"] == "running" and mid["summary"] is None
    assert [(s["name"], s["state"]) for s in mid["steps"]] == [
        ("sql", "done"),
        ("run", "done"),
        ("summary", "running"),
    ]
    assert mid["ask"]["sql"] == SQL and mid["ask"]["check"] == "ok"
    assert mid["result"]["row_count"] == 8 and mid["result"]["headline"]
    first = mid["result"]["rows"][0][0]
    lab["script"].replies = [_said(first)]
    end = _until(ana, job["job_id"], lambda b: b["state"] != "running")
    assert end["state"] == "done" and end["error"] is None
    assert end["summary"]["claims"][0]["event_ids"] == [first]
    assert all(s["ms"] is not None for s in end["steps"])
    # The same audit rows as the three synchronous calls (rule 14).
    actions = [(a, o) for a, o, _ in _audit(lab) if a.startswith(("ask.", "query."))]
    assert actions == [
        ("ask.request", "success"),
        ("query.run", "success"),
        ("ask.answer", "success"),
    ]
    run = next(d for a, _, d in _audit(lab) if a == "query.run")
    assert run["purpose"] == "ask" and run["ask_id"] == end["ask"]["ask_id"]


def test_a_slow_query_call_times_out_cleanly(lab: dict[str, Any]) -> None:  # noqa: F811
    lab["app"].state.gate.model_timeout_s = 0.5
    _slow(lab, sql_s=200)
    ana = login(lab, "ana")
    job = _submit(ana)
    end = _until(ana, job["job_id"], lambda b: b["state"] != "running")
    assert end["state"] == "failed" and end["result"] is None
    assert end["error"] == {"code": "model_timeout", "message": SQL_TIMED_OUT}
    assert [(s["name"], s["state"]) for s in end["steps"]] == [("sql", "timed_out")]
    assert _llm_errors(lab) == ["timeout"]
    (req,) = [(o, d) for a, o, d in _audit(lab) if a == "ask.request"]
    assert req[0] == "failure" and req[1]["error"] == "ModelTimeoutError"
    # The person may ask again at once: the job gave back their turn.
    _until(ana, _submit(ana)["job_id"], lambda b: b["state"] != "running")


def test_a_slow_summary_times_out_and_the_rows_stay(lab: dict[str, Any]) -> None:  # noqa: F811
    lab["app"].state.gate.model_timeout_s = 0.5
    _slow(lab, summary_s=200)
    lab["script"].replies = [answer(SQL)]
    ana = login(lab, "ana")
    end = _until(ana, _submit(ana)["job_id"], lambda b: b["state"] != "running")
    assert end["state"] == "done" and end["error"] is None
    assert end["result"]["row_count"] == 8 and end["ask"]["sql"] == SQL
    assert end["steps"][-1]["name"] == "summary" and end["steps"][-1]["state"] == "timed_out"
    assert end["summary"]["note"] == SUMMARY_TIMED_OUT and end["summary"]["timed_out"] is True
    assert end["summary"]["claims"] == []
    assert _llm_errors(lab) == [None, "timeout"]
    (row,) = [(o, d) for a, o, d in _audit(lab) if a == "ask.answer"]
    assert row[0] == "failure" and row[1]["error"] == "ModelTimeoutError"


def test_the_synchronous_calls_also_stop_at_the_limit(lab: dict[str, Any]) -> None:  # noqa: F811
    lab["app"].state.gate.model_timeout_s = 0.5
    _slow(lab, sql_s=200)
    res = login(lab, "ana").post("/api/ask", json={"question": "events by host"})
    assert res.status_code == 504
    assert res.json() == {"detail": SQL_TIMED_OUT, "code": "model_timeout"}


def test_nobody_else_can_read_a_job(lab: dict[str, Any]) -> None:  # noqa: F811
    lab["script"].replies = [answer(SQL), _said("0190a1b2-0000-7000-8000-00000000ffff")]
    ana = login(lab, "ana")
    job_id = _submit(ana)["job_id"]
    _until(ana, job_id, lambda b: b["state"] != "running")
    res = lab["admin"].post(
        "/api/users", json={"username": "bob", "role": "analyst"}, headers=lab["h"]
    )
    lab["admin"].post(
        "/api/account/password", json={"token": res.json()["invite_token"], "password": USER_PW}
    )
    assert login(lab, "bob").get(f"/api/ask/jobs/{job_id}").status_code == 404
    assert lab["admin"].get(f"/api/ask/jobs/{job_id}").status_code == 404  # admins too
    assert login(lab, "aud").get(f"/api/ask/jobs/{job_id}").status_code in (403, 404)
    assert ana.get("/api/ask/jobs/not-a-job").status_code == 404


def test_click_to_run_stops_after_the_sql_and_the_click_is_a_job(lab: dict[str, Any]) -> None:  # noqa: F811
    lab["app"].state.config.ask.auto_run = False
    lab["script"].replies = [answer(SQL)]
    ana = login(lab, "ana")
    end = _until(ana, _submit(ana)["job_id"], lambda b: b["state"] != "running")
    assert end["state"] == "done" and end["ask"]["auto_run"] is False and end["result"] is None
    assert [s["name"] for s in end["steps"]] == ["sql"]
    ask_id = end["ask"]["ask_id"]
    assert login(lab, "aud").post(f"/api/ask/{ask_id}/jobs").status_code in (403, 404)
    lab["script"].replies = [_said("0190a1b2-0000-7000-8000-00000000ffff")]
    res = _timed(lambda: ana.post(f"/api/ask/{ask_id}/jobs"))
    assert res.status_code == 202, res.text
    ran = _until(ana, res.json()["job_id"], lambda b: b["state"] != "running")
    assert [s["name"] for s in ran["steps"]] == ["run", "summary"]
    assert ran["result"]["row_count"] == 8


def test_one_question_at_a_time_per_person(lab: dict[str, Any]) -> None:  # noqa: F811
    lab["app"].state.gate.model_timeout_s = 1
    _slow(lab, sql_s=200)
    ana = login(lab, "ana")
    job_id = _submit(ana)["job_id"]
    res = ana.post("/api/ask/jobs", json={"question": "events by host"})
    assert res.status_code == 429
    _until(ana, job_id, lambda b: b["state"] != "running")


@pytest.mark.parametrize("path", ["/api/ask/jobs"])
def test_a_provider_problem_is_said_at_submit(lab: dict[str, Any], path: str) -> None:  # noqa: F811
    res = login(lab, "ana").post(path, json={"question": "q", "provider_id": "nope"})
    assert res.status_code == 400 and res.json()["code"] == "provider_invalid"


def test_once_a_job_shows_finished_the_person_may_ask_again_at_once(lab: dict[str, Any]) -> None:  # noqa: F811
    counts = "SELECT source_id, count(*) AS n FROM events GROUP BY 1"  # no summary step
    lab["script"].replies = [answer(counts) for _ in range(15)]
    ana = login(lab, "ana")
    job_id = _submit(ana)["job_id"]
    for _ in range(14):
        _until(ana, job_id, lambda b: b["state"] != "running")
        job_id = _submit(ana)["job_id"]  # a 429 here fails: the turn came back first
    _until(ana, job_id, lambda b: b["state"] != "running")
