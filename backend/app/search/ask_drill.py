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

from dataclasses import dataclass, field
from typing import Any

import sqlglot
from sqlglot import exp

from app.search.params import PLACEHOLDER

Scalar = str | int | float | bool | None
COLUMN = "__ask_col__"  # stands for the filtered output column in a filter condition
COLUMNS = "time, source_id, device_hostname, actor_user_name, src_endpoint_ip, message, event_id"
ROWS = 1000


class DrillError(ValueError):
    """The query cannot be drilled into as written."""


@dataclass(frozen=True, slots=True)
class Base:
    where: exp.Expression
    keys: dict[str, exp.Expression]  # output column -> its expression in the query
    filtered: dict[str, exp.Expression] = field(default_factory=dict)  # Ask's filter columns


def _marker(name: str) -> str:
    return f"__p_{name}__"


def base(sql: str, keys: list[str], filtered: list[str] | None = None) -> Base:
    """The query's WHERE and the expression behind each key and each column Ask filtered
    on, or DrillError saying why not. Neither may be an aggregate: an aggregate describes
    the group, not an event, so it cannot pick out events."""
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

    def expr(k: str, what: str) -> exp.Expression:
        e = named.get(k)
        if e is None:
            raise DrillError(f"{what} {k} is not a column the query returns")
        inner: exp.Expression = e.unalias()
        if inner.find(exp.AggFunc) is not None or inner.find(exp.Window) is not None:
            raise DrillError(f"{what} {k} is an aggregate, not a group")
        return inner

    out = {k: expr(k, "key") for k in keys}
    also = {k: expr(k, "filter on") for k in filtered or []}
    return Base(where.this, out, also)


def drill_sql(
    sql: str,
    keys: list[str],
    values: dict[str, Scalar],
    params: dict[str, Any],
    filters: list[tuple[str, str]] | None = None,
) -> str:
    """Events behind one row: the query's WHERE with its parameters written in (except
    `{{start}}` and `{{end}}`, which the Search range fills), each filter Ask added on
    the output (a person, an address) applied to the expression behind that column, and
    each key equal to the row's value. A row's count is then the number of events it
    opens. Values become SQL literals; the guard still checks the result.

    `filters` are (output column, condition) with `__ask_col__` standing for the column,
    as `ask_route.plan` wrote them, and their values in `params`."""
    if set(values) != set(keys):
        raise DrillError("give a value for each key, and only those")
    from app.search.library import literal  # library imports this module

    def fill(text: str) -> str:
        out = PLACEHOLDER.sub(
            lambda m: (
                m.group(0)
                if m.group(1) in ("start", "end")
                else literal(params[m.group(1)])
                if m.group(1) in params
                else m.group(0)
            ),
            text,
        )
        if set(PLACEHOLDER.findall(out)) - {"start", "end"}:
            raise DrillError("a parameter has no value")
        return out

    filters = filters or []
    b = base(fill(sql), keys, [c for c, _ in filters])
    conds: list[exp.Expression] = [exp.Paren(this=b.where.copy())]
    for col, cond in filters:
        inner = b.filtered[col].sql(dialect="duckdb")
        try:
            tree = sqlglot.parse_one(fill(cond).replace(COLUMN, f"({inner})"), read="duckdb")
        except sqlglot.errors.ParseError as exc:
            raise DrillError(f"filter on {col} does not parse") from exc
        conds.append(exp.Paren(this=tree))
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
