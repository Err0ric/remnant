"""`remnant ask`: prints the model's SQL and runs it only on an explicit yes (SPEC 5.6, T17)."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from app.cli import main as cli
from app.cli.client import Credentials
from app.core.config import load_config
from app.ingest.normalizer import Normalizer, SourceSpec
from app.ingest.records import DecodedLine
from app.ingest.writer import LakeWriter
from app.llm.locality import Endpoint
from app.llm.provider import ProviderResponse
from app.llm.registry import ProviderRecord, ProviderStore
from app.main import create_app

SQL = "SELECT source_id,\n  count(*) AS n\nFROM events GROUP BY 1"


@pytest.fixture
def lab(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    norm = Normalizer(
        SourceSpec(source_id="fw_edge", format="json"),
        clock=lambda: datetime.now(UTC),
    )
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = norm.normalize(
        DecodedLine(text=json.dumps({"time": now, "m": "x"}), bytes_invalid=False, truncated=False)
    )
    assert row is not None
    LakeWriter(tmp_path / "lake").write([row])
    app = create_app(load_config(Path("missing.yaml"), {"APP__PATHS__DATA_DIR": str(tmp_path)}))
    replies: list[ProviderResponse] = []

    class Fake:
        def __init__(self, record: ProviderRecord, endpoint: Endpoint) -> None:
            self.provider_id, self.locality = record.provider_id, endpoint.locality

        def chat(self, *_: object, **__: object) -> ProviderResponse:
            return replies.pop(0)

    app.state.gate._factory = lambda r, _s, e: Fake(r, e)
    store: ProviderStore = app.state.providers
    local = store.all()[0]
    store.update(local.provider_id, None, "http://127.0.0.1:11434/v1", "m", True, None, False)

    def factory(_: Credentials) -> TestClient:
        return TestClient(app)

    monkeypatch.setattr(cli, "client_factory", factory)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("REMNANT_TOKEN", raising=False)
    monkeypatch.delenv("REMNANT_SERVER", raising=False)
    return {"app": app, "replies": replies, "runner": CliRunner()}


def reply(lab: dict[str, Any], sql: str = SQL, explanation: str = "Counts per source.") -> None:
    body = {"sql": sql, "explanation": explanation, "assumptions": ["all sources"]}
    lab["replies"].append(ProviderResponse(text=json.dumps(body), model="m"))


def invoke(lab: dict[str, Any], *args: str, answer: str = "\n") -> Any:
    return lab["runner"].invoke(cli.app, ["ask", *args], input=answer)


def query_runs(lab: dict[str, Any]) -> int:
    import sqlite3

    db = sqlite3.connect(lab["app"].state.config.paths.data_dir / "meta.sqlite")
    return int(
        db.execute("SELECT count(*) FROM audit_log WHERE action = 'query.run'").fetchone()[0]
    )


def test_prints_sql_and_does_not_run_by_default(lab: dict[str, Any]) -> None:
    reply(lab)
    res = invoke(lab, "events per source")  # just Enter at the prompt
    assert res.exit_code == 0
    assert SQL in res.stdout
    assert "wrote this SQL" in res.stderr and "Run? [y/N]" in res.stderr
    assert "self-check returns rows" in res.stderr
    assert query_runs(lab) == 0


def test_runs_only_after_yes(lab: dict[str, Any]) -> None:
    reply(lab)
    res = invoke(lab, "events per source", "-o", "csv", answer="y\n")
    assert res.exit_code == 0
    assert "fw_edge,1" in res.stdout
    assert query_runs(lab) == 1


def test_model_text_is_stripped_of_terminal_controls(lab: dict[str, Any]) -> None:
    reply(lab, sql="SELECT 1 -- \x1b]0;pwned\x07\x1b[31mred", explanation="ok\x1b[2J")
    res = invoke(lab, "anything")
    assert "\x1b" not in res.stdout + res.stderr and "\x07" not in res.stdout
    assert "SELECT 1 -- red" in res.stdout


def test_model_choice_by_name(lab: dict[str, Any]) -> None:
    reply(lab)
    assert invoke(lab, "q", "--model", "local ollama").exit_code == 0
    res = invoke(lab, "q", "--model", "nope")
    assert res.exit_code == 1 and "no enabled AI provider named nope" in res.stderr


def test_there_is_no_flag_to_skip_the_prompt(lab: dict[str, Any]) -> None:
    for flag in ("--yes", "-y", "--run"):
        assert invoke(lab, "q", flag).exit_code != 0
