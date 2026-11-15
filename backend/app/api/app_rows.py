"""Rows the app's own pages show, with SQL the server builds and runs (owner, 2026-11-08,
option A for #451): the person page's sign-ins, the Microsoft 365 tab lists, and the
Sources page counts no longer send app-built SQL to /api/query. Each endpoint runs fixed
or server-built SQL on the caller's per-session `events` view and scope, through the
guard, audited `query.view` with the view's name. They are display, like the dashboards,
so a setting that keeps SQL from Auditors does not apply to them. Router only."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request
from starlette.concurrency import run_in_threadpool

from app.api.access import CurrentUser
from app.api.query import QueryRequest, QueryResponse, _geo, _intel, _run_audited
from app.core import clock
from app.core.errors import ParamInvalidError
from app.core.ids import AUTO_PARSER
from app.enrich import networks
from app.search import m365
from app.search.person_record import m365_sql
from app.search.timeline import signins_sql, window

router = APIRouter(tags=["search"])

COUNTS_SQL = (
    "SELECT source_id, count(*) AS events, max(coalesce(time, time_observed)) AS last_event"
    " FROM events GROUP BY source_id"
)
# Which template read each line, for Automatic sources (ADR-0012).
MIX_SQL = "SELECT source_id, template_id, count(*) FROM events GROUP BY 1, 2"


async def _rows(
    request: Request,
    user: CurrentUser,
    sql: str,
    view: str,
    start: datetime | None = None,
    end: datetime | None = None,
    sources: list[str] | None = None,
    params: dict[str, object] | None = None,
) -> QueryResponse:
    """Runs the server's SQL as /api/query runs a person's: the caller's scope (a source
    list only narrows it), the guard, enrichment, and an audit row."""
    body = QueryRequest.model_construct(
        sql=sql, start=start, end=end, sources=sources, params=params or {}
    )
    result = await _run_audited(body, request, user, "query.view", {"view": view})
    return QueryResponse(
        columns=result.columns,
        rows=result.rows,
        row_count=len(result.rows),
        truncated=result.truncated,
        elapsed_ms=result.elapsed_ms,
        executed_sql=result.executed_sql,
        sources=result.sources,
        geo=await run_in_threadpool(_geo, request, result.rows),
        intel=await run_in_threadpool(_intel, request, result.rows),
    )


def _fill(template: str, start: datetime, end: datetime) -> str:
    """A Search query template's `{from}` and `{to}`: server datetimes, never client text."""
    return template.replace("{from}", start.isoformat()).replace("{to}", end.isoformat())


@router.get("/people/{person}/signins")
async def person_signins(
    person: str,
    request: Request,
    user: CurrentUser,
    days: Annotated[int, Query(ge=1, le=30)] = 7,
) -> QueryResponse:
    """The person page's Microsoft 365 sign-ins (ADR-0038 row 27)."""
    ident = await run_in_threadpool(request.app.state.identities.load)
    start, end = window(days, clock.now())
    sql = _fill(signins_sql(ident, person[:256]), start, end)
    return await _rows(request, user, sql, "person.signins", start, end)


@router.get("/people/{person}/m365")
async def person_m365(
    person: str,
    request: Request,
    user: CurrentUser,
    name: Annotated[str, Query(max_length=32)],
    days: Annotated[int, Query(ge=1, le=30)] = 7,
) -> QueryResponse:
    """The person page's Microsoft 365 section (ADR-0052): `name` is `sign_ins`, `mail`
    (mailbox rule changes), or `admin` (directory changes the person made)."""
    ident = await run_in_threadpool(request.app.state.identities.load)
    start, end = window(days, clock.now())
    sql = _fill(m365_sql(ident, person[:256], name), start, end)
    return await _rows(request, user, sql, f"person.m365_{name}", start, end)


M365_LISTS = ("sign_ins", "mail", "dlp", "consents", "registrations", "admin")


@router.get("/m365/list")
async def m365_list(
    request: Request,
    user: CurrentUser,
    name: Annotated[str, Query(max_length=32)],
    start: datetime,
    end: datetime,
    cls: Annotated[str | None, Query(max_length=32)] = None,
    mode: Annotated[str | None, Query(max_length=32)] = None,
) -> QueryResponse:
    """One Microsoft 365 tab's list over the page window (ADR-0038 section 5): `name` is a
    list, and for sign-ins `cls` and `mode` pick the filtered one."""
    if name not in M365_LISTS:
        raise ParamInvalidError(f"Unknown list {name[:32]!r}")
    if name == "sign_ins" and (cls or mode):
        template = m365.sign_in_lists().get(cls or "all", {}).get(mode or "all")
        if template is None:
            raise ParamInvalidError("Unknown sign-in filter")
    else:
        places = await run_in_threadpool(networks.load, request.app.state.meta)
        approved = tuple(sorted(c.upper() for c in places.approved_countries))
        template = m365.lists(approved)[name]
    return await _rows(request, user, _fill(template, start, end), f"m365.{name}", start, end)


@router.get("/sources/event-counts")
async def source_event_counts(request: Request, user: CurrentUser) -> QueryResponse:
    """Events and the newest event per source, for the Sources page."""
    return await _rows(request, user, COUNTS_SQL, "sources.counts")


@router.get("/sources/parser-mix")
async def source_parser_mix(request: Request, user: CurrentUser) -> QueryResponse:
    """Lines per template for each Automatic source (ADR-0012)."""
    auto = [s.source_id for s in request.app.state.sources.list() if s.template_id == AUTO_PARSER]
    if not auto:
        return QueryResponse(
            columns=["source_id", "template_id", "count"], rows=[], row_count=0,
            truncated=False, elapsed_ms=0, executed_sql="", sources=[],
        )  # fmt: skip
    return await _rows(request, user, MIX_SQL, "sources.mix", sources=auto)
