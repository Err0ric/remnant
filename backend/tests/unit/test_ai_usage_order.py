"""AI usage lists keep one order on every load: equal counts by name (fix list S6)."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import duckdb
import pytest

from app.ai.catalog import Service
from app.ai.inventory import APPS_SQL, Item, ordered
from app.ai.usage import _DRILL_SELECT, PersonUse, Usage, merge_people, services_sql
from app.engine.duckdb import QueryScope


def service(sid: str, name: str) -> Service:
    return Service(sid, name, "Example", "chat", (f"{sid}.example.com",), "unreviewed", False, "")


CATALOG = [service("svc_c", "Alpha"), service("svc_a", "Charlie"), service("svc_b", "Bravo"),
           service("svc_d", "Delta")]  # fmt: skip


@dataclass
class Result:
    rows: list[list[Any]]
    sources: list[str] = field(default_factory=lambda: ["dns"])


class Catalog:
    def services(self) -> list[Service]:
        return CATALOG

    def domain_table(self) -> list[tuple[str, str]]:
        return [(s.id, d) for s in CATALOG for d in s.domains]


class Engine:
    """Answers the services query with its rows in the order given, as DuckDB may on ties."""

    def __init__(self, order: list[str]) -> None:
        self.order = order

    def run(self, sql: str, scope: QueryScope, *args: Any, **kwargs: Any) -> Result:
        events = {"svc_d": 9, "svc_a": 4, "svc_b": 4, "svc_c": 4}
        return Result([[sid, events[sid], 1, 1, None, None, [], []] for sid in self.order])


def listed(order: list[str]) -> list[str]:
    usage = Usage(Engine(order), Catalog())  # type: ignore[arg-type]  # stubs
    found, _ = usage.services(QueryScope(None, datetime(2026, 11, 1, tzinfo=UTC), None))
    return [u.service.name for u in found]


def test_services_with_equal_events_are_listed_by_name_whatever_order_rows_arrive_in() -> None:
    one = listed(["svc_d", "svc_a", "svc_b", "svc_c"])
    two = listed(["svc_c", "svc_b", "svc_d", "svc_a"])
    assert one == two == ["Delta", "Alpha", "Bravo", "Charlie"]


def test_the_services_query_breaks_ties_before_its_limit() -> None:
    assert "ORDER BY 2 DESC, 1\nLIMIT 500" in services_sql([("svc_a", "a.example.com")])


def test_merged_people_with_equal_numbers_are_listed_by_name() -> None:
    class Ident:
        def key(self, name: str) -> str:
            return name

        def org_email(self, name: str) -> bool:
            return "@" in name

        def display(self, key: str, email: bool) -> str:
            return key

    def use(name: str, sessions: int) -> PersonUse:
        return PersonUse(name, 0.0, 0, sessions, 0, 0, 0, [])

    rows = [use("carol@example.com", 3), use("bob@example.com", 3), use("alice@example.com", 2),
            use("dave@example.com", 7)]  # fmt: skip
    got = [p.person for p in merge_people(rows, Ident())]  # type: ignore[arg-type]  # a stub
    assert got == ["dave@example.com", "bob@example.com", "carol@example.com", "alice@example.com"]


def item(kind: str, name: str, last: str | None) -> Item:
    return Item(kind, name.lower(), name, None, 1, 1, None, last, [])


def test_inventory_items_seen_at_one_time_are_ordered_by_type_then_name() -> None:
    at, later = "2026-11-10T09:00:00+00:00", "2026-11-12T09:00:00+00:00"
    rows = [item("service", "Charlie", at), item("mcp", "bravo", at), item("service", "Alpha", at),
            item("agent", "delta", at), item("mcp", "echo", later), item("service", "Zulu", None)]  # fmt: skip
    got = [(i.type, i.name) for i in ordered(rows)]
    assert got == [("mcp", "echo"), ("agent", "delta"), ("mcp", "bravo"), ("service", "Alpha"),
                   ("service", "Charlie"), ("service", "Zulu")]  # fmt: skip
    assert [(i.type, i.name) for i in ordered(list(reversed(rows)))] == got


def run(sql: str, table: str, columns: str, rows: list[tuple[Any, ...]]) -> list[Any]:
    """`sql` over a table of `rows`, inserted in the order given."""
    con = duckdb.connect()
    con.execute(f"CREATE TABLE {table} ({columns})")
    marks = ", ".join("?" for _ in columns.split(","))
    con.executemany(f"INSERT INTO {table} VALUES ({marks})", rows)
    return [r[0] for r in con.execute(sql).fetchall()]


@pytest.mark.parametrize("kind", ["services", "people", "devices"])
def test_ai_watch_drills_order_equal_events_by_their_first_column(kind: str) -> None:
    sql = _DRILL_SELECT[kind].replace("{bounds}", "true")
    t = datetime(2026, 11, 10, tzinfo=UTC)
    # Equal events, inserted against name order, across many groups so a hash order shows.
    names = [f"n{i:02d}" for i in range(40)]
    rows = [(n, (None if kind == "devices" else n), (n if kind == "devices" else None), 1, t, t)
            for n in reversed(names)]  # fmt: skip
    got = run(sql, "r", "service_id VARCHAR, who VARCHAR, machine VARCHAR, n BIGINT,"
              " first_t TIMESTAMPTZ, last_t TIMESTAMPTZ", rows)  # fmt: skip
    assert got == names


def test_microsoft_365_apps_seen_at_one_time_are_ordered_by_name() -> None:
    body = APPS_SQL[APPS_SQL.index("SELECT coalesce(app") :]
    t = datetime(2026, 11, 10, tzinfo=UTC)
    names = [f"App {i:02d}" for i in range(40)]
    rows = [(n, None, "alice@example.com", t, 1) for n in reversed(names)]
    got = run(f"WITH consents AS (SELECT * FROM c)\n{body}", "c",
              "app VARCHAR, app_id VARCHAR, who VARCHAR, ts TIMESTAMPTZ, status_id INTEGER", rows)  # fmt: skip
    assert got == names
