"""The engine reads only the sources a query pins with source_id (trial finding)."""

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
        # Both sides of an OR pin it: a or b (S7, fix list 2026-11-16).
        ("SELECT * FROM events WHERE source_id = 'a' OR source_id = 'b'", None, {"a", "b"}),
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
        # The OR does not pin; the AND around it still does.
        ("SELECT * FROM events WHERE source_id = 'a' AND (source_id = 'b' OR 1=1)", None, {"a"}),
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
    ("sql", "expected"),
    [
        (
            "SELECT source_id, count(*) FROM events WHERE source_id = 'dns' OR 1=1 GROUP BY 1",
            ["dns", "fw", "linux"],
        ),
        (
            "SELECT source_id, count(*) FROM events"
            " WHERE source_id IN (SELECT source_id FROM events) GROUP BY 1",
            ["dns", "fw", "linux"],
        ),
        # Each read pins its own source, so the two are all it reads (S7, 2026-11-16).
        (
            "WITH other AS (SELECT * FROM events WHERE source_id = 'fw')"
            " SELECT source_id, count(*) FROM (SELECT * FROM events WHERE source_id = 'dns'"
            " UNION ALL SELECT * FROM other) GROUP BY 1",
            ["dns", "fw"],
        ),
        ("SELECT source_id, count(*) FROM events WHERE source_id = 'dns' GROUP BY 1", ["dns"]),
    ],
)
def test_reported_sources_are_exactly_what_the_view_reads(
    tmp_path: Path, sql: str, expected: list[str]
) -> None:
    """The view and the report share one scope: every source in the rows is reported, and
    a query narrowing could not prove reports every permitted source."""
    engine = _lake(tmp_path)
    res = engine.run(sql, QueryScope(None))
    assert {r[0] for r in res.rows} <= set(res.sources)
    assert res.sources == expected


def test_a_template_filter_reads_only_sources_holding_it(tmp_path: Path) -> None:
    """Owner 2026-10-31: a Microsoft 365 query said "4 sources"; a source whose files hold
    none of the pinned templates is not read (Parquet statistics), with the same rows."""
    from app.engine.narrow import pinned_templates

    engine = _lake(tmp_path)
    rows = []
    for sid, tpl in (("m365", "m365_signin"), ("fw2", "paloalto_traffic")):
        norm = Normalizer(SourceSpec(source_id=sid, format="json"), clock=lambda: NOW)
        row = norm.normalize(DecodedLine('{"time": "2026-10-09T11:00:00Z"}', False, False))
        assert row is not None
        row["template_id"] = tpl
        rows.append(row)
    LakeWriter(tmp_path / "lake").write(rows)
    assert pinned_templates("SELECT * FROM events WHERE template_id = 'x' AND a = 1") == {"x"}
    assert pinned_templates("SELECT * FROM events WHERE template_id = 'x' OR a = 1") is None
    res = engine.run(
        "SELECT count(*) FROM events WHERE template_id = 'm365_signin'", QueryScope(None)
    )
    assert res.rows == [[1]] and res.sources == ["m365"]
    both = engine.run(
        "SELECT count(*) FROM events WHERE template_id IN ('m365_signin', 'paloalto_traffic')",
        QueryScope(None),
    )
    assert both.rows == [[2]] and both.sources == ["fw2", "m365"]
    none = engine.run("SELECT count(*) FROM events WHERE template_id = 'nothing'", QueryScope(None))
    assert none.rows == [[0]] and none.sources == []


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        (
            "WITH r AS (SELECT * FROM events WHERE template_id IN ('a','b')) SELECT * FROM r",
            {"a", "b"},
        ),
        (
            "SELECT * FROM events WHERE template_id = 'a'"
            " UNION ALL SELECT * FROM events WHERE template_id = 'b'",
            {"a", "b"},
        ),
        # Not provable: every source.
        ("SELECT * FROM events WHERE template_id = 'a' UNION ALL SELECT * FROM events", None),
        (
            "WITH r AS (SELECT * FROM events e JOIN events f ON e.raw = f.raw"
            " WHERE e.template_id = 'a') SELECT * FROM r",
            None,
        ),
        ("WITH r AS (SELECT * FROM events WHERE template_id = 'a' OR 1=1) SELECT * FROM r", None),
        (
            "WITH events AS (SELECT 1 AS template_id) SELECT * FROM events WHERE template_id = 'a'",
            None,
        ),
    ],
)
def test_templates_pinned_through_ctes_and_unions(sql: str, expected: set[str] | None) -> None:
    """Owner 2026-10-31: a CTE over Microsoft 365 records said "4 sources"."""
    from app.engine.narrow import pinned_templates

    assert pinned_templates(sql) == expected


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        # S7 (fix list 2026-11-16): a class pin narrows like a template pin, in a CTE too.
        ("SELECT * FROM events WHERE class_uid = 4003", [("class_uid", {"4003"})]),
        (
            "WITH q AS (SELECT * FROM events WHERE class_uid IN (4003, 4001)) SELECT * FROM q",
            [("class_uid", {"4001", "4003"})],
        ),
        (
            "SELECT * FROM events WHERE template_id = 'a' AND class_uid = 1",
            [("template_id", {"a"})],
        ),
        ("SELECT * FROM events WHERE class_uid = '4003'", None),
        ("SELECT * FROM events WHERE class_uid BETWEEN 4000 AND 4999", None),
        ("SELECT * FROM events WHERE class_uid = 4003 OR 1=1", None),
        (
            "SELECT * FROM events WHERE (class_uid = 1 AND a = 1) OR (class_uid = 2 AND b = 2)",
            [("class_uid", {"1", "2"})],
        ),
    ],
)
def test_reads_pinned_by_class_or_template(sql: str, expected: Any) -> None:
    from app.engine.narrow import pinned_reads

    got = pinned_reads(sql)
    assert (None if got is None else [(c, set(v)) for c, v in got]) == expected


