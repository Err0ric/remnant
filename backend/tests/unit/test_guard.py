"""Query guard (SPEC 5.1, CLAUDE.md rule 7)."""

import pytest

from app.core.errors import QueryRejectedError
from app.engine.guard import guard_sql

ALLOWED = frozenset({"events"})


def ok(sql: str, **kw: int) -> str:
    return guard_sql(sql, ALLOWED, **kw)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM events",
        "select count(*) from events where status_id = 2",
        "WITH f AS (SELECT * FROM events WHERE status_id = 2) SELECT src_endpoint_ip, count(*) FROM f GROUP BY 1",
        "SELECT a.raw FROM events a JOIN events b ON a.event_id = b.event_id",
        "SELECT 1 UNION ALL SELECT 2",
        "SELECT json_extract(envelope, '$.relay_hops') FROM events",
        "SELECT * FROM events WHERE event_id IN (SELECT event_id FROM events LIMIT 5)",
        "SELECT * FROM events;",
    ],
)
def test_allowed(sql: str) -> None:
    assert ok(sql)


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("INSERT INTO events VALUES (1)", "statement"),
        ("UPDATE events SET raw = 'x'", "statement"),
        ("DELETE FROM events", "statement"),
        ("DROP TABLE events", "statement"),
        ("CREATE TABLE t AS SELECT 1", "statement"),
        ("ATTACH 'x.db' AS x", "statement"),
        ("COPY events TO '/tmp/out.csv'", "statement"),
        ("INSTALL httpfs", "statement"),
        ("LOAD httpfs", "statement"),
        ("PRAGMA database_list", "statement"),
        ("SET enable_external_access = true", "statement"),
        ("CALL pragma_version()", "statement"),
        ("EXPORT DATABASE '/tmp/x'", "statement"),
        ("SELECT 1; SELECT 2", "one statement"),
        ("SELECT * FROM read_csv('/etc/passwd')", "table"),
        ("SELECT * FROM read_parquet('lake/source=hr/**/*.parquet')", "table"),
        ("SELECT * FROM 'data/meta.sqlite'", "table"),
        ("SELECT * FROM other_table", "table"),
        ("SELECT * FROM main.events", "table"),
        ("SELECT getenv('HOME')", "function"),
        ("SELECT * FROM events WHERE raw = read_text('/etc/hosts')", "function"),
        ("WITH x AS (SELECT * FROM glob('/*')) SELECT * FROM x", "table"),
        ("SELECT * FROM events WHERE 1 = (SELECT count(*) FROM read_json('x'))", "table"),
        ("", "empty"),
        ("SELEKT nonsense", "parse"),
    ],
)
def test_rejected(sql: str, reason: str) -> None:
    with pytest.raises(QueryRejectedError) as exc:
        ok(sql)
    assert reason in str(exc.value).lower()


def test_limit_added_when_absent() -> None:
    assert ok("SELECT * FROM events", default_limit=100).upper().endswith("LIMIT 100")


def test_limit_capped_when_too_large() -> None:
    out = ok("SELECT * FROM events LIMIT 999999", default_limit=100, max_limit=500)
    assert out.upper().endswith("LIMIT 500")


def test_small_limit_kept() -> None:
    assert ok("SELECT * FROM events LIMIT 5", default_limit=100).upper().endswith("LIMIT 5")


def test_union_gets_wrapped_limit() -> None:
    out = ok("SELECT 1 AS x UNION ALL SELECT 2", default_limit=10)
    assert out.upper().endswith("LIMIT 10")


def test_cte_names_are_allowed_tables() -> None:
    assert ok("WITH recent AS (SELECT * FROM events) SELECT * FROM recent")


# --- review findings S3 and S5 (2026-10-10) ------------------------------------------


def test_limit_percent_is_capped_by_an_outer_limit() -> None:
    from app.engine.guard import guard

    g = guard("SELECT * FROM events LIMIT 50 PERCENT", frozenset({"events"}), 100, 1000)
    assert g.applied_limit == 1000
    assert g.sql.rstrip().endswith("LIMIT 1000")


def test_limit_with_ties_is_capped() -> None:
    from app.engine.guard import guard

    g = guard(
        "SELECT * FROM events ORDER BY time LIMIT 5 WITH TIES", frozenset({"events"}), 100, 1000
    )
    assert g.applied_limit == 1000


@pytest.mark.parametrize(
    "sql",
    [
        'WITH "/etc/passwd" AS (SELECT 1) SELECT * FROM "/etc/passwd"',
        'WITH "lake/x.parquet" AS (SELECT 1) SELECT * FROM "lake/x.parquet"',
        # CTE defined in one branch must not whitelist the same name in another
        "SELECT * FROM x UNION ALL SELECT * FROM (WITH x AS (SELECT 1 AS a) SELECT * FROM x)",
        'SELECT * FROM "/etc/passwd" UNION ALL SELECT * FROM (WITH "/etc/passwd" AS (SELECT 1) SELECT * FROM "/etc/passwd")',
    ],
)
def test_cte_names_do_not_leak_out_of_scope(sql: str) -> None:
    from app.engine.guard import guard

    with pytest.raises(QueryRejectedError):
        guard(sql, frozenset({"events"}), 100, 1000)


def test_ordinary_ctes_still_work() -> None:
    from app.engine.guard import guard

    sql = (
        "WITH fails AS (SELECT * FROM events WHERE message LIKE 'Failed%'), "
        "by_ip AS (SELECT device_ip, count(*) AS n FROM fails GROUP BY 1) "
        "SELECT * FROM by_ip ORDER BY n DESC"
    )
    assert "by_ip" in guard(sql, frozenset({"events"}), 100, 1000).sql
