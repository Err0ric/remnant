"""The ai_agents answer cases (evals/nl_queries/ai_agents_answers.yaml; owner, 2026-11-04):
routing picks the query, and the answer counts people, not accounts or test records."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.ingest.records import DecodedLine
from app.ingest.writer import LakeWriter
from app.main import create_app
from app.search.ask_route import rank
from app.search.ask_summary import headline
from app.search.library import LIBRARY_DIR, Library, load_dir
from app.templates.loader import parse_template
from app.templates.runtime import TemplateNormalizer
from tests.integration.test_person_placeholder import RANGE, ROOT, _hook

SUITE = yaml.safe_load(
    (Path(__file__).resolve().parents[2] / "evals" / "nl_queries" / "ai_agents_answers.yaml")
    .read_text()
)  # fmt: skip
LIB = Library(load_dir(LIBRARY_DIR))
SEEN = {t for p in LIB.packs for q in p.queries for t in q.requires}


def _line(r: dict[str, Any]) -> str:
    if r.get("test"):
        return _hook(r["time"], r["session"], None, test_record="true", plugin_variant="doctor")
    extra = {"claude_account_email": r["account"]} if r.get("account") else {}
    return _hook(r["time"], r["session"], r["host"], **extra)


@pytest.fixture
def app(tmp_path: Path) -> Any:
    config = load_config(Path("missing.yaml"), {"APP__PATHS__DATA_DIR": str(tmp_path / "d")})
    app = create_app(config)
    spec = parse_template((ROOT / "templates" / "starter" / "claude_hooks.yaml").read_text())
    norm = TemplateNormalizer(spec, "claude_hooks")
    LakeWriter(app.state.engine._lake).write([
        norm.normalize(DecodedLine(text=_line(r), bytes_invalid=False, truncated=False))
        for r in SUITE["records"]
    ])  # fmt: skip
    app.state.identities.set_domains(SUITE["domains"], "admin")
    return app


@pytest.mark.parametrize("case", SUITE["cases"], ids=[c["id"] for c in SUITE["cases"]])
def test_answer(case: dict[str, Any], app: Any) -> None:
    top = rank(case["question"], LIB, SEEN)
    assert top and top[0].ref == case["library"], [(c.ref, c.score) for c in top[:3]]
    q = top[0].query
    for alias, person in case["links"].items():
        app.state.identities.set_alias(alias, person, "admin")
    res = TestClient(app).post("/api/query", json={"sql": q.sql, **RANGE})
    assert res.status_code == 200, res.text
    cols, rows = res.json()["columns"], res.json()["rows"]
    assert headline(cols, rows, False, q.answer) == case["headline"]
    people = [r[cols.index("person")] for r in rows]
    assert sorted(people) == sorted(case["people"]) and all(people)
    for person, accounts in case.get("accounts", {}).items():
        assert next(r for r in rows if r[0] == person)[cols.index("accounts")] == accounts