def test_a_class_filter_reads_only_sources_holding_it(tmp_path: Path) -> None:
    from app.core.schema import COLUMN_NAMES
    from app.ingest.writer import LakeWriter

    def one(source: str, cls: int) -> dict[str, Any]:
        r: dict[str, Any] = dict.fromkeys(COLUMN_NAMES)
        at = datetime(2026, 10, 1, tzinfo=UTC)
        r.update(
            event_id=str(uuid.uuid4()), source_id=source, template_id=source,
            template_version="1", time=at, time_observed=at, raw="x", raw_bytes_invalid=False,
            parse_status="ok", classification="internal", owner_id="system", message="m",
            unmapped="{}", class_uid=cls,
        )  # fmt: skip
        return r

    LakeWriter(tmp_path).write([one("dns", 4003), one("fw", 4001), one("auth", 3002)])
    engine = QueryEngine(tmp_path)
    sql = "WITH q AS (SELECT * FROM events WHERE class_uid = 4003) SELECT count(*) FROM q"
    res = engine.run(sql, QueryScope(None))
    assert res.rows == [[1]] and res.sources == ["dns"]


def test_a_subquery_pinned_to_sources_reads_only_them(tmp_path: Path) -> None:
    """Each read pins its own sources (the summary shot of the fix list's S7): the outer
    read and the subquery together read two sources of three."""
    from app.core.schema import COLUMN_NAMES

    def one(source: str) -> dict[str, Any]:
        r: dict[str, Any] = dict.fromkeys(COLUMN_NAMES)
        at = datetime(2026, 10, 1, tzinfo=UTC)
        r.update(
            event_id=str(uuid.uuid4()), source_id=source, template_id=source,
            template_version="1", time=at, time_observed=at, raw="x", raw_bytes_invalid=False,
            parse_status="ok", classification="internal", owner_id="system", message="m",
            unmapped="{}", src_endpoint_ip="192.0.2.1",
        )  # fmt: skip
        return r

    LakeWriter(tmp_path).write([one("m365"), one("ssh"), one("fw")])
    sql = (
        "SELECT count(*) FROM events WHERE source_id = 'm365' AND src_endpoint_ip IN"
        " (SELECT src_endpoint_ip FROM events WHERE source_id = 'ssh')"
    )
    res = QueryEngine(tmp_path).run(sql, QueryScope(None))
    assert res.rows == [[1]] and res.sources == ["m365", "ssh"]


CORRELATED = (
    "SELECT * FROM events WHERE {col} = {v} AND EXISTS (SELECT 1 FROM events i"
    " WHERE i.actor_user_name = events.actor_user_name AND events.{col} = {v})"
)


@pytest.mark.parametrize(
    ("col", "v"), [("class_uid", "7"), ("template_id", "'t7'"), ("source_id", "'s7'")]
)
def test_a_correlated_reference_does_not_pin_the_inner_read(col: str, v: str) -> None:
    """Second review of 636: `events.<col>` inside the read aliased `i` names the outer
    read, so `i` has no pin of its own and nothing may be narrowed."""
    from app.engine.narrow import pinned_reads, pinned_templates

    sql = CORRELATED.format(col=col, v=v)
    assert pinned_reads(sql) is None
    assert pinned_templates(sql) is None


def test_a_correlated_reference_keeps_every_source_the_inner_read_needs(
    tmp_path: Path,
) -> None:
    """The outer row (class 7, in fw) matches only through an inner row in dns, which has
    no class 7: narrowing the inner read to class 7 would drop it."""
    from app.core.schema import COLUMN_NAMES

    def one(source: str, cls: int) -> dict[str, Any]:
        r: dict[str, Any] = dict.fromkeys(COLUMN_NAMES)
        at = datetime(2026, 10, 1, tzinfo=UTC)
        r.update(
            event_id=str(uuid.uuid4()), source_id=source, template_id=source,
            template_version="1", time=at, time_observed=at, raw="x", raw_bytes_invalid=False,
            parse_status="ok", classification="internal", owner_id="system", message="m",
            unmapped="{}", class_uid=cls, actor_user_name="alice" if source != "auth" else "bob",
        )  # fmt: skip
        return r

    LakeWriter(tmp_path).write([one("fw", 7), one("dns", 4003), one("auth", 3002)])
    sql = (
        "SELECT count(*) FROM events WHERE class_uid = 7 AND EXISTS (SELECT 1 FROM events i"
        " WHERE i.actor_user_name = events.actor_user_name AND i.class_uid = 4003"
        " AND events.class_uid = 7)"
    )
    res = QueryEngine(tmp_path).run(sql, QueryScope(None))
    assert res.rows == [[1]]


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        # Each read's own pins still narrow, aliased or not, through ORs and parentheses.
        ("SELECT * FROM events e WHERE e.class_uid = 7", [("class_uid", {"7"})]),
        ("SELECT * FROM events e WHERE class_uid = 7", [("class_uid", {"7"})]),
        ("SELECT * FROM events e WHERE events.class_uid = 7", None),
        (
            "SELECT * FROM events WHERE (template_id = 'a' AND x = 1) OR (template_id = 'b')",
            [("template_id", {"a", "b"})],
        ),
    ],
)
def test_own_pins_still_narrow(sql: str, expected: Any) -> None:
    from app.engine.narrow import pinned_reads

    got = pinned_reads(sql)
    assert (None if got is None else [(c, set(v)) for c, v in got]) == expected
