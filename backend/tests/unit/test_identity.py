"""Identity keys (ADR-0018): Python and SQL agree, and only certain rewrites merge."""

import duckdb
import pytest

from app.search.identity import IdentityMap, is_person, key_of, key_sql

DOMAINS = ["example.com", "corp.example"]
CASES = [
    ("alice", "alice"),
    ("  Alice ", "alice"),
    ("CORP\\alice", "alice"),
    ("alice@example.com", "alice"),
    ("ALICE@EXAMPLE.COM", "alice"),
    ("CORP\\alice@corp.example", "alice"),
    ("alice@gmail.example", "alice@gmail.example"),  # not an organization domain
    ("alice@sub.example.com", "alice@sub.example.com"),  # subdomains are not assumed
    ("WS-0042$", "ws-0042$"),
    ("o'brien@example.com", "o'brien"),
    ("", ""),
]


@pytest.mark.parametrize(("name", "key"), CASES)
def test_python_and_sql_keys_agree(name: str, key: str) -> None:
    assert key_of(name, DOMAINS) == key
    got = duckdb.connect().execute(f"SELECT {key_sql('$n')}", {"n": name, "id_org": DOMAINS})
    assert got.fetchone() == (key,)


def test_without_domains_nothing_but_case_and_prefix_merges() -> None:
    assert key_of("alice@example.com", []) == "alice@example.com"
    assert key_of("CORP\\Alice", []) == "alice"


def test_aliases_and_display() -> None:
    m = IdentityMap(domains=["example.com"], aliases={"jsmith": "john.smith"})
    m.email_people.add("john.smith")
    assert m.key("JSmith") == "john.smith"
    assert m.keys_for("john.smith@example.com") == ["john.smith", "jsmith"]
    assert m.display("john.smith", False) == "john.smith@example.com"
    # A bare login never seen as an organization address keeps its own name.
    assert m.display("admin", False) == "admin"
    assert m.display("alice", True) == "alice@example.com"


def test_role_accounts_are_not_people() -> None:
    assert not any(is_person(k) for k in ("root", "admin", "svc_backup", "ws-01$", ""))
    assert is_person("alice")
