"""Oversized queries fail with an error instead of exhausting memory (D58)."""

import tempfile
from pathlib import Path

import pytest

from app.core import memory
from app.core.errors import QueryFailedError, QueryRejectedError
from app.engine.duckdb import QueryEngine, QueryScope
from app.engine.guard import guard

EVENTS = frozenset({"events"})


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT count(*) FROM (SELECT unnest(range(3000000000)))",
        "SELECT unnest(generate_series(1, 600000000))",
        "SELECT range(-200000000, 0)",
        "SELECT unnest(range(0, 10000000000, 10))",
        "SELECT length(repeat('x', 2000000000))",
        "SELECT lpad('a', 99999999, 'b')",
        "SELECT rpad('a', 99999999, 'b')",
        "SELECT list_resize([1], 50000000)",
        "SELECT array_resize([1], 50000000)",
    ],
)
def test_literal_sizes_past_the_caps_are_refused(sql: str) -> None:
    with pytest.raises(QueryRejectedError, match="too large"):
        guard(sql, EVENTS)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT unnest(range(1000))",
        "SELECT repeat('-', 40)",
        "SELECT lpad(message, 20, ' ') FROM events",
        "SELECT unnest(range(0, 1000, 0))",  # zero step: DuckDB's own error, not ours
    ],
)
def test_ordinary_use_still_passes(sql: str) -> None:
    guard(sql, EVENTS)


def test_engine_reports_out_of_memory_as_a_failed_query() -> None:
    engine = QueryEngine(Path(tempfile.mkdtemp()), memory_mb=64, threads=1)
    sql = (
        "SELECT length(string_agg(repeat('x', 1000000), '')) FROM (SELECT unnest(range(3000)) AS i)"
    )
    with pytest.raises(QueryFailedError, match="more memory than this server allows"):
        engine.run(sql, QueryScope(None))


def test_budget_is_configured_or_three_quarters_of_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(memory, "available_mb", lambda: 8000)
    assert memory.server_budget_mb(0) == 6000
    assert memory.server_budget_mb(4096) == 4096
    assert memory.server_budget_mb(10) == memory.MIN_MB  # never below what the server needs
    monkeypatch.setattr(memory, "available_mb", lambda: 1000)
    assert memory.server_budget_mb(0) is None  # too small to cap safely
    monkeypatch.setattr(memory, "available_mb", lambda: None)
    assert memory.server_budget_mb(0) is None
    assert memory.available_mb is not None
