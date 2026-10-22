"""/api/searches: saved searches (SPEC 5.4). Router only.

Runs use the caller's source scope and the caller's audit identity, never the author's.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from app.api.access import AdminUser, CurrentUser, client_ip, require_role
from app.api.query import QueryResponse
from app.auth.service import AuthService
from app.auth.users import User
from app.core import safeyaml
from app.core.errors import AppError, PayloadTooLargeError, SearchInvalidError
from app.engine.duckdb import QueryEngine, QueryScope
from app.engine.views import permitted_sources, scope_sources
from app.meta.db import MetaDB
from app.search.params import bind, compile_sql
from app.search.saved import SavedSearch, SavedSearchIn, SavedSearchStore
from app.search.schedules import ScheduleService

router = APIRouter(tags=["searches"])

# Auditors are read-only (SPEC 3.6): they run shared searches but do not author them.
AuthorUser = Annotated[User, Depends(require_role("admin", "analyst"))]
MAX_IMPORT_BYTES = 256 * 1024
SERVER_FIELDS = ("schema_version", "owner_id", "created_at", "updated_at", "verified")


class RunRequest(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict, max_length=20)
    start: datetime | None = None
    end: datetime | None = None
    sources: list[str] | None = Field(default=None, max_length=200)


def _store(request: Request) -> SavedSearchStore:
    store: SavedSearchStore = request.app.state.searches
    return store


def _audit(request: Request, action: str, outcome: str, user: User, detail: dict[str, Any]) -> None:
    auth: AuthService = request.app.state.auth
    auth.audit.write(action, outcome, user.user_id, client_ip(request), detail)  # type: ignore[arg-type]  # outcome literal checked by callers


@router.get("/searches")
async def list_searches(
    request: Request, user: CurrentUser, tag: str | None = None
) -> list[SavedSearch]:
    return await run_in_threadpool(_store(request).visible, user, tag)


@router.get("/searches/{search_id}")
async def get_search(search_id: str, request: Request, user: CurrentUser) -> SavedSearch:
    return await run_in_threadpool(_store(request).get, search_id, user)


@router.post("/searches", status_code=status.HTTP_201_CREATED)
async def create_search(body: SavedSearchIn, request: Request, user: AuthorUser) -> SavedSearch:
    created = await run_in_threadpool(_store(request).create, body, user)
    await run_in_threadpool(
        _audit, request, "search.create", "success", user, {"search_id": body.id}
    )
    return created


@router.put("/searches/{search_id}")
async def update_search(
    search_id: str, body: SavedSearchIn, request: Request, user: AuthorUser
) -> SavedSearch:
    updated = await run_in_threadpool(_store(request).update, search_id, body, user)
    await run_in_threadpool(
        _audit, request, "search.update", "success", user, {"search_id": search_id}
    )
    # The editor's own schedules of this search take the change and note it (F37).
    schedules: ScheduleService = request.app.state.schedules
    for schedule_id in await run_in_threadpool(schedules.accept_search_change, search_id, user):
        await run_in_threadpool(
            _audit,
            request,
            "schedule.update",
            "success",
            user,
            {"schedule_id": schedule_id, "definition_change": "saved search edited"},
        )
    return updated


@router.delete("/searches/{search_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_search(search_id: str, request: Request, user: CurrentUser) -> Response:
    removed = await run_in_threadpool(_store(request).delete, search_id, user)
    await run_in_threadpool(
        _audit,
        request,
        "search.delete",
        "success",
        user,
        {"search_id": search_id, "owner_id": removed.owner_id},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/searches/{search_id}/run")
async def run_search(
    search_id: str, body: RunRequest, request: Request, user: CurrentUser
) -> QueryResponse:
    search = await run_in_threadpool(_store(request).get, search_id, user)
    end = body.end or datetime.now(UTC)
    start = body.start or end - timedelta(hours=24)
    values = bind(search.params, body.params, start, end, search.sql)

    meta: MetaDB = request.app.state.meta
    allowed = await run_in_threadpool(permitted_sources, meta, user)
    requested = search.sources
    if body.sources is not None:
        requested = [s for s in (requested or body.sources) if s in set(body.sources)]
    sources = scope_sources(allowed, requested)  # the caller's grants, narrowed only

    engine: QueryEngine = request.app.state.engine
    detail: dict[str, Any] = {
        "search_id": search_id,
        "params": {k: v for k, v in values.items() if k not in ("start", "end")},
        "start": start.isoformat(),
        "end": end.isoformat(),
    }
    try:
        result = await run_in_threadpool(
            engine.run,
            compile_sql(search.sql),
            QueryScope(sources=sources, start=start, end=end),
            values,
        )
    except AppError as exc:
        detail |= {
            "error": type(exc).__name__,
            "sources_in_scope": "all" if sources is None else sources,
        }
        await run_in_threadpool(_audit, request, "search.run", "failure", user, detail)
        raise
    detail |= {"rows": len(result.rows), "sources_in_scope": result.sources}
    await run_in_threadpool(_audit, request, "search.run", "success", user, detail)
    return QueryResponse(
        columns=result.columns,
        rows=result.rows,
        row_count=len(result.rows),
        truncated=result.truncated,
        elapsed_ms=result.elapsed_ms,
        executed_sql=result.executed_sql,
        sources=result.sources,
    )


class VerifyRequest(BaseModel):
    verified: bool


@router.put("/searches/{search_id}/verified")
async def verify_search(
    search_id: str, body: VerifyRequest, request: Request, admin: AdminUser
) -> SavedSearch:
    """Admins mark shared searches as verified Ask examples. Edits clear the mark."""
    updated = await run_in_threadpool(_store(request).set_verified, search_id, body.verified, admin)
    await run_in_threadpool(
        _audit,
        request,
        "search.verify",
        "success",
        admin,
        {"search_id": search_id, "verified": body.verified},
    )
    return updated


def to_yaml(search: SavedSearch) -> str:
    doc = {"schema_version": 1, **search.model_dump(mode="json", exclude={"verified"})}
    # Parameters carry only what was set, matching the SPEC 5.4 format.
    doc["params"] = [p.model_dump(mode="json", exclude_defaults=True) for p in search.params]
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)


@router.get("/searches/{search_id}/export")
async def export_search(search_id: str, request: Request, user: CurrentUser) -> Response:
    search = await run_in_threadpool(_store(request).get, search_id, user)
    await run_in_threadpool(
        _audit, request, "search.export", "success", user, {"search_id": search_id}
    )
    return Response(
        to_yaml(search),
        media_type="application/yaml",
        headers={"Content-Disposition": f'attachment; filename="{search_id}.yaml"'},
    )


@router.post("/searches/import", status_code=status.HTTP_201_CREATED)
async def import_search(request: Request, user: AuthorUser) -> SavedSearch:
    raw = await request.body()
    if len(raw) > MAX_IMPORT_BYTES:
        raise PayloadTooLargeError(f"Imports are limited to {MAX_IMPORT_BYTES // 1024} KB")
    try:
        doc = safeyaml.load(raw.decode("utf-8"))  # no object tags, no aliases
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise SearchInvalidError("Not valid YAML") from exc
    if not isinstance(doc, dict):
        raise SearchInvalidError("Expected one saved search as a YAML mapping")
    if doc.get("schema_version", 1) != 1:
        raise SearchInvalidError("Unsupported schema_version")
    for key in SERVER_FIELDS:
        doc.pop(key, None)  # owner, timestamps, and verification are set here, not imported
    doc["visibility"] = "private"  # an import is private until its new owner shares it
    try:
        spec = SavedSearchIn.model_validate(doc)
    except ValidationError as exc:
        raise SearchInvalidError(
            f"Invalid saved search: {exc.errors()[0].get('msg', 'invalid')}"
        ) from exc
    created = await run_in_threadpool(_store(request).create, spec, user)
    await run_in_threadpool(
        _audit, request, "search.import", "success", user, {"search_id": spec.id}
    )
    return created
