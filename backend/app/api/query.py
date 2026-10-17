"""POST /api/query: run guarded SQL against the caller's events view. Router only."""

import re
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field, StringConstraints
from starlette.concurrency import run_in_threadpool

from app.api.access import CurrentUser, client_ip
from app.auth.service import AuthService
from app.auth.users import User
from app.core.errors import AppError, SearchInvalidError
from app.engine.duckdb import QueryEngine, QueryResult, QueryScope
from app.engine.export import to_csv
from app.engine.views import permitted_sources, scope_sources
from app.meta.db import MetaDB
from app.search.presets import presets
from app.search.refine import refine_sql
from app.search.simple import MAX_TEXT, compile_search

router = APIRouter(tags=["query"])
Scalar = Annotated[str, StringConstraints(max_length=2048)] | int | float | bool | None


class QueryRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=20_000)
    start: datetime | None = None
    end: datetime | None = None
    # A filter only: intersected with the sources the caller may read, never a grant.
    sources: list[str] | None = Field(default=None, max_length=200)
    # Values for $name placeholders (Simple search sends these). Bound by the driver,
    # never formatted into the SQL.
    params: dict[Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,30}$")], Scalar] = (
        Field(default_factory=dict, max_length=100)
    )


class QueryResponse(BaseModel):
    columns: list[str]
    rows: list[list[object]]
    row_count: int
    truncated: bool
    elapsed_ms: int
    executed_sql: str
    sources: list[str]


async def _run_audited(
    body: QueryRequest, request: Request, user: User, action: str
) -> QueryResult:
    engine: QueryEngine = request.app.state.engine
    auth: AuthService = request.app.state.auth
    meta: MetaDB = request.app.state.meta
    # Scope comes from the caller's grants; the client list can only narrow it (rule 13).
    allowed = await run_in_threadpool(permitted_sources, meta, user)
    sources = scope_sources(allowed, body.sources)
    scope = QueryScope(sources=sources, start=body.start, end=body.end)
    detail: dict[str, object] = {
        "sql": body.sql[:4000],
        "params": body.params,
        "sources_requested": body.sources,
        "sources_in_scope": "all" if sources is None else sources,
    }
    try:
        result = await run_in_threadpool(engine.run, body.sql, scope, body.params or None)
    except AppError as exc:
        detail["error"] = type(exc).__name__
        await run_in_threadpool(
            auth.audit.write, action, "failure", user.user_id, client_ip(request), detail
        )
        raise
    detail |= {
        "rows": len(result.rows),
        "elapsed_ms": result.elapsed_ms,
        "sources_in_scope": result.sources,  # sources actually read
    }
    await run_in_threadpool(
        auth.audit.write, action, "success", user.user_id, client_ip(request), detail
    )
    return result


@router.post("/query")
async def run_query(body: QueryRequest, request: Request, user: CurrentUser) -> QueryResponse:
    result = await _run_audited(body, request, user, "query.run")
    return QueryResponse(
        columns=result.columns,
        rows=result.rows,
        row_count=len(result.rows),
        truncated=result.truncated,
        elapsed_ms=result.elapsed_ms,
        executed_sql=result.executed_sql,
        sources=result.sources,
    )


@router.post("/query/export")
async def export_query(body: QueryRequest, request: Request, user: CurrentUser) -> Response:
    """The same query as /query, returned as CSV and audited as an export (T18)."""
    result = await _run_audited(body, request, user, "query.export")
    return Response(
        content=to_csv(result.columns, result.rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="search-results.csv"'},
    )


class CompileRequest(BaseModel):
    text: str = Field(max_length=MAX_TEXT)
    top: str | None = Field(default=None, min_length=1, max_length=128)


class CompileResponse(BaseModel):
    sql: str
    params: dict[str, Any]
    notes: list[str]
    columns: list[str]  # schema columns the search filters on


@router.post("/search/compile")
async def compile_simple(body: CompileRequest, _: CurrentUser) -> CompileResponse:
    """Simple search text to SQL and parameters (ADR-0009). Reads no data; the query that
    follows goes through /query, its guard, and its audit like any other."""
    out = compile_search(body.text, body.top)
    return CompileResponse(sql=out.sql, params=out.params, notes=out.notes, columns=out.columns)


# --- facets (ADR-0016 row 2) ------------------------------------------------------------

FACET_COLUMNS = (
    "source_id",
    "device_hostname",
    "actor_user_name",
    "src_endpoint_ip",
    "dst_endpoint_hostname",
    "dst_endpoint_ip",
    "severity_id",
    "status_id",
    "class_uid",
    "parse_status",
)
FACET_VALUES = 10
FACET_TIMEOUT_S = 10.0
_TRAILING = re.compile(r"[\s;]+$")


class FacetRequest(BaseModel):
    # Either a Simple search (`text`, compiled here over every column) or the SQL on
    # screen (`sql`, with the result's `columns`; only fixed facet columns among them).
    text: str | None = Field(default=None, max_length=MAX_TEXT)
    sql: str | None = Field(default=None, min_length=1, max_length=20_000)
    params: dict[Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,30}$")], Scalar] = (
        Field(default_factory=dict, max_length=100)
    )
    columns: list[str] = Field(default_factory=list, max_length=200)
    start: datetime | None = None
    end: datetime | None = None
    sources: list[str] | None = Field(default=None, max_length=200)


