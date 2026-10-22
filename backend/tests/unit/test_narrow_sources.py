"""The engine reads only the sources a query pins with source_id (trial finding)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.engine.duckdb import QueryEngine, QueryScope
from app.engine.narrow import pinned_sources
from app.ingest.normalizer import Normalizer, SourceSpec
from app.ingest.records import DecodedLine
from app.ingest.writer import LakeWriter


@pytest.mark.parametrize(
    ("sql", "params", "expected"),
    [
        ("SELECT * FROM events WHERE source_id = 'dns'", None, {"dns"}),
        ("SELECT count(*) FROM events WHERE 'dns' = source_id AND severity_id > 2", None, {"dns"}),
        ("SELECT * FROM events e WHERE e.source_id IN ('a', 'b')", None, {"a", "b"}),
        ("SELECT * FROM events WHERE source_id IN ('a','b') AND source_id = 'b'", None, {"b"}),
        ("SELECT * FROM events WHERE source_id = $p0", {"p0": "fw"}, {"fw"}),  # Simple search
        # Not provable: full scope.
        ("SELECT * FROM events", None, None),
        ("SELECT * FROM events WHERE source_id = 'a' OR source_id = 'b'", None, None),
        ("SELECT * FROM events WHERE source_id = $p0", {}, None),
        ("SELECT * FROM events WHERE source_id LIKE 'fw%'", None, None),
        ("WITH x AS (SELECT * FROM events) SELECT * FROM x WHERE source_id = 'a'", None, None),
        (
            "SELECT * FROM events WHERE source_id = 'a'"
            " AND src_endpoint_ip IN (SELECT src_endpoint_ip FROM events)",
            None,
            None,
        ),
        (
            "SELECT * FROM events a JOIN threat_intel t ON a.raw = t.indicator WHERE a.source_id = 'a'",
            None,
            None,
        ),
        # Owner review: each falls back to the full permitted scope.
        ("SELECT * FROM events WHERE source_id = 'a' OR 1=1", None, None),
        ("SELECT * FROM events WHERE source_id = 'a' AND (source_id = 'b' OR 1=1)", None, None),
        ("SELECT * FROM events WHERE source_id IN (SELECT source_id FROM events)", None, None),
        (
            "SELECT * FROM events WHERE source_id IN (SELECT indicator FROM threat_intel)",
            None,
            None,
        ),
        ("SELECT * FROM events WHERE lower(source_id) = 'a'", None, None),
        ("SELECT * FROM events WHERE source_id = 'a' AND lower(source_id) = 'a'", None, None),
        (
            "WITH other AS (SELECT * FROM events WHERE source_id = 'b')"
            " SELECT * FROM events WHERE source_id = 'a' UNION ALL SELECT * FROM other",
            None,
            None,
        ),
        ("WITH x AS (SELECT 1) SELECT * FROM events WHERE source_id = 'a'", None, None),
        ("SELECT * FROM events WHERE source_id = 'a' UNION ALL SELECT * FROM events", None, None),
    ],
)
def test_pinned_sources(sql: str, params: dict[str, str] | None, expected: set[str] | None) -> None:
    assert pinned_sources(sql, params) == expected


NOW = datetime(2026, 10, 10, tzinfo=UTC)


def _lake(tmp_path: Path) -> QueryEngine:
    rows = []
    for sid in ("dns", "fw", "linux"):
        norm = Normalizer(SourceSpec(source_id=sid, format="json"), clock=lambda: NOW)
        row = norm.normalize(DecodedLine('{"time": "2026-10-09T10:00:00Z", "n": 1}', False, False))
        assert row is not None
        rows.append(row)
    LakeWriter(tmp_path / "lake").write(rows)
    return QueryEngine(tmp_path / "lake")


def test_result_names_only_the_sources_read(tmp_path: Path) -> None:
    engine = _lake(tmp_path)
    one = engine.run("SELECT count(*) FROM events WHERE source_id = 'dns'", QueryScope(None))
    assert one.rows == [[1]] and one.sources == ["dns"]
    every = engine.run("SELECT count(*) FROM events", QueryScope(None))
    assert every.rows == [[3]] and every.sources == ["dns", "fw", "linux"]


def test_narrowing_never_widens_the_callers_scope(tmp_path: Path) -> None:
    engine = _lake(tmp_path)
    res = engine.run("SELECT count(*) FROM events WHERE source_id = 'fw'", QueryScope(["dns"]))
    assert res.rows == [[0]] and res.sources == []


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT source_id, count(*) FROM events WHERE source_id = 'dns' OR 1=1 GROUP BY 1",
        "SELECT source_id, count(*) FROM events"
        " WHERE source_id IN (SELECT source_id FROM events) GROUP BY 1",
        "WITH other AS (SELECT * FROM events WHERE source_id = 'fw')"
        " SELECT source_id, count(*) FROM (SELECT * FROM events WHERE source_id = 'dns'"
        " UNION ALL SELECT * FROM other) GROUP BY 1",
        "SELECT source_id, count(*) FROM events WHERE source_id = 'dns' GROUP BY 1",
    ],
)
def test_reported_sources_are_exactly_what_the_view_reads(tmp_path: Path, sql: str) -> None:
    """The view and the report share one scope: every source in the rows is reported, and
    a query narrowing could not prove reports every permitted source."""
    engine = _lake(tmp_path)
    res = engine.run(sql, QueryScope(None))
    assert {r[0] for r in res.rows} <= set(res.sources)
    pinned = pinned_sources(sql)
    expected = engine.sources_in(QueryScope(None if pinned is None else sorted(pinned)))
    assert res.sources == expected
