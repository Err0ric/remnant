"""D205: `{{person:col}}` and `{{org_domains}}` compile to SQL over bound Identities values,
never to text from the client, and a headline counts people, not labels."""

import pytest

from app.core.errors import QueryRejectedError
from app.search.ask_summary import headline
from app.search.identity import IdentityMap, identity_values
from app.search.live import live_sql
from app.search.params import compile_sql, placeholders, uses_identities


def test_placeholders_compile_to_bound_parameters_only() -> None:
    sql = compile_sql("SELECT {{person:actor_user_name}} AS p, {{org_domains}} AS d FROM events")
    assert "$id_from" in sql and "$id_to" in sql and "$id_org" in sql
    assert "{{" not in sql
    assert uses_identities("SELECT {{person:x}} FROM events")
    assert uses_identities("SELECT {{org_domains}} FROM events")
    assert not uses_identities("SELECT {{start}} FROM events")
    assert placeholders("SELECT {{person:x}}, {{org_domains}}") == {"org_domains"}


def test_values_come_from_the_identities_map() -> None:
    m = IdentityMap(domains=["example.com"], aliases={"dana@example.org": "dana"})
    assert m.sql_values() == {
        "id_org": ["example.com"], "id_from": ["dana@example.org"], "id_to": ["dana"]
    }  # fmt: skip
    # Nothing linked: one blank each, which matches only a blank name.
    assert IdentityMap().sql_values() == {"id_org": [""], "id_from": [""], "id_to": [""]}
    assert identity_values("SELECT 1", None) == {}


def test_headline_counts_people_and_accounts_not_labels() -> None:
    cols = ["person", "accounts"]
    rows = [
        ["dana", "dana@example.com (work), dana@example.org (personal)"],
        ["(no account reported)", "(no account reported)"],
    ]
    t = "{count.person|person|people}, {items.accounts|account|accounts}; first {first.person}"
    assert headline(cols, rows, False, t) == "1 person, 2 accounts; first dana"
    assert headline(cols, rows[:1] * 3, False, "{n} rows, {count.person}") == "3 rows, 3"
    # A count of a column the result lacks falls back to the generic headline.
    assert headline(cols, rows, False, "{count.user|user|users}").startswith("2 rows.")


def test_live_does_not_follow_identity_queries() -> None:
    with pytest.raises(QueryRejectedError, match="person"):
        live_sql("SELECT {{person:actor_user_name}} AS p, time FROM events")
