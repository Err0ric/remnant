"""SQL allowlist for user and LLM queries (SPEC 5.1, CLAUDE.md rule 7).

Layer 1. The engine adds two more (ADR-0047): DuckDB's own parser must see one SELECT
statement, and the connection may open only the files its views read, with external
access off and the configuration locked. A guard gap alone cannot read or write files.
"""

import functools
import re
from collections.abc import Iterable
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.scope import traverse_scope

from app.core.errors import QueryBlockedError, QueryRejectedError

DEFAULT_LIMIT = 10_000
MAX_LIMIT = 100_000

# Functions that touch files, the network, settings, or the catalog, run SQL of their own
# (json_execute_serialized_sql and the serializers that feed it), read a file's footer
# (parquet_kv_metadata and the other parquet_* functions), or load keys (T2, 2026-11-08).
_DENIED_FUNCTION = re.compile(
    r"^(read_\w*|\w*_scan|scan_\w*|glob|sniff_csv|getenv|current_setting|duckdb_\w*|pragma_\w*"
    r"|query|query_table|sqlite_\w*|postgres_\w*|mysql_\w*|iceberg_\w*|delta_\w*|http\w*"
    r"|load_extension|install_extension|\w*secret\w*|set_\w*"
    r"|json_\w*serializ\w*|json_execute\w*|parquet_\w*|\w*_credentials)$",
    re.IGNORECASE,
)
_FORBIDDEN_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Command,
    exp.Copy,
    exp.Set,
    exp.Pragma,
    exp.Attach,
    exp.Detach,
    exp.Install,
)


@dataclass(frozen=True, slots=True)
class GuardedQuery:
    sql: str
    applied_limit: int | None  # set when the guard added or lowered the LIMIT


def guard(
    sql: str,
    allowed_tables: Iterable[str],
    default_limit: int = DEFAULT_LIMIT,
    max_limit: int = MAX_LIMIT,
) -> GuardedQuery:
    """Cached by query text, tables and limits (the answer depends on nothing else, and a
    refusal raises again each time): page queries repeat on every load (owner, 2026-11-01)."""
    return _cached(sql, frozenset(allowed_tables), default_limit, max_limit)


@functools.lru_cache(maxsize=512)
def _cached(
    sql: str, allowed_tables: frozenset[str], default_limit: int, max_limit: int
) -> GuardedQuery:
    return _guard(sql, allowed_tables, default_limit, max_limit)


def _guard(
    sql: str,
    allowed_tables: frozenset[str],
    default_limit: int = DEFAULT_LIMIT,
    max_limit: int = MAX_LIMIT,
) -> GuardedQuery:
    text = sql.strip()
    while text.endswith(";"):
        text = text[:-1].rstrip()
    if not text:
        raise QueryRejectedError("Empty query")
    try:
        statements = [s for s in sqlglot.parse(text, read="duckdb") if s is not None]
    except SqlglotError as exc:
        raise QueryRejectedError(
            f"Could not parse SQL as a single SELECT statement: {_first_line(exc)}"
        ) from exc
    if len(statements) != 1:
        raise QueryBlockedError("Only one statement is allowed per query")
    tree = statements[0]
    if not isinstance(tree, exp.Select | exp.SetOperation):
        raise QueryBlockedError(
            "Statement not allowed: only SELECT or WITH ... SELECT can run "
            f"(could not parse a SELECT, got {type(tree).__name__.upper()})"
        )
    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise QueryBlockedError(f"Statement not allowed inside a query: {type(node).__name__}")

    _check_tables(tree, allowed_tables)
    _check_functions(tree)
    return _apply_limit(tree, default_limit, max_limit)


def guard_sql(
    sql: str,
    allowed_tables: frozenset[str],
    default_limit: int = DEFAULT_LIMIT,
    max_limit: int = MAX_LIMIT,
) -> str:
    return guard(sql, allowed_tables, default_limit, max_limit).sql


_PLAIN_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def _check_tables(tree: exp.Expression, allowed: frozenset[str]) -> None:
    for cte in tree.find_all(exp.CTE):
        if not _PLAIN_NAME.match(cte.alias_or_name):
            raise QueryRejectedError(
                f"CTE names must be plain identifiers: {cte.alias_or_name[:60]}"
            )
    allowed_lower = {t.lower() for t in allowed}
    # Scope-aware: a CTE name only counts inside the query that defines it, so a CTE in
    # one branch cannot whitelist the same name elsewhere (review finding S5).
    try:
        scopes = traverse_scope(tree)
    except Exception as exc:  # unanalysable query: refuse rather than guess
        raise QueryRejectedError("Query structure could not be analysed") from exc
    for scope in scopes:
        for source in scope.sources.values():
            if isinstance(source, exp.Table):
                _check_table_shape(source)
            if isinstance(source, exp.Table) and source.name.lower() not in allowed_lower:
                raise QueryRejectedError(
                    f"Unknown table: {source.name[:60]}. Query the events table"
                )
    ctes = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    permitted = allowed_lower | ctes
    for table in tree.find_all(exp.Table):
        _check_table_shape(table)
        if table.name.lower() not in permitted:
            raise QueryRejectedError(f"Unknown table: {table.name[:60]}. Query the events table")


