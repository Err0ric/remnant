"""Query library (ADR-0033). Router only.

The library is SQL text for the editor and saved searches: nothing here runs a library
query. Offering reads which templates the viewer's own sources produced (row 3)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.access import CurrentUser, client_ip, require_role
from app.auth.service import AuthService
from app.auth.users import User
from app.core.errors import NotFoundError
from app.engine.views import permitted_sources
from app.search.library import Library, LibraryQuery, Pack, copies, copy, editor_sql
from app.search.saved import SavedSearch, SavedSearchStore
from app.search.schedules import ScheduleService

router = APIRouter(tags=["search"])
Author = Annotated[User, Depends(require_role("admin", "analyst"))]


class CopyOut(BaseModel):
    search_id: str
    version: str  # the pack version the copy was made from
    updated: bool  # the pack's SQL changed since (row 7)
    sql: str  # the copy's SQL now, for the difference


class QueryOut(BaseModel):
    id: str
    name: str
    group: str
    description: str
    why: str
    normal: str
    tags: list[str]
    requires: list[str]
    sql: str  # for the editor: start and end placeholders kept, other defaults written in
    pack_sql: str  # as shipped, for the difference with a copy
    suggested_schedule: str | None
    flag: str | None
    my_copy: CopyOut | None


class PackOut(BaseModel):
    id: str
    name: str
    version: str
    description: str
    queries: list[QueryOut]


class LibraryOut(BaseModel):
    packs: list[PackOut]
    hidden: int  # queries whose sources the viewer has no events from


def _lib(request: Request) -> Library:
    lib: Library = request.app.state.library
    return lib


def _audit(request: Request, action: str, user: User, detail: dict[str, Any]) -> None:
    auth: AuthService = request.app.state.auth
    auth.audit.write(action, "success", user.user_id, client_ip(request), detail)


def _query_out(pack: Pack, q: LibraryQuery, mine: dict[str, SavedSearch]) -> QueryOut:
    c = mine.get(f"{pack.id}/{q.id}")
    cp = None
    if c is not None:
        made = (c.origin or {}).get("library", "").rpartition("@")[2]
        cp = CopyOut(
            search_id=c.id, version=made, sql=c.sql,
            updated=made != pack.version and c.sql.strip() != q.sql.strip(),
        )  # fmt: skip
    return QueryOut(
        id=q.id, name=q.name, group=q.group, description=q.description, why=q.why,
        normal=q.normal, tags=q.tags, requires=q.requires, sql=editor_sql(q), pack_sql=q.sql,
        suggested_schedule=q.suggested_schedule, flag=q.flag, my_copy=cp,
    )  # fmt: skip


@router.get("/library")
async def library(request: Request, user: CurrentUser) -> LibraryOut:
    """The packs, with only the queries whose templates the viewer's sources produced in
    the last 30 days, and the viewer's own copies."""
    lib = _lib(request)
    allowed = await run_in_threadpool(permitted_sources, request.app.state.meta, user)
    seen = await run_in_threadpool(lib.templates_seen, request.app.state.engine, allowed)
    store: SavedSearchStore = request.app.state.searches
    mine = copies(await run_in_threadpool(store.visible, user), user)
    packs, hidden = [], 0
    for p in lib.packs:
        offered = [q for q in p.queries if lib.offered(q, seen)]
        hidden += len(p.queries) - len(offered)
        if offered:
            packs.append(
                PackOut(
                    id=p.id,
                    name=p.name,
                    version=p.version,
                    description=p.description,
                    queries=[_query_out(p, q, mine) for q in offered],
                )
            )
    return LibraryOut(packs=packs, hidden=hidden)


def _find(request: Request, pack_id: str, query_id: str) -> tuple[Pack, LibraryQuery]:
    found = _lib(request).find(pack_id, query_id)
    if found is None:
        raise NotFoundError("No such library query")
    return found


@router.post("/library/{pack_id}/{query_id}/copy", status_code=status.HTTP_201_CREATED)
async def save_as_mine(pack_id: str, query_id: str, request: Request, user: Author) -> SavedSearch:
    """Save as my own (row 4): a private saved search the user owns. Audited
    search.create with the library entry."""
    pack, q = _find(request, pack_id, query_id)
    store: SavedSearchStore = request.app.state.searches
    created = await run_in_threadpool(copy, store, pack, q, user)
    await run_in_threadpool(
        _audit, request, "search.create", user,
        {"search_id": created.id, "library": pack.origin(q)},
    )  # fmt: skip
    return created


@router.post("/library/{pack_id}/{query_id}/replace")
async def replace_mine(pack_id: str, query_id: str, request: Request, user: Author) -> SavedSearch:
    """Replace my copy (row 7): the user's copy takes the pack's current SQL and version.
    Audited search.update; the user's schedules of it take the change as an edit does."""
    pack, q = _find(request, pack_id, query_id)
    store: SavedSearchStore = request.app.state.searches
    mine = copies(await run_in_threadpool(store.visible, user), user).get(f"{pack.id}/{q.id}")
    if mine is None:
        raise NotFoundError("You have no copy of this library query")
    spec = q.spec(pack.origin(q)).model_copy(
        update={"id": mine.id, "name": mine.name, "tags": mine.tags,
                "visibility": mine.visibility, "sources": mine.sources}
    )  # fmt: skip
    updated = await run_in_threadpool(store.update, mine.id, spec, user)
    await run_in_threadpool(
        _audit, request, "search.update", user,
        {"search_id": mine.id, "library": pack.origin(q), "replaced": True},
    )  # fmt: skip
    schedules: ScheduleService = request.app.state.schedules
    for sid in await run_in_threadpool(schedules.accept_search_change, mine.id, user):
        await run_in_threadpool(
            _audit, request, "schedule.update", user,
            {"schedule_id": sid, "definition_change": "library copy replaced"},
        )  # fmt: skip
    return updated
