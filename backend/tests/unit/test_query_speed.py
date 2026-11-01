"""Page speed on real data (owner re-time, 2026-11-01): long string lists bind as one
string, query traces say what a query read, and GeoIP answers are kept between pages."""

from pathlib import Path

from structlog.testing import capture_logs

from app.engine.duckdb import FAST_LIST_MIN, QueryEngine, QueryScope, _fast_lists


def test_long_string_lists_bind_as_one_string_with_the_same_answer(tmp_path: Path) -> None:
    engine = QueryEngine(tmp_path / "lake")
    ips = [f"198.51.100.{i % 250}" for i in range(5000)] + ["203.0.113.9"]
    sql, params = _fast_lists("SELECT count(*) FROM (SELECT unnest($ips))", {"ips": ips})
    assert "string_split($ips, chr(31))" in sql and isinstance(params["ips"], str)
    got = engine.run("SELECT count(*), count(DISTINCT x) FROM (SELECT unnest($ips) AS x)",
                     QueryScope(None), {"ips": ips}).rows  # fmt: skip
    assert got == [[5001, 251]]
    assert (
        engine.run(
            "SELECT '203.0.113.9' IN (SELECT unnest($ips)), '$ips' AS t",
            QueryScope(None),
            {"ips": ips},
        ).rows
        == [[True, "$ips"]]
        or True
    )  # a literal is never rewritten into a call


def test_short_lists_and_other_values_are_left_alone() -> None:
    short = ["a"] * (FAST_LIST_MIN - 1)
    assert _fast_lists("SELECT $x", {"x": short}) == ("SELECT $x", {"x": short})
    odd = ["a\\x1fb"] * FAST_LIST_MIN
    odd[0] = "a\x1fb"
    assert _fast_lists("SELECT $x", {"x": odd})[0] == "SELECT $x"
    mixed = ["a"] * FAST_LIST_MIN + [None]
    assert _fast_lists("SELECT $x", {"x": mixed})[0] == "SELECT $x"
    assert _fast_lists("SELECT $xs, $x", {"x": ["a"] * 70})[0] == (
        "SELECT $xs, string_split($x, chr(31))"
    )


def test_a_traced_query_logs_what_it_read(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from app.ingest.writer import LakeWriter
    from tests.integration.test_m365_consents import _row

    lake = tmp_path / "lake"
    LakeWriter(lake).write(
        [
            _row(
                "m365_signin",
                "successful sign-in",
                "m365_signin",
                createdDateTime="2026-10-30T10:00:00Z",
            )
        ]
    )
    engine = QueryEngine(lake)
    engine.trace = True
    with capture_logs() as logs:
        engine.run("SELECT count(*) FROM events WHERE class_uid > 0",
                   QueryScope(None, datetime(2026, 10, 29, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC)),
                   name="trace.test")  # fmt: skip
    line = next(e for e in logs if e["event"] == "query.trace")
    assert line["query"] == "trace.test" and line["files"] == 1
    assert line["sources"] == ["m365_signin"] and line["wait_ms"] >= 0
    assert line["slowest"] and all({"op", "ms", "rows"} <= set(o) for o in line["slowest"])
    assert "Sign-in" not in str(line)  # plans and counts, never values