def _check_table_shape(table: exp.Table) -> None:
    """A table function, a qualified name, or a file path is a block, not a typo (D237)."""
    if not isinstance(table.this, exp.Identifier):
        raise QueryBlockedError(
            "Table functions are not allowed; query the events table "
            f"(found {table.this.sql(dialect='duckdb')[:60]})"
        )
    if table.args.get("db") or table.args.get("catalog"):
        raise QueryBlockedError(f"Qualified table names are not allowed: {table.sql()[:60]}")
    if not _PLAIN_NAME.match(table.name):
        raise QueryBlockedError(
            f"File paths and quoted table names are not allowed: {table.name[:60]}"
        )


def _check_functions(tree: exp.Expression) -> None:
    for func in tree.find_all(exp.Func):
        name = func.name if isinstance(func, exp.Anonymous) else func.sql_name()
        if _DENIED_FUNCTION.match(name or ""):
            raise QueryBlockedError(f"Function not allowed: {name.lower()}")
        _check_size(func, (name or "").lower())


# Functions that build a value or a row set from a number in the query. A literal past
# these sizes is refused up front; anything computed is left to the engine's memory limit
# and the server's address-space limit (D58).
MAX_SERIES_ROWS = 100_000_000
MAX_BUILT_LENGTH = 10_000_000


def _number(node: exp.Expression | None) -> float | None:
    if isinstance(node, exp.Neg):
        inner = _number(node.this)
        return -inner if inner is not None else None
    if isinstance(node, exp.Literal) and not node.is_string:
        try:
            return float(node.this)
        except ValueError:
            return None
    return None


def _check_size(func: exp.Func, name: str) -> None:
    if isinstance(func, exp.GenerateSeries):
        start, end = _number(func.args.get("start")), _number(func.args.get("end"))
        step = _number(func.args.get("step")) if func.args.get("step") is not None else 1.0
        if func.args.get("start") is not None and func.args.get("end") is None:
            start, end = 0.0, start  # range(n)
        if start is not None and end is not None and step:
            if abs(end - start) / abs(step) > MAX_SERIES_ROWS:
                raise QueryRejectedError(
                    f"Series too large: at most {MAX_SERIES_ROWS:,} rows from range or "
                    "generate_series"
                )
        return
    sizes: list[exp.Expression | None] = []
    if isinstance(func, exp.Repeat):
        sizes = [func.args.get("times")]
    elif isinstance(func, exp.Pad):
        sizes = [func.args.get("expression")]
    elif name in ("list_resize", "array_resize") and isinstance(func, exp.Anonymous):
        sizes = func.expressions[1:2]
    for size in sizes:
        n = _number(size)
        if n is not None and n > MAX_BUILT_LENGTH:
            raise QueryRejectedError(
                f"Value too large: {name or 'this function'} may build at most "
                f"{MAX_BUILT_LENGTH:,} items"
            )


def _apply_limit(tree: exp.Query, default_limit: int, max_limit: int) -> GuardedQuery:
    limit = tree.args.get("limit")
    current = _int_literal(limit.expression) if isinstance(limit, exp.Limit) else None
    if isinstance(limit, exp.Limit) and limit.args.get("limit_options") is not None:
        # LIMIT n PERCENT or WITH TIES is not a row count; cap it with an outer LIMIT (S3).
        out = exp.select("*").from_(tree.subquery("_q")).limit(max_limit)
        return GuardedQuery(out.sql(dialect="duckdb"), max_limit)
    if limit is not None and current is not None and current <= max_limit:
        return GuardedQuery(tree.sql(dialect="duckdb"), None)

    target = default_limit if limit is None else max_limit
    if isinstance(tree, exp.Select) and (limit is None or current is not None):
        out = tree.limit(target, copy=True)
    else:
        out = exp.select("*").from_(tree.subquery("_q")).limit(target)
    return GuardedQuery(out.sql(dialect="duckdb"), target)


def _int_literal(node: exp.Expression | None) -> int | None:
    if isinstance(node, exp.Literal) and node.is_int:
        return int(node.this)
    return None


def _first_line(exc: Exception) -> str:
    return str(exc).splitlines()[0][:200] if str(exc) else type(exc).__name__
