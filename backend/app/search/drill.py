"""Drill-through queries for Dashboard numbers (ADR-0039).

Each number carries a Search query template built from the same expressions its count
uses. The page fills `{from}` and `{to}` with the window's bounds as UTC timestamps and
opens Search; Search runs it through the guard on the caller's own view like anything
typed, so nothing here is trusted beyond being readable SQL. Values are SQL string
literals with quotes doubled.
"""

from __future__ import annotations

from collections.abc import Iterable

TS = "coalesce(time, time_observed)"
BOUNDS = f"{TS} >= TIMESTAMPTZ '{{from}}' AND {TS} < TIMESTAMPTZ '{{to}}'"
MAX_SQL = 18_000  # Search takes 20,000 characters

EVENT_COLUMNS = (
    "time, source_id, device_hostname, actor_user_name, src_endpoint_ip, message, event_id"
)
ADDRESS_COLUMNS = (
    "time, source_id, device_hostname, actor_user_name, src_endpoint_ip,"
    " ip_country(src_endpoint_ip) AS country, ip_org(src_endpoint_ip) AS network,"
    " message, event_id"
)


def lit(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def lits(values: Iterable[str]) -> str:
    return "[" + ", ".join(lit(v) for v in values) + "]"


def events(where: str, columns: str = EVENT_COLUMNS) -> str:
    """Event rows matching `where` in the window, newest first."""
    return f"SELECT {columns}\nFROM events\nWHERE {where}\n  AND {BOUNDS}\nORDER BY {TS} DESC"


def grouped(where: str, key: str, label: str, value: str = "count(*)") -> str:
    """One row per `key` (an address, a country) with its count, busiest first."""
    return (
        f"SELECT {key} AS {label}, {value} AS events\nFROM events\nWHERE {where}\n"
        f"  AND {BOUNDS}\nGROUP BY 1\nORDER BY events DESC"
    )


def any_of(conditions: Iterable[str]) -> str | None:
    """Rules' conditions joined with OR; None when too long for Search."""
    parts = sorted({c for c in conditions if c})
    if not parts:
        return None
    joined = "\n   OR ".join(f"({c})" for c in parts)
    return f"({joined})" if len(joined) < MAX_SQL - 400 else None
