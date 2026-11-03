""" "Show events" for a row of an aggregate Ask answer (owner, 2026-11-02; D173).

A library query lists its group keys (`keys`: output columns such as `user` or `address`).
From the query's own SQL, code builds an events query: the same table, the same WHERE
(time range and parameters included), plus one condition per key, `<the key's own
expression> = <the row's value>`. Nothing is guessed and no model is called. The SQL goes
to the Search editor, where it runs through the guard on the caller's own view and is
audited like any query.

Only plain queries qualify: one SELECT from `events` with a WHERE and a GROUP BY, no WITH,
no join, and keys that are not aggregates. `check` refuses a pack that marks keys on any
other shape, so a broken drill fails in review, not on screen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import sqlglot
from sqlglot import exp

from app.search.params import PLACEHOLDER

Scalar = str | int | float | bool | None
COLUMNS = "time, source_id, device_hostname, actor_user_name, src_endpoint_ip, message, event_id"
ROWS = 1000


class DrillError(ValueError):
    """The query cannot be drilled into as written."""


@dataclass(frozen=True, slots=True)
class Base:
    where: exp.Expression
    keys: dict[str, exp.Expression]  # output column -> its expression in the query


def _marker(name: str) -> str:
    return f"__p_{name}__"


def base(sql: str, keys: list[str]) -> Base:
    """The query's WHERE and each key's expression, or DrillError saying why not."""
    text = PLACEHOLDER.sub(lambda m: _marker(m.group(1)), sql)
    try:
        tree = sqlglot.parse_one(text, read="duckdb")
    except sqlglot.errors.ParseError as exc:
        raise DrillError(f"does not parse: {str(exc)[:120]}") from exc
    if not isinstance(tree, exp.Select) or tree.args.get("with_", tree.args.get("with")):
        raise DrillError("only a plain SELECT (no WITH, no UNION) can be drilled into")
    source = tree.args.get("from_")
    table = source.this if source is not None else None
    if not isinstance(table, exp.Table) or table.name != "events" or tree.args.get("joins"):
        raise DrillError("must read only from events")
    where = tree.args.get("where")
    if where is None or tree.args.get("group") is None:
        raise DrillError("needs a WHERE and a GROUP BY")
    named = {e.alias_or_name: e for e in tree.expressions}
    out: dict[str, exp.Expression] = {}
    for k in keys:
        e = named.get(k)
        if e is None:
            raise DrillError(f"key {k} is not a column the query returns")
        inner = e.unalias()
        if inner.find(exp.AggFunc) is not None or inner.find(exp.Window) is not None:
            raise DrillError(f"key {k} is an aggregate, not a group")
        out[k] = inner
    return Base(where.this, out)


def drill_sql(
    sql: str,
    keys: list[str],
    values: dict[str, Scalar],
    params: dict[str, Any],
) -> str:
    """Events behind one row: the query's WHERE with its parameters written in (except
    `{{start}}` and `{{end}}`, which the Search range fills), and each key equal to the
    row's value. Values become SQL literals; the guard still checks the result."""
    if set(values) != set(keys):
        raise DrillError("give a value for each key, and only those")
    from app.search.library import literal  # library imports this module

    text = PLACEHOLDER.sub(
        lambda m: (
            m.group(0)
            if m.group(1) in ("start", "end")
            else literal(params[m.group(1)])
            if m.group(1) in params
            else m.group(0)
        ),
        sql,
    )
    if set(PLACEHOLDER.findall(text)) - {"start", "end"}:
        raise DrillError("a parameter has no value")
    b = base(text, keys)
    conds: list[exp.Expression] = [exp.Paren(this=b.where.copy())]
    for k in keys:
        v = values[k]
        if isinstance(v, (dict, list)):
            raise DrillError(f"{k} must be a single value")
        e = b.keys[k].copy()
        if v is None:
            conds.append(exp.Is(this=e, expression=exp.Null()))
        else:
            right = sqlglot.parse_one(literal(v), read="duckdb")
            conds.append(exp.EQ(this=e, expression=right))
    where = exp.and_(*conds)
    query = (
        exp.select(*[c.strip() for c in COLUMNS.split(",")])
        .from_("events")
        .where(where)
        .order_by("coalesce(time, time_observed) DESC")
        .limit(ROWS)
    )
    out = query.sql(dialect="duckdb", pretty=True)
    for name in ("start", "end"):
        out = out.replace(_marker(name), "{{" + name + "}}")
    return out
