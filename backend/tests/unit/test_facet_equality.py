"""Logs facets in one pass (owner priority 2026-11-14: the facets call timed out on 30
days): the top values per field are exactly what the old statement gave, one grouped scan
of the needed columns instead of every column copied and sorted once and grouped ten times.
Compared with the old statement on a lake where a difference would show: values on other
days and in other sources (outside the scope), NULLs, more values than the limit, ties, a
search text, and the SQL on screen with its own ORDER BY."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.api import query as q_mod
from app.core.schema import COLUMN_NAMES
from app.engine.duckdb import QueryEngine, QueryScope
from app.ingest.writer import LakeWriter
from app.search.simple import compile_search

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


def old_facet_sql(sql: str, columns: list[str], intel: bool = False) -> str:
    """The statement as it was before this change, for comparison."""
    wanted = [c for c in q_mod.FACET_COLUMNS if c in set(columns)]
    branch = (
        "(SELECT '{c}' AS facet, CAST(\"{c}\" AS VARCHAR) AS value, count(*) AS n"
        " FROM q GROUP BY 2 ORDER BY 3 DESC, 2 NULLS LAST LIMIT {n})"
    )
    branches = [branch.format(c=c, n=q_mod.FACET_VALUES) for c in wanted]
    if intel:
        branches.append(q_mod.INTEL_FACET.format(n=q_mod.FACET_VALUES))
    inner = q_mod._TRAILING.sub("", sql)
    return (
        f"WITH q AS (\n{inner}\n)\nSELECT facet, value, n FROM (\n"
        + "\nUNION ALL\n".join(branches)
        + "\n) f"
    )


def row(source: str, at: datetime, **f: Any) -> dict[str, Any]:
    r: dict[str, Any] = dict.fromkeys(COLUMN_NAMES)
    r.update(
        event_id=str(uuid.uuid4()), source_id=source, template_id="t", template_version="1",
        time=at, time_observed=at, raw=f"line {f.get('message', '')}", raw_bytes_invalid=False,
        parse_status="ok", classification="internal", owner_id="system", message="m",
    )  # fmt: skip
    r.update(f)
    return r


@pytest.fixture(scope="module")
def engine(tmp_path_factory: pytest.TempPathFactory) -> QueryEngine:
    lake: Path = tmp_path_factory.mktemp("facets") / "lake"
    rows = []
    for i in range(400):
        at = NOW - timedelta(hours=i % 72, minutes=i % 60)
        rows.append(row(
            ["fw", "dns", "auth"][i % 3], at,
            # 15 users with ties (i % 15 spreads evenly), some with no user at all
            actor_user_name=None if i % 11 == 0 else f"user{i % 15:02d}@example.com",
            device_hostname=f"ws-{i % 4:04d}" if i % 5 else None,
            src_endpoint_ip=f"10.0.{i % 2}.{i % 13}", dst_endpoint_ip=None,
            dst_endpoint_hostname=["chat.example.com", "files.example.org", None][i % 3],
            severity_id=i % 6, status_id=[1, 2][i % 2], class_uid=[3002, 4003, 4001][i % 3],
            message="failed login" if i % 4 == 0 else "accepted",
        ))  # fmt: skip
    # Values only on other days (before the window) and in a source outside the scope.
    rows += [row("fw", NOW - timedelta(days=20), actor_user_name="mallory@example.com",
                 message="failed old")] * 30  # fmt: skip
    rows += [row("hidden", NOW - timedelta(hours=1), actor_user_name="judy@example.com",
                 message="failed hidden")] * 30  # fmt: skip
    LakeWriter(lake).write(rows)
    return QueryEngine(lake)


SCOPES = [
    QueryScope(None, NOW - timedelta(days=2), NOW),
    QueryScope(["fw", "dns", "auth"], NOW - timedelta(days=3), NOW),  # "hidden" not readable
    QueryScope(["dns"], None, None),
]


def answer(engine: QueryEngine, sql: str, scope: QueryScope, params: Any) -> list[tuple[Any, ...]]:
    rows = engine.run(sql, scope, params or None, timeout_s=30).rows
    return sorted(map(tuple, rows), key=lambda r: (r[0], -r[2], r[1] is None, str(r[1])))


def in_order(
    engine: QueryEngine, sql: str, scope: QueryScope, params: Any
) -> dict[str, list[tuple[Any, int]]]:
    """Each field's values as the statement returns them, unsorted: what the panel shows."""
    out: dict[str, list[tuple[Any, int]]] = {}
    for facet, value, n in engine.run(sql, scope, params or None, timeout_s=30).rows:
        out.setdefault(str(facet), []).append((value, int(n)))
    return out


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("text", ["", "failed"])
def test_each_field_s_values_come_in_the_old_order(
    engine: QueryEngine, scope: QueryScope, text: str
) -> None:
    old = compile_search(text, select="*")
    want = in_order(engine, old_facet_sql(old.sql, list(q_mod.FACET_COLUMNS)), scope, old.params)
    sql, params = q_mod.text_facet_sql(text)
    got = in_order(engine, sql, scope, params)
    assert got == want
    assert sql.rstrip().endswith("ORDER BY facet, n DESC, value NULLS LAST")


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("text", ["", "failed", "user:user0* -host:ws-0001", "severity:>2"])
def test_a_search_s_facets_are_the_old_answer(
    engine: QueryEngine, scope: QueryScope, text: str
) -> None:
    old = compile_search(text, select="*")
    want = answer(engine, old_facet_sql(old.sql, list(q_mod.FACET_COLUMNS)), scope, old.params)
    sql, params = q_mod.text_facet_sql(text)
    got = answer(engine, sql, scope, params)
    assert got == want
    # Enough here to show a difference: more users than the limit, NULLs, ties.
    if text == "" and scope.sources is None:
        users = [r for r in got if r[0] == "actor_user_name"]
        assert len(users) == q_mod.FACET_VALUES and any(r[1] is None for r in got)


SQLS = [
    "SELECT * FROM events ORDER BY coalesce(time, time_observed) DESC",
    "SELECT source_id, actor_user_name, severity_id FROM events WHERE message ILIKE '%fail%'\n"
    "ORDER BY severity_id;\n",
    "SELECT actor_user_name, count(*) AS n FROM events GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 5",
]


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("sql", SQLS)
def test_the_sql_on_screen_has_the_old_facets(
    engine: QueryEngine, scope: QueryScope, sql: str
) -> None:
    # The result's own columns, as the page sends them.
    cols = engine.run(sql, scope, timeout_s=30).columns
    want = answer(engine, old_facet_sql(sql, cols), scope, None)
    got = answer(engine, q_mod.facet_sql(sql, cols), scope, None)
    assert got == want


def test_only_the_needed_columns_are_read_and_nothing_is_sorted() -> None:
    sql, _ = q_mod.text_facet_sql("failed")
    assert "raw" in sql and "ORDER BY coalesce" not in sql
    assert sql.count("FROM events") == 1  # one pass
    assert "GROUPING SETS" in sql
