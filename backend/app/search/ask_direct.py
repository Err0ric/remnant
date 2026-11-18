"""Direct lookups in Ask (owner, P1 item 6, fix batch of 2026-11-17): a question that is only
an address goes to that address's page, with no model call.

The rule is strict and in code, with no read of the lake: the trimmed question, with at
most one "?" at its end, is one token that is a whole IPv4 or IPv6 address without a scope
id. Host and user names are not matched here: nothing knows every name without scanning the
events (D276), so they go on to the library and the model as before, as does anything else
("who is 10.20.1.5" included).
"""

from __future__ import annotations

import ipaddress
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from app.core.errors import AppError
from app.core.timing import in_context
from app.engine.duckdb import QueryEngine, QueryScope
from app.search import address_page
from app.search.library import Library


@dataclass(slots=True)
class SectionBrief:
    section: str
    title: str
    state: Literal["ok", "no_source", "failed"]
    count_words: str = ""
    read: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Direct:
    kind: Literal["ip"]
    value: str
    window: str  # the window the brief read, in words: "the last 7 days"
    range: str  # the same window as the page's time choice: "7d"
    sections: list[SectionBrief] = field(default_factory=list)  # the page, in brief


def address(question: str) -> str | None:
    """The question when it is only an address: trimmed, one "?" at the end allowed, a
    whole IPv4 or IPv6 address without a scope id (as the address page takes it)."""
    t = question.strip()
    if t.endswith("?"):
        t = t[:-1].rstrip()
    if not t or "%" in t:
        return None
    try:
        ipaddress.ip_address(t)
    except ValueError:
        return None
    return t


def brief(
    engine: QueryEngine,
    library: Library,
    ip: str,
    scope: QueryScope,
    templates: set[str] | None,
    end: datetime,
    services: Sequence[Any] = (),
) -> list[SectionBrief]:
    """The address page's four sections in brief, run side by side as the page runs them.
    A section that fails says so; the others still answer."""

    def one(name: address_page.Name) -> SectionBrief:
        try:
            s = address_page.section(engine, library, name, ip, scope, templates, end, services)
        except AppError:
            return SectionBrief(name, address_page.TITLES[name], "failed")
        words = s.words() if s.state == "ok" else ""
        return SectionBrief(name, address_page.TITLES[name], s.state, words, s.read)

    with ThreadPoolExecutor(max_workers=len(address_page.SECTIONS)) as pool:
        return list(pool.map(in_context(one), list(address_page.SECTIONS)))
