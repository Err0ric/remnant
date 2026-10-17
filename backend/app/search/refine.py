"""Add one field filter to the SQL on screen (a facet click in SQL or Ask mode, ADR-0016).

The condition is built as a syntax tree, never by pasting text: the value becomes a quoted
literal and the field must be one of the fixed facet columns. The result is shown in the
editor and goes through the guard like any other query when it runs.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from app.core.errors import SearchInvalidError

NUMERIC = frozenset({"severity_id", "status_id", "class_uid"})


def refine_sql(
    sql: str, field: str, value: str | None, exclude: bool, allowed: tuple[str, ...]
) -> str:
    if field not in allowed:
        raise SearchInvalidError(f"{field} cannot be used as a quick filter")
    try:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except SqlglotError as exc:
        raise SearchInvalidError("The SQL could not be read; add the filter in the editor") from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise SearchInvalidError(
            "Quick filters work on a single SELECT; add the condition in the editor"
        )
    tree = statements[0]
    column = exp.column(field)
    if value is None or value == "":
        cond: exp.Expression = exp.Not(this=exp.Is(this=column, expression=exp.Null()))
        if not exclude:
            cond = exp.Is(this=column, expression=exp.Null())
    else:
        literal = (
            exp.Literal.number(value)
            if field in NUMERIC and value.isdigit()
            else exp.Literal.string(value)
        )
        cond = exp.NullSafeNEQ(this=column, expression=literal) if exclude else column.eq(literal)
    return tree.where(cond, copy=True).sql(dialect="duckdb", pretty=True)
