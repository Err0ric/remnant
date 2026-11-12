"""D237 (owner, 2026-11-10): a policy block raises QueryBlockedError (recorded in
server_events); a plain mistake raises QueryRejectedError only (not recorded)."""

import pytest

from app.core.errors import QueryBlockedError, QueryRejectedError
from app.engine.guard import guard

TABLES = frozenset({"events"})


@pytest.mark.parametrize(
    "sql",
    [
        "ATTACH 'x.db' AS x",
        "COPY (SELECT 1) TO 'out.csv'",
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM 'data.parquet'",
        "SELECT * FROM other.events",
        "SELECT getenv('HOME')",
        "SELECT 1; SELECT 2",
        "INSERT INTO events VALUES (1)",
        "SELECT * FROM (SELECT * FROM read_parquet('x'))",
    ],
)
def test_policy_blocks(sql: str) -> None:
    with pytest.raises(QueryBlockedError):
        guard(sql, TABLES)


@pytest.mark.parametrize(
    "sql", ["", "SELEC 1", "SELECT * FROM missing", "SELECT repeat('a', 99999999999)"]
)
def test_plain_mistakes_are_not_blocks(sql: str) -> None:
    with pytest.raises(QueryRejectedError) as info:
        guard(sql, TABLES)
    assert not isinstance(info.value, QueryBlockedError)
