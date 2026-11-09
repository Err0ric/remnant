"""Owner, 2026-11-08 (handoff item 1): a library question never waits on the model.

On a CPU-only local model, "who uses claude code" spent about 25 s in the routing call
before the library answer appeared. Code now matches the question to the library first;
the routing call is made only when no library query is a confident match, exactly as
before. A library answer is still audited as an Ask, with no model call."""

import json
import sqlite3
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.ingest.records import DecodedLine
from app.ingest.writer import LakeWriter
from app.llm.locality import Endpoint
from app.llm.provider import ProviderResponse
from app.llm.registry import ProviderRecord, ProviderStore
from app.main import create_app
from app.templates.loader import parse_template
from app.templates.runtime import TemplateNormalizer
from tests.integration.test_ask_routing import ROUTE_PROMPT
from tests.integration.test_ask_routing import lab as lab  # the fixture
from tests.integration.test_person_placeholder import LINES, ROOT

SLOW_S = 30.0  # a provider that never answers in time: CPU-only, or not reachable at all


class Sleepy:
    """A provider that takes 30 s to answer anything, and counts the calls it got."""

    def __init__(self, record: ProviderRecord, endpoint: Endpoint, seen: list[str]) -> None:
        self.provider_id, self.locality, self.seen = record.provider_id, endpoint.locality, seen

    def chat(self, messages: list[Any], *_: object, **__: object) -> ProviderResponse:
        self.seen.append(messages[0].content)
        threading.Event().wait(SLOW_S)
        return ProviderResponse(text=json.dumps({"kind": "data", "query": None}), model="m")


def _slow(app: Any) -> list[str]:
    seen: list[str] = []
    app.state.gate._factory = lambda r, _s, e: Sleepy(r, e, seen)
    store: ProviderStore = app.state.providers
    local = store.all()[0]
    store.update(local.provider_id, None, "http://127.0.0.1:9/v1", "m", True, None, False)
    return seen


@pytest.fixture
def hooks(tmp_path: Path, pin_now: Callable[[datetime], None]) -> dict[str, Any]:
    """Claude Code hooks records (synthetic) on a loopback install, with a slow model."""
    pin_now(datetime(2026, 10, 26, 12, 0, tzinfo=UTC))
    config = load_config(Path("missing.yaml"), {"APP__PATHS__DATA_DIR": str(tmp_path / "d")})
    app = create_app(config)
    spec = parse_template((ROOT / "templates" / "starter" / "claude_hooks.yaml").read_text())
    norm = TemplateNormalizer(spec, "claude_hooks")
    LakeWriter(app.state.engine._lake).write(
        [norm.normalize(DecodedLine(text=x, bytes_invalid=False, truncated=False)) for x in LINES]
    )
    app.state.identities.set_domains(["example.com"], "admin")
    return {
        "app": app,
        "c": TestClient(app),
        "seen": _slow(app),
        "db": config.paths.data_dir / "meta.sqlite",
    }


def _timed(c: TestClient, question: str) -> tuple[dict[str, Any], float]:
    t0 = time.monotonic()
    res = c.post("/api/ask", json={"question": question, "tz": "UTC"})
    took = time.monotonic() - t0
    assert res.status_code == 200, res.text
    out: dict[str, Any] = res.json()
    return out, took


def _asks(db: Path) -> list[dict[str, Any]]:
    """Ask audit rows' details; `db` is the meta database file."""
    rows = sqlite3.connect(db).execute(
        "SELECT detail FROM audit_log WHERE action = 'ask.request' AND outcome = 'success'"
    )
    return [json.loads(d) for (d,) in rows]


@pytest.mark.parametrize(
    "question",
    ["who uses claude code", "Who uses Claude Code?", "Which people are using coding agents?"],
)
def test_a_library_question_answers_without_the_model(hooks: dict[str, Any], question: str) -> None:
    body, took = _timed(hooks["c"], question)
    assert took < 2.0, took
    assert hooks["seen"] == []  # the routing call was never made
    route = body["route"]
    assert route["kind"] == "data" and route["by"] == "library"
    assert route["library"]["ref"] == "ai_agents/agents_claude_code_users"
    assert body["check"] == "library" and body["call_ids"] == []
    # Audited as an Ask, with the library query it used and no model call.
    (detail,) = _asks(hooks["db"])
    # Which route answered, for comparing the two on real data (owner, 2026-11-08 22:28).
    assert detail["route"]["via"] == "library" and detail["call_ids"] == []
    assert detail["route"]["library"] == "ai_agents/agents_claude_code_users@1.1.0"
    assert isinstance(detail["route"]["ms"], int) and 0 <= detail["route"]["ms"] < 2000
    assert detail["ask_id"] == body["ask_id"]
    run = hooks["c"].post(f"/api/ask/{body['ask_id']}/run")
    assert run.status_code == 200, run.text
    assert {r[0] for r in run.json()["rows"]} >= {"dana", "erin"}


def test_a_natural_phrasing_on_an_analysts_view_skips_the_model(lab: dict[str, Any]) -> None:
    """ "Failed SSH logins by IP" in other words: the same words once synonyms are read."""
    seen = _slow(lab["app"])
    t0 = time.monotonic()
    res = lab["ana"].post("/api/ask", json={"question": "failed ssh logins by source address"})
    assert res.status_code == 200, res.text
    assert time.monotonic() - t0 < 2.0
    assert seen == []
    assert res.json()["route"]["library"]["ref"] == "linux_auth/ssh_failures_by_source"


def _routes(lab: dict[str, Any]) -> int:
    return sum(1 for m in lab["calls"]["seen"] if ROUTE_PROMPT in m[0].content)


def test_a_library_miss_still_calls_the_router_once(lab: dict[str, Any]) -> None:
    body = lab["ana"].post("/api/ask", json={"question": "how many events per user"}).json()
    assert _routes(lab) == 1
    assert body["route"]["by"] == "model" and body["route"]["library"] is None
    assert len(body["call_ids"]) == 2  # the route and the SQL, as before
    (detail,) = _asks(lab["db"])
    assert detail["route"]["via"] == "model" and detail["route"]["library"] is None
    assert isinstance(detail["route"]["ms"], int)


@pytest.mark.parametrize(
    "question",
    [
        # Every word of a sudo_denied example, but not "denied": all sudo events, not refusals.
        "How many sudo events are there?",
        # "internal" is a filter the shipped query does not apply (0.8 of the words).
        "Which internal addresses had failed SSH logins?",
        # Shaped like general guidance: the model decides, as before.
        "How do I find who used sudo?",
    ],
)
def test_a_near_miss_is_left_to_the_router(lab: dict[str, Any], question: str) -> None:
    body = lab["ana"].post("/api/ask", json={"question": question}).json()
    assert _routes(lab) == 1
    assert body["route"]["by"] == "model" and body["route"]["library"] is None
