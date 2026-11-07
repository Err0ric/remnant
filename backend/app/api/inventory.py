"""Proxmox inventory matches and empty-result explanations (ADR-0045 A5, Part B). Router
only: the logic is in app/search/inventory.py and app/search/coverage.py. Everything reads
the caller's own events view and source list, and is audited."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.access import CurrentUser, client_ip
from app.auth.service import AuthService
from app.engine.duckdb import QueryEngine, QueryScope
from app.engine.views import permitted_sources
from app.ingest.sources import SourceStore
from app.search.coverage import coverage
from app.search.inventory import Match, inventory_rows, match_rows
from app.templates.registry import TemplateRegistry

router = APIRouter(tags=["inventory"])
DEFAULT_RANGE = timedelta(hours=24)
MAX_VALUES = 50


class MatchOut(BaseModel):
    """ "Proxmox VM 104 build-runner on pve2", first and last seen holding the value."""

    source_id: str
    vmid: int
    type: str
    name: str
    node: str
    first_seen: str
    last_seen: str
    current: bool
    search_sql: str


class MatchesOut(BaseModel):
    matches: dict[str, list[MatchOut]]


class NoteOut(BaseModel):
    source_id: str
    state: str  # receiving | not_receiving | never | off
    since: str | None
    records_address: bool


class CategoryOut(BaseModel):
    category: str
    sources: list[NoteOut]


class CoverageOut(BaseModel):
    value: str
    start: str
    end: str
    events: int
    categories: list[CategoryOut]
    missing: list[str]
    inventory_source: bool
    inventory: list[MatchOut]
    restricted: bool
    can_add_source: bool


def _window(
    request: Request, start: datetime | None, end: datetime | None
) -> tuple[datetime, datetime]:
    now: datetime = request.app.state.auth.clock()
    stop = (end or now).astimezone(UTC)
    return (start or stop - DEFAULT_RANGE).astimezone(UTC), stop


def _out(m: Match) -> MatchOut:
    return MatchOut(**{f: getattr(m, f) for f in MatchOut.model_fields})


async def _audit(
    request: Request, user: CurrentUser, action: str, detail: dict[str, object]
) -> None:
    auth: AuthService = request.app.state.auth
    await run_in_threadpool(
        auth.audit.write, action, "success", user.user_id, client_ip(request), detail
    )


@router.get("/inventory/matches")
async def matches(
    request: Request,
    user: CurrentUser,
    value: Annotated[list[str], Query(min_length=1, max_length=MAX_VALUES)],
    start: datetime | None = None,
    end: datetime | None = None,
) -> MatchesOut:
    """The Proxmox guests that held each IP, MAC, or host name (exact matches only)."""
    first, last = _window(request, start, end)
    allowed = await run_in_threadpool(permitted_sources, request.app.state.meta, user)
    engine: QueryEngine = request.app.state.engine
    rows = await run_in_threadpool(inventory_rows, engine, QueryScope(allowed, first, last))
    values = [v[:256] for v in dict.fromkeys(value)]
    found = {v: [_out(m) for m in match_rows(rows, v, first)] for v in values}
    await _audit(
        request,
        user,
        "inventory.match",
        {"values": len(values), "sources_in_scope": allowed},
    )
    return MatchesOut(matches=found)


@router.get("/inventory/coverage")
async def address_coverage(
    request: Request,
    user: CurrentUser,
    value: str = Query(min_length=1, max_length=256),
    start: datetime | None = None,
    end: datetime | None = None,
) -> CoverageOut:
    """For an address with no events: per category of the caller's sources, what was
    searched and whether each source could have recorded it (ADR-0045 B2 to B4)."""
    first, last = _window(request, start, end)
    allowed = await run_in_threadpool(permitted_sources, request.app.state.meta, user)
    store: SourceStore = request.app.state.sources
    every = await run_in_threadpool(store.list)
    mine = every if allowed is None else [s for s in every if s.source_id in set(allowed)]
    engine: QueryEngine = request.app.state.engine
    templates: TemplateRegistry = request.app.state.templates
    scope = QueryScope(allowed, first, last)
    result = await run_in_threadpool(
        coverage,
        engine,
        scope,
        value,
        mine,
        templates.get,
        request.app.state.ingest.status(),
        request.app.state.auth.clock(),
        allowed is not None,
    )
    rows = await run_in_threadpool(inventory_rows, engine, scope)
    await _audit(
        request,
        user,
        "address.coverage",
        {"value": value[:256], "events": result.events, "sources_in_scope": result.read},
    )
    return CoverageOut(
        value=result.value,
        start=first.isoformat(),
        end=last.isoformat(),
        events=result.events,
        categories=[
            CategoryOut(
                category=c.category,
                sources=[
                    NoteOut(
                        source_id=n.source_id,
                        state=n.state,
                        since=n.since,
                        records_address=n.records_address,
                    )
                    for n in c.sources
                ],
            )
            for c in result.categories
        ],
        missing=result.missing,
        inventory_source=result.inventory_source,
        inventory=[_out(m) for m in match_rows(rows, value, first)],
        restricted=result.restricted,
        can_add_source=allowed is None,
    )
