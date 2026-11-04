"""The answer step of Ask, without a model (ADR-0042 row 8, slice 1c).

The headline is written here, by code, from the result: a library query's `answer`
template when it has one, otherwise the row count and the first row. It is never model
text. This module also picks the rows a model may summarize and checks the statements it
returns: a statement stays only when it cites at least one event id and every id it cites
was in the rows sent (C1: uncited statements are removed, and the answer says so).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ANSWER_ROWS = 20  # rows a model may see (ADR-0042 row 8)
MAX_VALUE = 300  # characters per value sent
MAX_COLUMNS = 12
MAX_CHARS = 7_000  # the rows as JSON, about 2,000 tokens: the answer prompt stays small
MAX_CLAIMS = 5
FIRST_COLUMNS = 3  # values of the first row shown in a generic headline

# `{n}` rows, `{first.<col>}` the first row's value, `{count.<col>}` rows whose value is a
# real one (not blank, not a "(...)" label such as "(no account reported)"), and
# `{items.<col>}` the comma-separated real values across all rows. A count may carry its
# words, `{count.person|person|people}`: "1 person", "3 people" (D205).
TEMPLATE = re.compile(
    r"\{(n|first\.[a-z_][a-z0-9_]{0,63}|count\.[a-z_][a-z0-9_]{0,63}|items\.[a-z_][a-z0-9_]{0,63})"
    r"(?:\|([a-z][a-z ]{0,29})\|([a-z][a-z ]{0,29}))?\}"
)


def _real(value: Any) -> bool:
    text = "" if value is None else str(value).strip()
    return bool(text) and not text.startswith("(")


def _count(key: str, columns: list[str], rows: list[list[Any]]) -> int | None:
    kind, _, col = key.partition(".")
    if kind == "n":
        return len(rows)
    if col not in columns:
        return None
    i = columns.index(col)
    if kind == "count":
        return sum(1 for r in rows if _real(r[i]))
    return sum(sum(1 for x in str(r[i]).split(", ") if _real(x)) for r in rows if r[i] is not None)


def _zone(tz: str | None) -> ZoneInfo | None:
    if not tz:
        return None
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _show(value: Any, tz: str | None = None) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    if isinstance(value, datetime):
        # The asker's zone, as times read everywhere else (owner, 2026-11-04); UTC when the
        # browser sent none or an unknown one.
        zone = _zone(tz)
        if zone is None or value.tzinfo is None:
            return value.strftime("%Y-%m-%d %H:%M UTC")
        local = value.astimezone(zone)
        hour = local.strftime("%I").lstrip("0") or "12"
        return f"{local.strftime('%b')} {local.day}, {hour}:{local.strftime('%M %p %Z')}"
    if isinstance(value, date):
        return value.isoformat()
    text = str(value)
    return text if len(text) <= 80 else text[:79] + "…"


def _rows(n: int) -> str:
    return "1 row" if n == 1 else f"{n:,} rows"


def headline(
    columns: list[str],
    rows: list[list[Any]],
    truncated: bool,
    template: str | None = None,
    tz: str | None = None,
) -> str:
    """One sentence about the result, written by code. A template names `{n}` (rows) and
    `{first.<column>}` (the first row's value); when the result cannot fill it, the
    generic headline is used instead, so a headline never shows a blank."""
    n = len(rows)
    if n == 0:
        return "No matching rows in this time range."
    first = dict(zip(columns, rows[0], strict=False))
    if template:
        names = [m[0] for m in TEMPLATE.findall(template)]
        if all(
            (k.removeprefix("first.") in first)
            if k.startswith("first.")
            else _count(k, columns, rows) is not None
            for k in names
        ):

            def fill(m: re.Match[str]) -> str:
                key, one, many = m.group(1), m.group(2), m.group(3)
                if key.startswith("first."):
                    return _show(first[key.removeprefix("first.")], tz)
                c = _count(key, columns, rows) or 0
                return f"{c:,} {one if c == 1 else many}" if one else f"{c:,}"

            text = TEMPLATE.sub(fill, template)
            return text + (" (more rows than shown)" if truncated else "")
    shown = [(c, v) for c, v in first.items() if c != "event_id" and v is not None]
    if n == 1 and len(columns) <= 4:
        return "; ".join(f"{c}: {_show(v, tz)}" for c, v in shown) or "1 row."
    count = f"More than {n:,} rows" if truncated else _rows(n)
    lead = ", ".join(f"{c} {_show(v, tz)}" for c, v in shown[:FIRST_COLUMNS])
    return f"{count}. First row: {lead}." if lead else f"{count}."


@dataclass(frozen=True, slots=True)
class Sample:
    """What a model may see of a result: at most 20 rows, 12 columns, and 300 characters a
    value, under about 2,000 tokens, with the event ids it may cite."""

    columns: list[str]
    rows: list[list[Any]]
    event_ids: frozenset[str]
    row_count: int
    truncated: bool


def sample(columns: list[str], rows: list[list[Any]], truncated: bool) -> Sample | None:
    """None when the rows carry no `event_id` column: there is nothing a statement could
    cite, so no summary is written (owner 2026-11-02: if a summary cannot cite, show the
    rows without one)."""
    if "event_id" not in columns:
        return None
    keep = ["event_id", *[c for c in columns if c != "event_id"]][:MAX_COLUMNS]
    at = [columns.index(c) for c in keep]
    out: list[list[Any]] = []
    size = 0
    for r in rows[:ANSWER_ROWS]:
        row = [_cut(r[i]) for i in at]
        if row[0] is None:
            continue
        row[0] = str(row[0]).lower()
        size += len(json.dumps(row, default=str))
        if out and size > MAX_CHARS:
            break
        out.append(row)
    if not out:
        return None
    ids = frozenset(str(r[0]) for r in out)
    return Sample(keep, out, ids, len(rows), truncated)


def _cut(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_VALUE:
        return value[:MAX_VALUE] + "…"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


@dataclass(frozen=True, slots=True)
class Checked:
    claims: list[tuple[str, list[str]]]  # (text, event ids) that cite only sent rows
    removed: int


def check_claims(claims: list[tuple[str, list[str]]], sent: frozenset[str]) -> Checked:
    """Keep a statement only when it cites at least one event id and every id it cites
    was sent; at most five. Ids compare lowercase, as stored."""
    kept: list[tuple[str, list[str]]] = []
    removed = 0
    for text, ids in claims:
        cited = list(dict.fromkeys(i.strip().lower() for i in ids if i.strip()))
        if cited and set(cited) <= sent and len(kept) < MAX_CLAIMS:
            kept.append((text, cited))
        elif not (cited and set(cited) <= sent):
            removed += 1
    return Checked(kept, removed)


def removed_note(removed: int, kept: int) -> str | None:
    if removed == 0:
        return None
    if kept == 0:
        return "No summary: the model's statements did not cite these rows."
    if removed == 1:
        return "1 statement removed: it cited no events from these rows."
    return f"{removed} statements removed: they cited no events from these rows."
