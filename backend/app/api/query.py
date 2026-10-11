"""POST /api/query: run guarded SQL against the caller's events view. Router only."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field, StringConstraints
from starlette.concurrency import run_in_threadpool

from app.api.access import CurrentUser, client_ip
from app.auth.service import AuthService
from app.auth.users import User
from app.core.errors import AppError
from app.engine.duckdb import QueryEngine, QueryResult, QueryScope
from app.engine.export import to_csv
from app.engine.views import permitted_sources, scope_sources
from app.meta.db import MetaDB
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
