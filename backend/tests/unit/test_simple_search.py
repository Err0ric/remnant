"""Simple search compiler (ADR-0009): syntax, names, escaping, caps, and refusals."""

import pytest

from app.core.errors import SearchInvalidError
from app.engine.guard import guard
from app.search.simple import MAX_TERMS, compile_search


def where(text: str) -> str:
    sql = compile_search(text).sql
    return sql.split("WHERE ", 1)[1].split("\nORDER BY", 1)[0] if "WHERE" in sql else ""


@pytest.mark.parametrize(
    ("text", "fragment", "params"),
    [
        ("sshd", "raw ILIKE $p0 ESCAPE '\\' OR message ILIKE $p0", {"p0": "%sshd%"}),
        ('"failed password"', "raw ILIKE $p0", {"p0": "%failed password%"}),
        ("user:root", 'lower("actor_user_name") = lower($p0)', {"p0": "root"}),
        ('user:"jane doe"', 'lower("actor_user_name") = lower($p0)', {"p0": "jane doe"}),
        ("src_ip:203.0.113.*", '"src_endpoint_ip" ILIKE $p0', {"p0": "203.0.113.%"}),
        ("severity:>=high", '"severity_id" >= $p0', {"p0": 4}),
        ("dst_port:<1024", '"dst_endpoint_port" < $p0', {"p0": 1024}),
        ("src_ip:2001:db8::1", 'lower("src_endpoint_ip") = lower($p0)', {"p0": "2001:db8::1"}),
        ("user:*", '"actor_user_name" IS NOT NULL', {}),
        ("raw_bytes_invalid:true", '"raw_bytes_invalid" = $p0', {"p0": True}),
        ("100%", "raw ILIKE $p0", {"p0": "%100\\%%"}),
        ("a_b", "raw ILIKE $p0", {"p0": "%a\\_b%"}),
        ("a\\*b", "raw ILIKE $p0", {"p0": "%a*b%"}),
        ("12:30:01", "raw ILIKE $p0", {"p0": "%12:30:01%"}),
        ("EventID:4625", "$.winlog.event_id", {"p0": "4625"}),
        ("TargetUserName:adm*", '$.winlog.event_data."TargetUserName"', {"p0": "adm%"}),
        ("Source_Port:>1000", "TRY_CAST(", {"p0": 1000.0}),
    ],
)
def test_terms(text: str, fragment: str, params: dict[str, object]) -> None:
    out = compile_search(text)
    assert fragment in out.sql
    assert out.params == params
    guard(out.sql, frozenset({"events"}))  # every compiled search passes the guard


def test_boolean_structure_and_negation() -> None:
    assert where("a b") == (
        "(coalesce(raw ILIKE $p0 ESCAPE '\\' OR message ILIKE $p0 ESCAPE '\\', false) AND "
        "coalesce(raw ILIKE $p1 ESCAPE '\\' OR message ILIKE $p1 ESCAPE '\\', false))"
    )
    assert where("a OR b AND c").count(" OR ") == 4  # one inside each term, one between
    assert where("-user:root").startswith("NOT coalesce(")
    assert where("NOT user:root") == where("-user:root")
    assert where("(a OR b) c").startswith("((coalesce")
    assert "and" in compile_search("rock and roll").params.get("p1", "")  # lower case is a word


def test_times_and_days() -> None:
    day = compile_search("time:2026-10-10")
    assert day.params == {"p0": "2026-10-10T00:00:00+00:00", "p1": "2026-10-11T00:00:00+00:00"}
    after = compile_search("time:>2026-10-10")
    assert '"time" >= ' in after.sql and after.params == {"p0": "2026-10-11T00:00:00+00:00"}
    upto = compile_search("time:<=2026-10-10")
    assert '"time" < ' in upto.sql and upto.params == {"p0": "2026-10-11T00:00:00+00:00"}
    moment = compile_search("time:>=2026-10-10T14:30Z")
    assert moment.params == {"p0": "2026-10-10T14:30:00+00:00"}


def test_unmapped_names_add_a_note_once() -> None:
    out = compile_search("Foo:1 Foo:2")
    assert out.notes == ["Foo is not a column, so it is looked up in unmapped fields"]
    assert compile_search("EventID:1").notes == []


def test_top_values() -> None:
    out = compile_search("sshd", top="user")
    assert out.sql.startswith('SELECT "actor_user_name" AS "actor_user_name", count(*) AS events')
    assert "GROUP BY 1" in out.sql and "LIMIT 20" in out.sql
    guard(out.sql, frozenset({"events"}))


def test_empty_search_lists_everything() -> None:
    out = compile_search("   ")
    assert "WHERE" not in out.sql and out.params == {}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('"open', "never closed"),
        ("(a b", "never closed"),
        ("a)", "no matching opening"),
        ("OR a", "Unexpected OR"),
        ("a AND", "ends where a term"),
        ("user:", "Give a value after user:"),
        ("user:>abc", "needs a number"),
        ("severity:loud", "whole number"),
        ("dst_port:8*", "not a text field"),
        ("time:yesterday", "date or time"),
        ("time:2026-02-30", "not a real date"),
        ("x" * 3000, "too long"),
        (" ".join(["a"] * (MAX_TERMS + 1)), "too many terms"),
        ("(" * 30 + "a" + ")" * 30, "nests too deeply"),
    ],
)
def test_refusals(text: str, message: str) -> None:
    with pytest.raises(SearchInvalidError, match=message):
        compile_search(text)


@pytest.mark.parametrize(
    "text",
    [
        'user:"x\') OR 1=1 --"',
        "a'; DROP TABLE events; --",
        'host:"\\"; SELECT 1"',
        "src_ip:$p0",
    ],
)
def test_typed_text_never_reaches_the_sql(text: str) -> None:
    out = compile_search(text)
    for marker in ("DROP", "1=1", "SELECT 1", "'x"):
        assert marker not in out.sql
    assert all(isinstance(v, str) for v in out.params.values())


def test_field_names_are_never_taken_from_unsafe_text() -> None:
    with pytest.raises(SearchInvalidError):
        compile_search("x", top='a" FROM x; --')


def test_columns_filtered_on_are_listed_once() -> None:
    out = compile_search("sshd user:root -src_ip:10.* user:admin EventID:1")
    assert out.columns == ["actor_user_name", "src_endpoint_ip"]
    assert compile_search("sshd").columns == []
