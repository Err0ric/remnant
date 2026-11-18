"""The address page's sections (owner P4, fix batch of 2026-11-17): DHCP and VPN history,
the names the address looked up, its sign-ins and access, and the AI services seen from it.

Three sections are shipped library queries (ADR-0033) run as the library runs anywhere;
the AI services section is AI usage's own count (`usage.answer_sql`) for rows from this
address, server-built like the other page reads. Each runs through the guard on the
caller's `events` view, the address a bound parameter, the page's range as the scope. No
model is called. A section whose query needs templates none of the caller's sources has
says so and runs nothing. Rows with group keys carry the events query behind them for
Logs, built by code from the query (D173).
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from app.ai.usage import answer_sql, events_sql
from app.core.errors import NotFoundError, ParamInvalidError
from app.core.ids import AUTO_PARSER
from app.engine.duckdb import QueryEngine, QueryScope
from app.search.ask_drill import DrillError, drill_sql
from app.search.library import Library
from app.search.params import bind, compile_sql

Name = Literal["dhcp", "dns", "access", "ai"]
# The library query (pack, query) behind each section; the AI section is AI usage's own.
SECTIONS: dict[Name, tuple[str, str] | None] = {
    "dhcp": ("paloalto", "who_had_ip"),
    "dns": ("addresses", "dns_names_from_ip"),
    "access": ("addresses", "access_from_ip"),
    "ai": None,
}
# The page's titles for them, said the same on the page and in Ask's direct answer.
TITLES: dict[Name, str] = {
    "dhcp": "DHCP and VPN history",
    "dns": "Names looked up",
    "access": "Sign-ins and access",
    "ai": "AI services",
}
ROWS = 50
TIMEOUT_S = 20
# What a section's count counts, one and many (the page and Ask's direct answer say it).
UNITS: dict[Name, tuple[str, str]] = {
    "dhcp": ("lease or tunnel", "leases or tunnels"),
    "dns": ("name", "names"),
    "access": ("event", "events"),
    "ai": ("AI service", "AI services"),
}
AI_ORIGIN = "AI usage"
AI_QUERY = "AI services as AI usage counts them, for this source address"
LIMIT = re.compile(r"\s+LIMIT\s+\d+\s*$", re.IGNORECASE)


@dataclass(slots=True)
class Section:
    name: Name
    library: str  # "<pack>/<query>@<version>", or "AI usage"
    query: str  # the library query's name, or what AI usage counts
    state: Literal["ok", "no_source"]
    count: int = 0  # the true total, also when the rows shown are cut
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    # Per row, the events behind it for Logs (server-built), when the query has keys.
    links: list[str | None] = field(default_factory=list)
    read: list[str] = field(default_factory=list)  # sources the query read
    needs: list[str] = field(default_factory=list)  # templates it reads, when none is readable
    # Sources that returned rows: the query's own `sources` column when it has one, else
    # every source it read (a query pinned to its templates).
    found: list[str] = field(default_factory=list)

    def words(self) -> str:
        one, many = UNITS[self.name]
        return f"{self.count:,} {one if self.count == 1 else many}"


def address(value: str) -> str:
    """The address, or a plain 400: only an IPv4 or IPv6 address without a scope id has
    a page (a scope id can carry any text)."""
    try:
        ipaddress.ip_address(value)
    except ValueError as exc:
        raise ParamInvalidError("Give an IPv4 or IPv6 address") from exc
    if "%" in value:
        raise ParamInvalidError("Give an address without a scope id (%)")
    return value


def readable_templates(sources: Collection[tuple[str, str | None]]) -> set[str] | None:
    """Templates the caller's sources are set to; None when one parses with any template."""
    out: set[str] = set()
    for _source_id, template in sources:
        if template is None or template == AUTO_PARSER:
            return None
        out.add(template)
    return out


def section(
    engine: QueryEngine,
    library: Library,
    name: Name,
    ip: str,
    scope: QueryScope,
    templates: set[str] | None,
    end: datetime,
    services: Sequence[Any] = (),
) -> Section:
    """One section on the caller's scope. `templates` are those the caller's sources are
    set to (None: any), so a section whose query needs others runs nothing. `services`
    are the live AI catalog's entries, for the AI section."""
    ip = address(ip)
    ref = SECTIONS[name]
    keys: list[str] = []
    if ref is None:
        sql, params, requires = answer_sql(services, from_ip=True), {"ip": ip}, []
        out = Section(name, AI_ORIGIN, AI_QUERY, "ok")
    else:
        found = library.find(*ref)
        if found is None:
            raise NotFoundError(f"The library query {ref[0]}/{ref[1]} is not installed")
        pack, q = found
        sql, keys, requires = q.sql, list(q.keys), list(q.requires)
        params = bind(q.params, {"ip": ip}, scope.start or end, end, q.sql)
        out = Section(name, pack.origin(q), q.name, "ok")
    if requires and templates is not None and not templates & set(requires):
        out.state, out.needs = "no_source", requires
        return out

    def run(text: str, cap: int | None, label: str) -> Any:
        return engine.run(
            compile_sql(text), scope, params, row_cap=cap, timeout_s=TIMEOUT_S, intel=False,
            name=f"address.{label}", page=True,
        )  # fmt: skip

    res = run(sql, ROWS, name)
    out.columns, out.rows, out.read = res.columns, res.rows, sorted(res.sources)
    at = {c: i for i, c in enumerate(res.columns)}
    out.found = _found(at, res.rows, out.read)
    if name == "ai" and "service_id" in at:
        # Each service's events from this address, for Logs: built by code (usage.events_sql).
        pairs = [(s.id, d) for s in services for d in s.domains]
        out.links = [events_sql(pairs, str(r[at["service_id"]]), ip) for r in res.rows]
    for row in res.rows if keys else []:
        try:
            out.links.append(drill_sql(sql, keys, {k: row[at[k]] for k in keys}, {"ip": ip}))
        except (DrillError, KeyError):
            out.links.append(None)
    out.count = _count(name, at, res.rows)
    if name in ("dhcp", "ai") and len(res.rows) >= ROWS:
        # Cut at the rows shown (the query's own LIMIT or ours): count them all.
        total = run(f"SELECT count(*) FROM (\n{LIMIT.sub('', sql)}\n) AS q", None, f"{name}.n")  # noqa: S608  # the same shipped or server-built SQL
        out.count = int(total.rows[0][0])
    return out


def _found(at: dict[str, int], rows: list[list[Any]], read: list[str]) -> list[str]:
    if not rows:
        return []
    if "sources" not in at:
        return read
    out: set[str] = set()
    for r in rows:
        v = r[at["sources"]]
        out |= set(v) if isinstance(v, list) else {x for x in str(v or "").split(", ") if x}
    return sorted(out)


def _count(name: Name, at: dict[str, int], rows: list[list[Any]]) -> int:
    if name == "dns":
        return int(rows[0][at["names"]]) if rows and "names" in at else 0
    if name == "access":
        return sum(int(r[at["events"]] or 0) for r in rows) if "events" in at else 0
    return len(rows)
