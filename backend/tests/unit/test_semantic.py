"""Ask vocabulary: every shipped predicate passes the guard and runs in DuckDB."""

from pathlib import Path

import pytest

from app.core.errors import ConfigError
from app.engine.duckdb import QueryEngine, QueryScope
from app.llm.semantic import base_vocabulary, load_vocabulary


def test_every_shipped_predicate_runs(tmp_path: Path) -> None:
    engine = QueryEngine(tmp_path / "lake")  # empty lake: the typed empty view
    vocab = base_vocabulary()
    assert len(vocab.terms) >= 15
    for term in vocab.terms:
        res = engine.run(
            f"SELECT count(*) FROM events WHERE {term.sql}", QueryScope(sources=None)
        )  # repo predicate under test
        assert res.rows == [[0]], term.term


@pytest.mark.parametrize(
    "sql",
    [
        "1=1; DROP TABLE events",
        "event_id IN (SELECT * FROM read_csv('/etc/passwd'))",
        "x IN (SELECT 1 FROM other_table)",
    ],
)
def test_bad_predicates_stop_startup(tmp_path: Path, sql: str) -> None:
    path = tmp_path / "v.yaml"
    path.write_text(f'schema_version: 1\nterms:\n  - term: bad\n    sql: "{sql}"\n')
    with pytest.raises(ConfigError, match="bad"):
        load_vocabulary(path)


def test_unknown_keys_rejected(tmp_path: Path) -> None:
    path = tmp_path / "v.yaml"
    path.write_text("schema_version: 1\nterms:\n  - term: x\n    sql: '1=1'\n    run: rm\n")
    with pytest.raises(ConfigError):
        load_vocabulary(path)
