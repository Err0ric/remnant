"""Sources a query pins with `source_id`, so the engine reads only those (trial finding).

A filter such as `WHERE source_id = 'dns'` only drops rows after every source in scope
has been opened, so the result said "3 sources" for a query that used one. When the
query's top level provably limits `source_id` to literal values (or bound values, as
Simple search sends), the scope can be narrowed to them with an identical result. Only
narrowing: the scope from the caller's grants is intersected, never widened. Anything
this cannot prove (an OR, a subquery or CTE over events, a join, events read twice)
returns None and the full scope is used.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import sqlglot
from sqlglot import exp


def _value(node: exp.Expression, params: Mapping[str, Any]) -> str | None:
    if isinstance(node, exp.Literal) and node.is_string:
        return str(node.this)
    if isinstance(node, exp.Placeholder | exp.Parameter):
        value = params.get(str(node.name))
        return value if isinstance(value, str) else None
    return None


def pinned_sources(sql: str, params: Mapping[str, Any] | None = None) -> set[str] | None:
    """The source ids the query can only read from, or None when unknown."""
    return _pinned(sql, params, "source_id")


def pinned_templates(sql: str, params: Mapping[str, Any] | None = None) -> set[str] | None:
    """The template ids the query can only match, or None when unknown: the engine leaves
    out sources whose files hold none of them, so a Microsoft 365 query is said to read
    Microsoft 365 sources only (owner, 2026-10-31)."""
    return _pinned(sql, params, "template_id")


def _pinned(sql: str, params: Mapping[str, Any] | None, column: str) -> set[str] | None:
    """The set of values of `column` the query can only read, or None when unknown.

    Structural checks, not argument names (sqlglot renames keys between versions): any
    CTE, subquery, set operation, join, or second read of `events` means None. Every
    mention of `source_id` in the WHERE must be a recognised pin (`=` or `IN` with
    literal or bound string values, ANDed at the top level); an OR, a function on
    `source_id`, or anything else means None."""
    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
    except sqlglot.errors.ParseError:
        return None
    if not isinstance(tree, exp.Select):
        return None
    if any(tree.find_all(exp.With, exp.CTE, exp.Subquery, exp.Union, exp.Join)):
        return None
    if any(isinstance(n, exp.Select) for n in tree.find_all(exp.Select) if n is not tree):
        return None
    events = [t for t in tree.find_all(exp.Table) if t.name.lower() == "events"]
    if len(events) != 1 or len(list(tree.find_all(exp.Table))) != 1:
        return None
    names = {"events", events[0].alias_or_name.lower()}
    where = tree.args.get("where")
    if where is None:
        return None
    conjuncts = list(where.this.flatten()) if isinstance(where.this, exp.And) else [where.this]
    pinned: set[str] | None = None
    used: set[int] = set()
    for cond in conjuncts:
        values: list[str | None] | None = None
        if isinstance(cond, exp.EQ):
            col, other = cond.this, cond.expression
            if not isinstance(col, exp.Column):
                col, other = other, col
            if isinstance(col, exp.Column) and _is_col(col, names, column):
                values = [_value(other, params or {})]
                used.add(id(col))
        elif isinstance(cond, exp.In) and isinstance(cond.this, exp.Column):
            if _is_col(cond.this, names, column) and not cond.args.get("query"):
                values = [_value(v, params or {}) for v in cond.expressions]
                used.add(id(cond.this))
        if values is None:
            continue
        if any(v is None for v in values):
            return None  # a source filter we cannot read: do not guess
        found = {v for v in values if v is not None}
        pinned = found if pinned is None else pinned & found
    # Any other mention of the column in the WHERE (inside an OR, a function, a CASE):
    # the pins above may not be the whole story, so do not narrow.
    for col in where.find_all(exp.Column):
        if _is_col(col, names, column) and id(col) not in used:
            return None
    return pinned


def _is_col(col: exp.Column, table_names: set[str], column: str) -> bool:
    return col.name.lower() == column and (not col.table or col.table.lower() in table_names)