class FacetValue(BaseModel):
    value: str | None
    count: int


class Facet(BaseModel):
    field: str
    values: list[FacetValue]


class FacetResponse(BaseModel):
    facets: list[Facet]
    elapsed_ms: int


def facet_sql(sql: str, columns: list[str]) -> str:
    """Top values per facet column over the caller's query, in one statement. The query
    itself is the caller's (it still goes through the guard as part of this one); the
    rest is fixed text and column names from FACET_COLUMNS."""
    wanted = [c for c in FACET_COLUMNS if c in set(columns)]
    branch = (
        "(SELECT '{c}' AS facet, CAST(\"{c}\" AS VARCHAR) AS value, count(*) AS n"
        " FROM q GROUP BY 2 ORDER BY 3 DESC, 2 NULLS LAST LIMIT {n})"
    )
    branches = [branch.format(c=c, n=FACET_VALUES) for c in wanted]
    inner = _TRAILING.sub("", sql)
    return (
        f"WITH q AS (\n{inner}\n)\nSELECT facet, value, n FROM (\n"
        + "\nUNION ALL\n".join(branches)
        + "\n) f"
    )


@router.post("/search/facets")
async def search_facets(body: FacetRequest, request: Request, user: CurrentUser) -> FacetResponse:
    """Counts of the top values of a few fixed fields for the search on screen, over the
    whole result (not just the page). Same scope, guard, and audit as /query."""
    if body.text is not None:
        compiled = compile_search(body.text, select="*")
        query, params = compiled.sql, compiled.params
        wanted = list(FACET_COLUMNS)
    elif body.sql is not None:
        query, params = body.sql, dict(body.params)
        wanted = [c for c in FACET_COLUMNS if c in set(body.columns)]
    else:
        raise SearchInvalidError("Send the search text or the SQL")
    if not wanted:
        return FacetResponse(facets=[], elapsed_ms=0)
    engine: QueryEngine = request.app.state.engine
    auth: AuthService = request.app.state.auth
    meta: MetaDB = request.app.state.meta
    allowed = await run_in_threadpool(permitted_sources, meta, user)
    sources = scope_sources(allowed, body.sources)
    scope = QueryScope(sources=sources, start=body.start, end=body.end)
    detail: dict[str, object] = {
        "sql": query[:4000],
        "params": params,
        "facets": wanted,
        "sources_in_scope": "all" if sources is None else sources,
    }
    sql = facet_sql(query, wanted)
    try:
        result = await run_in_threadpool(
            lambda: engine.run(sql, scope, params or None, timeout_s=FACET_TIMEOUT_S)
        )
    except AppError as exc:
        detail["error"] = type(exc).__name__
        await run_in_threadpool(
            auth.audit.write, "query.facets", "failure", user.user_id, client_ip(request), detail
        )
        raise
    detail["sources_in_scope"] = result.sources
    await run_in_threadpool(
        auth.audit.write, "query.facets", "success", user.user_id, client_ip(request), detail
    )
    grouped: dict[str, list[FacetValue]] = {c: [] for c in wanted}
    for facet, value, n in result.rows:
        grouped[str(facet)].append(FacetValue(value=value, count=int(n)))
    return FacetResponse(
        facets=[Facet(field=c, values=v) for c, v in grouped.items() if v],
        elapsed_ms=result.elapsed_ms,
    )


class RefineRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=20_000)
    field: str = Field(max_length=64)
    value: str | None = Field(default=None, max_length=4096)
    exclude: bool = False


class RefineResponse(BaseModel):
    sql: str


@router.post("/query/refine")
async def query_refine(body: RefineRequest, _: CurrentUser) -> RefineResponse:
    """The SQL on screen with one facet filter added (ADR-0016 row 2). Reads no data; the
    caller runs the result like any query, through the guard and the audit log."""
    sql = await run_in_threadpool(
        refine_sql, body.sql, body.field, body.value, body.exclude, FACET_COLUMNS
    )
    return RefineResponse(sql=sql)


class PresetOut(BaseModel):
    id: str
    name: str
    description: str
    text: str


@router.get("/search/presets")
async def search_presets(_: CurrentUser) -> list[PresetOut]:
    """Suspicious presets (ADR-0016 row 3): Simple search text to put in the bar."""
    return [PresetOut(**p.model_dump()) for p in presets()]
