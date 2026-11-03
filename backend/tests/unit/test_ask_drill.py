"""D173: "Show events" SQL is built by code from the library query's own SQL."""

import pytest

from app.search.ask_drill import DrillError, base, drill_sql

SQL = (
    'SELECT lower(actor_user_name) AS "user", src_endpoint_ip AS address, count(*) AS n'
    " FROM events WHERE template_id = 'linux_sshd' AND status_id = {{status}}"
    " AND time BETWEEN {{start}} AND {{end}} GROUP BY 1, 2 HAVING count(*) > 2"
)


def test_keys_use_their_own_expression_and_values_are_literals() -> None:
    out = drill_sql(
        SQL, ["user", "address"], {"user": "o'brien' OR 1=1 --", "address": None}, {"status": 2}
    )
    assert "LOWER(actor_user_name) = 'o''brien'' OR 1=1 --'" in out
    assert "src_endpoint_ip IS NULL" in out
    assert "status_id = 2" in out and "{{start}}" in out and "{{end}}" in out
    assert "HAVING" not in out and "GROUP BY" not in out and "LIMIT 1000" in out


@pytest.mark.parametrize(
    ("sql", "why"),
    [
        ("WITH a AS (SELECT 1) SELECT * FROM a", "plain SELECT"),
        ("SELECT host, count(*) FROM other GROUP BY 1", "only from events"),
        ("SELECT host FROM events", "WHERE and a GROUP BY"),
    ],
)
def test_only_plain_grouped_queries_qualify(sql: str, why: str) -> None:
    with pytest.raises(DrillError, match=why):
        base(sql, ["host"])


def test_keys_must_be_groups_the_query_returns() -> None:
    with pytest.raises(DrillError, match="aggregate"):
        base(SQL, ["n"])
    with pytest.raises(DrillError, match="not a column"):
        base(SQL, ["host"])
    with pytest.raises(DrillError, match="each key"):
        drill_sql(SQL, ["user"], {"user": "a", "address": "b"}, {"status": 2})
    with pytest.raises(DrillError, match="no value"):
        drill_sql(SQL, ["user"], {"user": "a"}, {})
