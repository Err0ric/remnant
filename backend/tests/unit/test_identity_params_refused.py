"""Caller-written SQL never names the values the server binds for Identities (T70, D219):
`compile_sql` refuses `$id_...` in any spelling DuckDB reads as that parameter, and
`{{id_org}}`, `{{id_from}}`, `{{id_to}}`, before it expands anything."""

import pytest

from app.core.errors import QueryRejectedError
from app.search.params import compile_sql

REFUSED = [
    "SELECT $id_from",
    "SELECT $ID_TO",
    'SELECT $"id_org"',
    "SELECT $ id_from",
    "SELECT $\n\tid_from",
    "SELECT $/* x */id_from",
    "SELECT $/* /* nested */ x */id_from",
    "SELECT $-- x\nid_from",
    "SELECT {{org_domains}} AS d, $id_from",
    "SELECT {{id_from}}",
    "SELECT {{ id_to }}",
    "SELECT {{id_org}}",
]
KEPT = [
    "SELECT json_extract_string(unmapped, '$.attr.x') FROM events",
    "SELECT regexp_matches(message, '^a$|^b$') FROM events",
    "SELECT {{person:actor_user_name}} FROM events WHERE x = $p0",
    "SELECT {{org_domains}}",
    "SELECT {{id_host}} AS h",  # a saved search's own parameter, not a bound value
]


@pytest.mark.parametrize("sql", REFUSED)
def test_refused(sql: str) -> None:
    with pytest.raises(QueryRejectedError, match="Identities"):
        compile_sql(sql)


@pytest.mark.parametrize("sql", KEPT)
def test_kept(sql: str) -> None:
    compile_sql(sql)


def test_the_expansion_itself_still_binds_them() -> None:
    out = compile_sql("SELECT {{person:actor_user_name}}, {{org_domains}}")
    assert "$id_from" in out and "$id_to" in out and "$id_org" in out
