"""The Ask accuracy harness itself is correct (SPEC 5.7).

A model is not available in CI, so these tests prove the harness: every reference query
runs on the fixture, an oracle that answers with the reference scores 100 percent, and a
model that answers wrongly scores 0 percent exact while staying executable.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from app.llm.locality import Endpoint
from app.llm.provider import ChatMessage, ProviderResponse
from app.llm.registry import ProviderRecord, ProviderStore
from evals.nl_queries.compare import matches
from evals.nl_queries.fixture import build_rows
from evals.nl_queries.run import build_lab, load_suite, run_case, summarise

CASES, SCOPE = load_suite()
BY_QUESTION = {c.question: c.sql for c in CASES}


def test_suite_has_106_questions_and_10_follow_ups() -> None:
    assert len(CASES) == 116
    assert len({c.id for c in CASES}) == 116
    assert len(BY_QUESTION) == 116
    assert sum(1 for c in CASES if c.history) == 9  # f006 names a person with no history


def test_fixture_is_deterministic_and_synthetic() -> None:
    a, b = build_rows(), build_rows()
    assert [r["raw"] for r in a] == [r["raw"] for r in b]
    ips = {r[k] for r in a for k in ("src_endpoint_ip", "dst_endpoint_ip") if r[k]}
    allowed = ("10.", "192.0.2.", "198.51.100.", "203.0.113.")
    assert all(ip.startswith(allowed) for ip in ips), ips


@pytest.fixture(scope="module")
def lab(tmp_path_factory: pytest.TempPathFactory) -> Any:
    return build_lab(Path(tmp_path_factory.mktemp("eval")))


def test_every_reference_query_returns_rows_and_matches_itself(lab: Any) -> None:
    for case in CASES:
        res = lab.state.engine.run(case.sql, SCOPE)
        assert res.rows, case.id
        assert not res.truncated, case.id
        width = len(res.columns)
        assert matches(res.rows, width, res.rows, width, case.compare), case.id


def _provider(lab: Any, answer_for: Any) -> str:
    class Fake:
        def __init__(self, record: ProviderRecord, endpoint: Endpoint) -> None:
            self.provider_id, self.locality = record.provider_id, endpoint.locality

        def chat(self, messages: list[ChatMessage], **_: object) -> ProviderResponse:
            question = next(
                m.content.removeprefix("Question: ")
                for m in reversed(messages)
                if m.role == "user" and m.content.startswith("Question: ")
            )
            body = {"sql": answer_for(question), "explanation": "", "assumptions": []}
            return ProviderResponse(text=json.dumps(body), model="fake")

    lab.state.gate._factory = lambda r, _s, e: Fake(r, e)
    store: ProviderStore = lab.state.providers
    rec = store.add(f"fake-{id(answer_for)}", "http://127.0.0.1:1/v1", "fake", None)
    store.update(rec.provider_id, None, None, None, True, None, False)
    return rec.provider_id


def test_oracle_scores_100_percent_through_the_real_agent(lab: Any) -> None:
    pid = _provider(lab, lambda q: BY_QUESTION[q])
    sample = CASES[::10]  # every Ask runs profile queries; a sample keeps CI fast
    results = [run_case(lab.state.ask, lab.state.engine, pid, SCOPE, c) for c in sample]
    summary = summarise(results, "oracle")
    misses = [r.id for r in results if not r.exact]
    assert misses == []
    assert summary["exact_rate"] == 1.0 and summary["executable_rate"] == 1.0


def test_follow_ups_send_the_earlier_turns_and_the_oracle_passes(lab: Any) -> None:
    seen: list[str] = []

    def answer(question: str) -> str:
        return BY_QUESTION[question]

    pid = _provider(lab, answer)
    fake = lab.state.gate._factory

    def spy(r: Any, s: Any, e: Any) -> Any:
        inner = fake(r, s, e)
        original = inner.chat

        def chat(messages: list[ChatMessage], **kw: object) -> ProviderResponse:
            seen.append("\n".join(m.content for m in messages))
            return original(messages, **kw)

        inner.chat = chat
        return inner

    lab.state.gate._factory = spy
    follow = [c for c in CASES if c.id.startswith("f")]
    results = [run_case(lab.state.ask, lab.state.engine, pid, SCOPE, c) for c in follow]
    assert [r.id for r in results if not r.exact] == []
    f010 = next(m for m in seen if "Just the top 3." in m)
    assert "Break that down by source IP." in f010 and "GROUP BY 1" in f010


def test_a_wrong_model_scores_zero_but_runs(lab: Any) -> None:
    pid = _provider(lab, lambda q: "SELECT 'wrong' AS answer")
    sample = CASES[1::10]
    results = [run_case(lab.state.ask, lab.state.engine, pid, SCOPE, c) for c in sample]
    assert all(r.executable and not r.exact for r in results)


# --- comparison rules ------------------------------------------------------------------


def test_extra_columns_order_and_aliases_do_not_matter() -> None:
    ref = [["203.0.113.9", 120], ["198.51.100.23", 60]]
    got = [[60, "198.51.100.23", "x"], [120, "203.0.113.9", "y"]]
    assert matches(ref, 2, got, 3, "set")
    assert not matches(ref, 2, got, 3, "ordered")
    assert matches(ref, 2, list(reversed(got)), 3, "ordered")


def test_missing_or_extra_rows_fail() -> None:
    ref = [["a", 1], ["b", 2]]
    assert not matches(ref, 2, [["a", 1]], 2, "set")
    assert not matches(ref, 2, [["a", 1], ["b", 2], ["c", 3]], 2, "set")
    assert not matches(ref, 2, [["a", 1], ["b", 3]], 2, "set")


def test_equivalent_spellings_compare_equal() -> None:
    assert matches([["2026-10-01", 3]], 2, [["2026-10-01T00:00:00+00:00", 3.0]], 2, "set")
    assert matches([[0.33333333]], 1, [[0.333333]], 1, "set")
    assert not matches([["2026-10-01T05:00:00+00:00"]], 1, [["2026-10-01"]], 1, "set")


def test_all_null_rows_are_ignored() -> None:
    assert matches([["bastion"], ["db-01"]], 2 - 1, [["bastion"], [None], ["db-01"]], 1, "set")
