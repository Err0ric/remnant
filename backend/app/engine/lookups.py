"""SQL functions for local lookups (ADR-0039 row 4): `ip_country`, `ip_asn`, `ip_org`, and
`is_internal`, registered on every query connection.

They answer from the local GeoIP files and the install's Internal networks list, in the
server process, with no network access. Values from the lake are untrusted text: anything
that is not an address answers NULL (false for `is_internal`). Answers are cached per
query, so an address seen on many rows is looked up once.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import duckdb
import pyarrow as pa
from duckdb.func import FunctionNullHandling, PythonUDFType

# country code, ASN, organization; None when the address is not public or not listed.
Geo = Callable[[str], tuple[str | None, int | None, str | None] | None]


@dataclass(frozen=True, slots=True)
class Lookups:
    geo: Geo
    # Called once per query: returns the membership test for the list in force now.
    internal: Callable[[], Callable[[str], bool]]


FUNCTIONS = ("ip_country", "ip_asn", "ip_org", "is_internal")


def register(con: duckdb.DuckDBPyConnection, lookups: Lookups) -> None:
    geo_cache: dict[str, tuple[str | None, int | None, str | None] | None] = {}
    internal_cache: dict[str, bool] = {}
    test: list[Callable[[str], bool]] = []

    def geo(value: str) -> tuple[str | None, int | None, str | None] | None:
        if value not in geo_cache:
            if len(geo_cache) > 200_000:
                geo_cache.clear()
            geo_cache[value] = lookups.geo(value)
        return geo_cache[value]

    def country(value: str) -> str | None:
        found = geo(value)
        return found[0] if found else None

    def asn(value: str) -> int | None:
        found = geo(value)
        return found[1] if found else None

    def org(value: str) -> str | None:
        found = geo(value)
        return found[2] if found else None

    def internal(value: str) -> bool:
        if value not in internal_cache:
            if not test:
                test.append(lookups.internal())
            if len(internal_cache) > 200_000:
                internal_cache.clear()
            internal_cache[value] = test[0](value)
        return internal_cache[value]

    # Arrow functions: DuckDB passes a column at a time, not a row.
    def column(fn: Callable[[str], object], kind: pa.DataType) -> Callable[[pa.Array], pa.Array]:
        def run(values: pa.Array) -> pa.Array:
            return pa.array([None if v is None else fn(v) for v in values.to_pylist()], type=kind)

        return run

    varchar, integer, boolean = (duckdb.sqltype(t) for t in ("VARCHAR", "INTEGER", "BOOLEAN"))
    for name, fn, ret, kind in (
        ("ip_country", country, varchar, pa.string()),
        ("ip_asn", asn, integer, pa.int32()),
        ("ip_org", org, varchar, pa.string()),
        ("is_internal", internal, boolean, pa.bool_()),
    ):
        con.create_function(
            name,
            column(fn, kind),
            [varchar],
            ret,
            type=PythonUDFType.ARROW,
            null_handling=FunctionNullHandling.SPECIAL,
            side_effects=False,
        )
