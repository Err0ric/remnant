"""/api/ask: Ask mode (SPEC 5.3). Router only.

Returns the SQL with an `ask_id`; `POST /api/ask/{ask_id}/run` runs exactly that SQL for
the person who asked, through the guard on their own view, audited like any query with
purpose `ask` (ADR-0042 slice 1a). With `ask.auto_run` on, the panel calls it at once.
Scope comes from the caller's grants exactly as in /api/query. Auditors have no Ask
unless an admin has turned on the setting that grants Auditors SQL (D220).

`POST /api/ask/jobs` and `POST /api/ask/{ask_id}/jobs` do the same steps as a background
job (D269): they answer at once with a job id, and `GET /api/ask/jobs/{job_id}` returns
what is done so far, so no request waits on the model. The steps are the same code, with
the same guard, view, and audit rows, as the three calls above.
"""

import asyncio
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta
from time import monotonic
from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field, StringConstraints, model_validator
from starlette.concurrency import run_in_threadpool

from app.api.access import SqlUser, client_ip
from app.api.addresses import readable
from app.api.cancel import watch_disconnect
from app.api.query import MAX_TYPED_SQL, HeldQuery, QueryResponse, _geo, _intel, _run_audited
from app.auth.service import AuthService
from app.auth.users import User
from app.core import clock
from app.core.config import AppConfig
from app.core.errors import (
    AppError,
    ModelTimeoutError,
    NotFoundError,
    ParamInvalidError,
    ProviderConfigError,
    RateLimitedError,
)
from app.core.times import UtcDateTime
from app.engine.duckdb import QueryScope
from app.engine.views import permitted_sources, scope_sources
from app.llm import gate
from app.llm.agent import AskAgent, AskExample, AskTurn
from app.llm.ask_summary import summarize
from app.llm.provider import Locality
from app.llm.queue import QUEUES
from app.llm.registry import ProviderRecord, ProviderStore
from app.meta.db import MetaDB
from app.search import ask_direct
from app.search.ask_drill import DrillError, drill_sql
from app.search.ask_flow import Routed, route_question
from app.search.ask_jobs import AskJob, AskJobs
from app.search.ask_route import Plan, rank
from app.search.ask_runs import AskRuns, Drill, Ran
from app.search.ask_summary import (
    check_claims,
    counted_line,
    headline,
    removed_note,
    sample,
    window_words,
)
from app.search.library import Library, LibraryQuery, editor_sql
from app.search.saved import SavedSearchStore

router = APIRouter(tags=["ask"])
log = structlog.get_logger(__name__)

AskUser = SqlUser
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)]


class Turn(BaseModel):
    question: Text
    # The earlier answer by its id: the server reads its SQL from what it holds, so SQL it
    # built (a library answer longer than typed SQL may be) is never posted back. `sql`
    # is the client's copy, used when the answer has expired or had no id.
    ask_id: str | None = Field(default=None, max_length=64)
    sql: str | None = Field(default=None, min_length=1, max_length=MAX_TYPED_SQL)

    @model_validator(mode="after")
    def _one(self) -> "Turn":
        if self.ask_id is None and self.sql is None:
            raise ValueError("a turn needs its ask_id or its sql")
        return self


def _history_sql(t: Turn, runs: AskRuns, user_id: str, now: datetime) -> str:
    """An earlier turn's SQL for the follow-up: the held answer's own SQL, the client's
    copy when it has expired, or one line in its place when the SQL is a server-built
    library answer too long for the model's turn or expired with no copy (the
    model-facing limit stays as it is)."""
    run = None
    if t.ask_id is not None:
        try:
            run = runs.get(t.ask_id, user_id, now)
        except NotFoundError:
            run = None
    if run is None:
        # Expired, and its SQL too long to have been sent back: the follow-up still runs,
        # with one line saying so, never blocked by an earlier turn (second review of 636).
        if t.sql is None:
            return (
                "-- An earlier answer built by the server; it has expired, so its SQL is not shown."
            )
        return t.sql
    if len(run.sql) <= MAX_TYPED_SQL:
        return run.sql
    return f"-- The library query {run.origin}; its SQL was built by the server and is not shown."


class AskRequest(BaseModel):
    question: Text
    provider_id: str | None = Field(default=None, max_length=64)
    start: UtcDateTime | None = None
    end: UtcDateTime | None = None
    # A filter only: intersected with the sources the caller may read, never a grant.
    sources: list[str] | None = Field(default=None, max_length=200)
    history: list[Turn] = Field(default_factory=list, max_length=3)
    # The asker's time zone, for "today" and "yesterday" (IANA name; UTC when unknown).
    tz: str | None = Field(default=None, max_length=64)
    # "data": the asker chose "Check your data instead" after a general-guidance route.
    route: Literal["auto", "data"] = "auto"


class LibraryRef(BaseModel):
    ref: str  # "<pack>/<query>"
    name: str
    version: str


class RouteOut(BaseModel):
    """How the question was routed (ADR-0042 condition 3), for the turn and How I got this."""

    kind: Literal["data", "knowhow"]
    # library: matched in code to a library query, with no model call (owner, 2026-11-08).
    # direct: only an address; its page, with no model call (D276).
    by: Literal["model", "forced", "follow_up", "library", "direct"]
    library: LibraryRef | None = None
    filters: list[str] = Field(default_factory=list)  # "user = dana@example.com"
    params: dict[str, str | int | float | bool] = Field(default_factory=dict)
    time: str | None = None  # the time phrase as understood ("today")
    reason: str | None = None  # why the library was not used


class AskProvider(BaseModel):
    provider_id: str
    name: str
    model: str
    locality: Locality


class DirectSectionOut(BaseModel):
    section: str
    title: str
    state: Literal["ok", "no_source", "failed"]
    count_words: str  # "14 names"; empty unless ok
    read: list[str]


class DirectOut(BaseModel):
    """A direct lookup (D276): the address the question is, to open its page, and the
    page's sections in brief, read as the page reads them."""

    kind: Literal["ip"]
    value: str
    window: str  # "the last 7 days": the page's own default, which the sections read
    range: str  # the same window as the page's time choice ("7d"), for the link
    sections: list[DirectSectionOut] = Field(default_factory=list)


class AskResponse(BaseModel):
    # None for a general-guidance route: nothing to run (answers arrive in slice 2).
    ask_id: str | None
    # Run without a click: the install allows it and the SQL passed the self-check.
    auto_run: bool
    sql: str
    explanation: str
    assumptions: list[str]
    # library: a shipped query, tested on the template fixtures; not previewed again.
    check: Literal["ok", "empty", "failed", "library", "none"]
    check_detail: str | None
    attempts: int
    provider: AskProvider
    call_ids: list[str]
    route: RouteOut | None = None
    # The time range the query reads, when the question named one.
    start: UtcDateTime | None = None
    end: UtcDateTime | None = None
    # A direct lookup (route.by "direct"): no query, the entity's page instead.
    lookup: list[DirectOut] = Field(default_factory=list)


_running: set[str] = set()
_running_lock = threading.Lock()


def _claim(user_id: str) -> None:
    """One Ask per user at a time: each can run several model calls and previews."""
    with _running_lock:
        if user_id in _running:
            raise RateLimitedError("Your previous question is still running", retry_after_s=5)
        _running.add(user_id)


def _release(user_id: str) -> None:
    with _running_lock:
        _running.discard(user_id)


@contextmanager
def _one_at_a_time(user_id: str) -> Iterator[None]:
    _claim(user_id)
    try:
        yield
    finally:
        _release(user_id)


@asynccontextmanager
async def _held(request: Request, user_id: str, live: bool) -> AsyncIterator[None]:
    """A request's model calls: cancelled if the browser leaves, one per user at a time.
    A job (`live` False) holds the user's turn itself for all its steps, and has no
    browser to watch."""
    if not live:
        yield
        return
    async with watch_disconnect(request):
        with _one_at_a_time(user_id):
            yield


def _enabled(request: Request) -> list[AskProvider]:
    store: ProviderStore = request.app.state.providers
    config: AppConfig = request.app.state.config
    trusted = config.llm.trusted_local_hosts
    out = [_public(r, gate.locality_of(r, trusted)) for r in store.all() if r.enabled]
    return sorted(out, key=lambda p: (p.locality != "local", p.name.lower()))


def _public(r: ProviderRecord, locality: Locality) -> AskProvider:
    return AskProvider(provider_id=r.provider_id, name=r.name, model=r.model, locality=locality)


@router.get("/ask/providers")
async def ask_providers(request: Request, _: AskUser) -> list[AskProvider]:
    """Enabled providers an analyst can choose, local first. No URLs or key state."""
    return await run_in_threadpool(_enabled, request)


class QueueOut(BaseModel):
    """How busy a provider is right now (ADR-0028 row 10). Counts only, no content."""

    slots: int | None  # None: no queue
    running: int
    waiting: int


@router.get("/ask/providers/{provider_id}/queue")
async def provider_queue(provider_id: str, request: Request, _: AskUser) -> QueueOut:
    choices = await run_in_threadpool(_enabled, request)
    if provider_id not in {p.provider_id for p in choices}:
        raise ProviderConfigError("That AI provider is not available")
    st = QUEUES.status(provider_id)
    return QueueOut(slots=st.limit, running=st.running, waiting=st.waiting)


async def _chosen(request: Request, provider_id: str | None) -> AskProvider:
    choices = await run_in_threadpool(_enabled, request)
    if provider_id is None:
        if not choices:
            raise ProviderConfigError("No AI provider is enabled. An admin can add one.")
        return choices[0]
    match = [p for p in choices if p.provider_id == provider_id]
    if not match:
        raise ProviderConfigError("That AI provider is not available")
    return match[0]


SQL_TIMED_OUT = "The model took too long to write a query."
SUMMARY_TIMED_OUT = "The model took too long to summarize. Results are above."


@router.post("/ask")
async def ask(body: AskRequest, request: Request, user: AskUser) -> AskResponse:
    return await _ask(body, request, user, live=True)


async def _ask(body: AskRequest, request: Request, user: User, live: bool) -> AskResponse:
    meta: MetaDB = request.app.state.meta
    auth: AuthService = request.app.state.auth
    agent: AskAgent = request.app.state.ask
    chosen = await _chosen(request, body.provider_id)

    allowed = await run_in_threadpool(permitted_sources, meta, user)
    scope = QueryScope(sources=scope_sources(allowed, body.sources), start=body.start, end=body.end)
    runs: AskRuns = request.app.state.ask_runs
    asked_at = clock.now()
    history = [
        AskTurn(t.question, _history_sql(t, runs, user.user_id, asked_at)) for t in body.history
    ]
    searches: SavedSearchStore = request.app.state.searches
    found = await run_in_threadpool(searches.examples, user, body.question)
    examples = [AskExample(s.name, s.sql) for s in found]
    detail: dict[str, object] = {
        "question": body.question,
        "provider_id": chosen.provider_id,
        "sources_requested": body.sources,
        "examples": [s.id for s in found],
    }
    now = clock.now()
    # A bare address is never a refinement: it opens its page on any turn (D276).
    began = monotonic()
    direct = await run_in_threadpool(_direct, request, body.question, allowed, now)
    if direct is not None:
        detail["route"] = {
            "kind": "data", "by": "direct", "via": "direct", "library": None,
            "candidates": [], "time": None, "entities": 1, "reason": None,
            "lookup": [direct.kind], "ms": round((monotonic() - began) * 1000),
            "sources_read": sorted({r for x in direct.sections for r in x.read}),
        }  # fmt: skip
        await run_in_threadpool(
            auth.audit.write, "ask.request", "success", user.user_id, client_ip(request), detail
        )
        return AskResponse(
            ask_id=None, auto_run=False, sql="", explanation="", assumptions=[], check="none",
            check_detail=None, attempts=0, provider=chosen, call_ids=[],
            route=RouteOut(kind="data", by="direct"),
            lookup=[DirectOut.model_validate(direct, from_attributes=True)],
        )  # fmt: skip
    routed: Routed | None = None
    try:
        async with _held(request, user.user_id, live):
            if not history:  # follow-ups refine the last SQL (slice 4 routes them)
                routed = await run_in_threadpool(
                    _route, request, user, chosen.provider_id, body, allowed, scope, now
                )
                detail["route"] = _route_detail(routed)
            if routed is not None and (routed.kind == "knowhow" or routed.plan):
                outcome = None
            else:
                if routed is not None and routed.span is not None:
                    scope = QueryScope(scope.sources, routed.span.start, routed.span.end)
                outcome = await run_in_threadpool(
                    agent.ask,
                    user.user_id,
                    chosen.provider_id,
                    scope,
                    body.question,
                    history,
                    examples,
                )
    except Exception as exc:  # every outcome is audited, including unexpected ones
        detail["error"] = type(exc).__name__
        await run_in_threadpool(
            auth.audit.write, "ask.request", "failure", user.user_id, client_ip(request), detail
        )
        if isinstance(exc, ModelTimeoutError):
            timed_out = ModelTimeoutError(SQL_TIMED_OUT)
            timed_out.call_id = getattr(exc, "call_id", None)  # type: ignore[attr-defined]  # as the gate sets it
            raise timed_out from exc
        raise
    config: AppConfig = request.app.state.config
    route_out = _route_out(routed, bool(history))
    start = routed.span.start if routed and routed.span else body.start
    end = routed.span.end if routed and routed.span else body.end
    call_ids = [routed.call_id] if routed and routed.call_id else []
    if routed is not None and routed.kind == "knowhow":
        detail |= {"call_ids": call_ids}
        await run_in_threadpool(
            auth.audit.write, "ask.request", "success", user.user_id, client_ip(request), detail
        )
        return AskResponse(
            ask_id=None, auto_run=False, sql="", explanation="", assumptions=[], check="none",
            check_detail=None, attempts=0, provider=chosen, call_ids=call_ids, route=route_out,
            start=start, end=end,
        )  # fmt: skip
    if routed is not None and routed.plan is not None and routed.candidate is not None:
        c = routed.candidate
        kept = runs.keep(
            user.user_id, routed.plan.sql, start, end, body.sources, call_ids, now,
            body.question, origin=c.pack.origin(c.query), params=routed.plan.params,
            provider_id=chosen.provider_id, template=c.query.answer,
            drill=_drill(c.query, routed.plan), tz=body.tz,
            counted=(w.what, w.row, w.rows) if (w := c.query.counted) else None,
            window=routed.span.label if routed.span else None, empty=c.query.empty,
        )  # fmt: skip
        detail |= {"call_ids": call_ids, "ask_id": kept.ask_id}
        await run_in_threadpool(
            auth.audit.write, "ask.request", "success", user.user_id, client_ip(request), detail
        )
        return AskResponse(
            ask_id=kept.ask_id, auto_run=config.ask.auto_run, sql=routed.plan.sql,
            explanation="", assumptions=[], check="library", check_detail=None, attempts=0,
            provider=chosen, call_ids=call_ids, route=route_out, start=start, end=end,
        )  # fmt: skip
    assert outcome is not None  # the agent ran: neither know-how nor a library plan
    call_ids += outcome.call_ids
    kept = runs.keep(
        user.user_id, outcome.answer.sql, start, end, body.sources,
        call_ids, now, body.question, provider_id=chosen.provider_id, tz=body.tz,
        window=routed.span.label if routed and routed.span else None,
    )  # fmt: skip
    detail |= {"call_ids": call_ids, "check": outcome.check, "ask_id": kept.ask_id}
    await run_in_threadpool(
        auth.audit.write, "ask.request", "success", user.user_id, client_ip(request), detail
    )
    return AskResponse(
        ask_id=kept.ask_id,
        auto_run=config.ask.auto_run and outcome.check != "failed",
        sql=outcome.answer.sql,
        explanation=outcome.answer.explanation,
        assumptions=outcome.answer.assumptions,
        check=outcome.check,
        check_detail=outcome.check_detail,
        attempts=outcome.attempts,
        provider=chosen,
        call_ids=call_ids,
        route=route_out,
        start=start,
        end=end,
    )


# The address page's own default window: the brief reads what the page shows (D276).
DIRECT_DAYS = 7


def _direct(
    request: Request, question: str, allowed: list[str] | None, now: datetime
) -> ask_direct.Direct | None:
    """The direct lookup (D276) when the question is only an address, or None: then it goes
    on as before. The brief reads what the address page reads: the caller's full view (not
    the sources picked in Ask) over the page's default window, with the same function."""
    ip = ask_direct.address(question)
    if ip is None:
        return None
    state = request.app.state
    view = QueryScope(allowed, now - timedelta(days=DIRECT_DAYS), now)
    found = ask_direct.Direct("ip", ip, f"the last {DIRECT_DAYS} days", f"{DIRECT_DAYS}d")
    found.sections = ask_direct.brief(
        state.engine, state.library, ip, view, readable(request, allowed), now,
        state.ai_catalog.services(),
    )  # fmt: skip
    return found


def _route(
    request: Request,
    user: User,
    provider_id: str,
    body: AskRequest,
    allowed: list[str] | None,
    scope: QueryScope,
    now: datetime,
) -> Routed:
    state = request.app.state
    library: Library = state.library
    seen = library.templates_seen(state.engine, allowed)
    # Only the links the asker's scope shows reach the plan's filters (T70, D219).
    # Kept for a minute per asker and scope. Always computed, never only when the question
    # names someone the whole map knows: that would time whether a word is in the map.
    ident = state.identities.scoped(
        state.engine, scope, ["actor_user_name"], user.user_id, user.role
    )
    return route_question(
        state.gate, state.engine, library, seen, user.user_id, provider_id, body.question,
        now, body.tz, ident, scope, body.route,
    )  # fmt: skip


def _route_detail(r: Routed) -> dict[str, object]:
    return {
        "kind": r.kind,
        "by": r.by,
        "library": r.candidate.pack.origin(r.candidate.query) if r.candidate else None,
        "candidates": [c.ref for c in r.candidates],
        "time": r.span.label if r.span else None,
        "entities": len(r.entities),
        "reason": r.reason,
        # Which route answered and how long routing took, to compare the two later.
        "via": r.via,
        "ms": r.route_ms,
    }


def _route_out(r: Routed | None, follow_up: bool) -> RouteOut | None:
    if r is None:
        return RouteOut(kind="data", by="follow_up") if follow_up else None
    lib = None
    if r.candidate is not None and r.plan is not None:
        c = r.candidate
        lib = LibraryRef(ref=c.ref, name=c.query.name, version=c.pack.version)
    return RouteOut(
        kind=r.kind,
        by=r.by,
        library=lib,
        filters=r.plan.filters if r.plan else [],
        params={
            k: v for k, v in (r.plan.params if r.plan else {}).items() if not k.startswith("ask_")
        },
        time=r.span.label if r.span else None,
        reason=r.reason,
    )


class Suggestion(BaseModel):
    ref: str
    name: str
    why: str
    sql: str  # for the Search editor, defaults written in; it runs there like any query


@router.get("/ask/suggest")
async def suggest(
    request: Request,
    user: AskUser,
    q: Annotated[str, Query(min_length=1, max_length=2_000)],
) -> list[Suggestion]:
    """Library queries that match the question's words, best first, at most 3, with no
    model at all (ADR-0042 C4): what Ask offers when no AI provider is set up. Reads only
    which templates the caller's sources have used."""
    meta: MetaDB = request.app.state.meta
    library: Library = request.app.state.library
    allowed = await run_in_threadpool(permitted_sources, meta, user)
    seen = await run_in_threadpool(library.templates_seen, request.app.state.engine, allowed)
    return [
        Suggestion(ref=c.ref, name=c.query.name, why=c.query.why, sql=editor_sql(c.query))
        for c in rank(q, library, seen, top=3)
    ]


# Ask's own caps on a run (ADR-0042 row 1, C2): rows shown and the longest time range.
ASK_ROWS = 1000
ASK_MAX_DAYS = 90


class AskRunResponse(QueryResponse):
    # Written by code from the rows (ADR-0042 row 8), never model text.
    headline: str
    # Call POST /api/ask/{ask_id}/answer next: summaries are on and the rows carry event
    # ids a statement can cite.
    summarize: bool
    # Why there is no summary, when there is none and the reason is not "turned off".
    summary_note: str | None = None
    # Group keys (D173): each row can open its events with POST /api/ask/{id}/drill.
    drill_keys: list[str] = Field(default_factory=list)
    # What was counted, when the rows have no event ids to cite (item 21): one sentence
    # written by code from the run (sources read, window, rows) and the library entry.
    counted: str | None = None
    # A library query's words for no rows (D274), for the results' empty line.
    empty: str | None = None


@router.post("/ask/{ask_id}/run")
async def run_answer(ask_id: str, request: Request, user: AskUser) -> AskRunResponse:
    """Run the SQL an answer produced, as the person who asked, on their current view.
    Audited as query.run with purpose `ask`, the answer's id, its model call ids, and its
    origin (`generated`, or the library query `<pack>/<id>@<version>`). Returns a headline
    written by code from the rows."""
    return await _run(ask_id, request, user)


async def _run(ask_id: str, request: Request, user: User) -> AskRunResponse:
    runs: AskRuns = request.app.state.ask_runs
    config: AppConfig = request.app.state.config
    run = runs.get(ask_id, user.user_id, clock.now())
    end = run.end or clock.now()
    start = run.start
    if start is None or end - start > timedelta(days=ASK_MAX_DAYS):
        start = end - timedelta(days=ASK_MAX_DAYS)
    body = HeldQuery(
        sql=run.sql,
        start=start,
        end=end,
        sources=run.sources,
        params={k: v for k, v in run.params.items()},
    )
    extra: dict[str, object] = {
        "purpose": "ask",
        "origin": run.origin,
        "ask_id": run.ask_id,
        "ask_call_ids": run.call_ids,
    }
    result = await _run_audited(body, request, user, "query.run", extra, max_rows=ASK_ROWS)
    head = headline(result.columns, result.rows, result.truncated, run.template, run.tz, run.empty)
    rows = sample(result.columns, result.rows, result.truncated)
    runs.ran(run.ask_id, Ran(rows, list(result.sources), head, start, end))
    # Words for the window the run read: the question's own words only when the run read
    # exactly that window (a cut to the 90-day cap reads less than "the last 120 days").
    label = run.window if run.start is not None and start == run.start else None
    window = window_words(start, end, run.end is None, label, run.tz)
    counted = counted_line(
        result.columns, len(result.rows), len(result.sources), window, run.counted, run.empty,
    )  # fmt: skip
    note = None
    if config.ask.summarize and result.rows and rows is None and counted is None:
        note = "No summary: these rows have no event ids to cite."
    return AskRunResponse(
        columns=result.columns,
        rows=result.rows,
        row_count=len(result.rows),
        truncated=result.truncated,
        elapsed_ms=result.elapsed_ms,
        executed_sql=result.executed_sql,
        sources=result.sources,
        geo=await run_in_threadpool(_geo, request, result.rows),
        intel=await run_in_threadpool(_intel, request, result.rows),
        headline=head,
        summarize=config.ask.summarize and rows is not None and bool(run.provider_id),
        summary_note=note,
        drill_keys=run.drill.keys if run.drill and result.columns else [],
        counted=counted,
        empty=run.empty,
    )


class ClaimOut(BaseModel):
    text: str
    event_ids: list[str]


class AnswerOut(BaseModel):
    headline: str
    # Only statements that cite rows that were sent (C1); empty when none could.
    claims: list[ClaimOut]
    removed: int  # statements dropped for citing no sent row
    note: str | None  # why statements were removed, or why there is no summary
    call_id: str | None
    timed_out: bool = False  # the model ran past `ask.model_timeout_s` (D270)


@router.post("/ask/{ask_id}/answer")
async def answer(ask_id: str, request: Request, user: AskUser) -> AnswerOut:
    """The answer step (ADR-0042 row 8, slice 1c): statements about the rows the run kept,
    each citing their event ids; never rows from the client. Statements that cite no sent
    row are removed and counted. Any failure of the model leaves the rows and the headline
    without a summary. Audited as ask.answer."""
    return await _answer(ask_id, request, user, live=True)


async def _answer(ask_id: str, request: Request, user: User, live: bool) -> AnswerOut:
    runs: AskRuns = request.app.state.ask_runs
    config: AppConfig = request.app.state.config
    auth: AuthService = request.app.state.auth
    run, ran = runs.result(ask_id, user.user_id, clock.now())
    if not config.ask.summarize:
        raise ProviderConfigError("Summaries are turned off on this server (ask.summarize)")
    if ran.sample is None or not run.provider_id:
        return AnswerOut(
            headline=ran.headline, claims=[], removed=0, call_id=None,
            note="No summary: these rows have no event ids to cite.",
        )  # fmt: skip
    detail: dict[str, object] = {"ask_id": run.ask_id, "provider_id": run.provider_id}
    try:
        async with _held(request, user.user_id, live):
            got = await run_in_threadpool(
                summarize,
                request.app.state.gate,
                user.user_id,
                run.provider_id,
                run.question,
                ran.sample,
                ran.sources,
            )
    except AppError as exc:
        # Accuracy over speed (owner, 2026-11-02): no summary rather than a doubtful one.
        detail["error"] = type(exc).__name__
        await run_in_threadpool(
            auth.audit.write, "ask.answer", "failure", user.user_id, client_ip(request), detail
        )
        late = isinstance(exc, ModelTimeoutError)
        return AnswerOut(
            headline=ran.headline, claims=[], removed=0, call_id=None,
            note=SUMMARY_TIMED_OUT if late else f"No summary: {exc}", timed_out=late,
        )  # fmt: skip
    checked = check_claims(got.claims, ran.sample.event_ids)
    detail |= {
        "call_id": got.call_id,
        "kept": len(checked.claims),
        "removed": checked.removed,
        "citation_check": got.citation_check,
    }
    await run_in_threadpool(
        auth.audit.write, "ask.answer", "success", user.user_id, client_ip(request), detail
    )
    return AnswerOut(
        headline=ran.headline,
        claims=[ClaimOut(text=t, event_ids=ids) for t, ids in checked.claims],
        removed=checked.removed,
        note=removed_note(checked.removed, len(checked.claims)),
        call_id=got.call_id,
    )


def _drill(q: LibraryQuery, plan: Plan) -> Drill | None:
    """What Show events needs, or None when the rows cannot open their events exactly:
    the query has no keys, or a filter Ask added sits on a column that is an aggregate
    (it describes the group, so no events match it one by one)."""
    if not q.keys:
        return None
    values = {p.name: plan.params.get(p.name, p.default) for p in q.params}
    params = {**plan.params, **{k: v for k, v in values.items() if v is not None}}
    drill = Drill(q.sql, list(q.keys), params, list(plan.conds))
    try:  # built once here with stand-in values, so a row never offers a broken link
        drill_sql(drill.sql, drill.keys, dict.fromkeys(drill.keys, "x"), params, drill.filters)
    except DrillError:
        return None
    return drill


Value = str | int | float | bool | None


class DrillRequest(BaseModel):
    # The row's value for each group key, as the run returned it.
    values: dict[Annotated[str, StringConstraints(max_length=64)], Value] = Field(max_length=8)


class DrillOut(BaseModel):
    sql: str  # for the Search editor; {{start}} and {{end}} come from the window
    start: datetime | None
    end: datetime | None
    sources: list[str] | None


@router.post("/ask/{ask_id}/drill")
async def drill(ask_id: str, body: DrillRequest, request: Request, user: AskUser) -> DrillOut:
    """ "Show events" for one row of an aggregate library answer (D173): the library
    query's own WHERE and parameters plus each group key equal to the row's value, built
    by code, never by a model. Nothing runs here: Search runs it through the guard on the
    caller's view and audits it like any query."""
    runs: AskRuns = request.app.state.ask_runs
    run, ran = runs.result(ask_id, user.user_id, clock.now())
    if run.drill is None:
        raise ParamInvalidError("This answer's rows have no events to show")
    for v in body.values.values():
        if isinstance(v, str) and len(v) > 2_000:
            raise ParamInvalidError("A value is too long")
    try:
        sql = drill_sql(
            run.drill.sql, run.drill.keys, body.values, run.drill.params, run.drill.filters
        )
    except DrillError as exc:
        raise ParamInvalidError(f"Cannot show events for this row: {exc}") from exc
    return DrillOut(sql=sql, start=ran.start, end=ran.end, sources=run.sources)


# --- Ask as a background job (D269) ----------------------------------------------------


class StepError(BaseModel):
    code: str  # as the synchronous call's HTTP error says it ("model_timeout", ...)
    message: str


class AskJobStep(BaseModel):
    name: Literal["sql", "run", "summary"]
    state: Literal["running", "done", "failed", "timed_out"]
    ms: int | None  # None while running
    error: StepError | None = None


class AskJobOut(BaseModel):
    """What a job has so far. `ask` is the SQL step's answer (the SQL, the self-check
    verdict in `check`, the route); `result` the rows, as POST /ask/{id}/run returns them,
    there as soon as the query ran; `summary` once written. A failed job is still a 200:
    its `error` and the failed step say why."""

    job_id: str
    state: Literal["running", "done", "failed"]
    steps: list[AskJobStep]
    ask: AskResponse | None = None
    result: AskRunResponse | None = None
    summary: AnswerOut | None = None
    error: StepError | None = None


def _job_out(jobs: AskJobs, job: AskJob) -> AskJobOut:
    def err(e: tuple[str, str] | None) -> StepError | None:
        return StepError(code=e[0], message=e[1]) if e else None

    with jobs.lock:  # one consistent picture while the job moves on
        return AskJobOut(
            job_id=job.job_id,
            state=job.state,
            steps=[
                AskJobStep(name=s.name, state=s.state, ms=s.ms, error=err(s.error))
                for s in job.steps
            ],
            ask=job.ask if isinstance(job.ask, AskResponse) else None,
            result=job.result if isinstance(job.result, AskRunResponse) else None,
            summary=job.summary if isinstance(job.summary, AnswerOut) else None,
            error=err(job.error),
        )


def _detached(request: Request) -> Request:
    """The app and the caller's address without the connection: a job outlives its
    submit request and must not stop when that request ends."""
    scope = {
        "type": "http", "app": request.app, "client": request.client, "headers": [],
        "method": "POST", "path": request.url.path, "query_string": b"",
    }  # fmt: skip
    return Request(scope)


def _launch(request: Request, user: User, body: AskRequest | None, ask_id: str | None) -> AskJobOut:
    """Start the job in its own thread and event loop, holding the user's one turn."""
    jobs: AskJobs = request.app.state.ask_jobs
    _claim(user.user_id)
    try:
        job = jobs.start(user.user_id, clock.now())
    except Exception:
        _release(user.user_id)
        raise
    req = _detached(request)

    def work() -> None:
        try:
            asyncio.run(_work(job, req, user, body, ask_id))
        finally:
            if job.state == "running":  # _work never got to its end: give the turn back
                _done(jobs, job, user, ("internal_error", "Something went wrong. Ask again."))

    threading.Thread(target=work, name="ask-job", daemon=True).start()
    return _job_out(jobs, job)


def _done(jobs: AskJobs, job: AskJob, user: User, error: tuple[str, str] | None = None) -> None:
    """Give the person's turn back first, then mark the job finished: whoever sees it
    finished may ask again at once."""
    _release(user.user_id)
    jobs.finish(job, clock.now(), error)


async def _work(
    job: AskJob, request: Request, user: User, body: AskRequest | None, ask_id: str | None
) -> None:
    """The steps in order: SQL (for a question), the query (when it may run without a
    click, or for an answer whose Run was clicked), then the summary. Each step's output
    is readable as soon as the step ends."""
    jobs: AskJobs = request.app.state.ask_jobs
    codes: dict[type[Exception], str] = request.app.state.error_codes
    step = None
    try:
        if body is not None:
            step = jobs.begin(job, "sql")
            got = await _ask(body, request, user, live=False)
            job.ask = got
            jobs.end(job, step, "done")
            if got.ask_id is None or not got.auto_run:
                _done(jobs, job, user)  # know-how, or click-to-run: nothing runs without a click
                return
            ask_id = got.ask_id
        assert ask_id is not None
        step = jobs.begin(job, "run")
        result = await _run(ask_id, request, user)
        job.result = result
        jobs.end(job, step, "done")
        if not result.summarize:
            _done(jobs, job, user)
            return
        step = jobs.begin(job, "summary")
        summary = await _answer(ask_id, request, user, live=False)
        job.summary = summary
        jobs.end(job, step, "timed_out" if summary.timed_out else "done")
        _done(jobs, job, user)
    except Exception as exc:
        if isinstance(exc, AppError):
            error = (codes.get(type(exc), "error"), str(exc))
        else:  # an unexpected failure: its class only, never its text (it may hold data)
            log.error("ask.job_failed", job_id=job.job_id, error=type(exc).__name__)
            error = ("internal_error", "Something went wrong. Ask again.")
        if step is not None:
            late = isinstance(exc, ModelTimeoutError)
            jobs.end(job, step, "timed_out" if late else "failed", error)
        _done(jobs, job, user, error)


@router.post("/ask/jobs", status_code=202)
async def submit(body: AskRequest, request: Request, user: AskUser) -> AskJobOut:
    """Ask as a background job: returns at once with `job_id`; poll GET /ask/jobs/{id}."""
    await _chosen(request, body.provider_id)  # a provider problem is said now, not later
    return _launch(request, user, body, None)


@router.post("/ask/{ask_id}/jobs", status_code=202)
async def submit_run(ask_id: str, request: Request, user: AskUser) -> AskJobOut:
    """Run an answer's SQL (the Run click) and then summarize it, as a background job."""
    runs: AskRuns = request.app.state.ask_runs
    runs.get(ask_id, user.user_id, clock.now())  # only the asker's own, while fresh
    return _launch(request, user, None, ask_id)


@router.get("/ask/jobs/{job_id}")
async def job_status(job_id: str, request: Request, user: AskUser) -> AskJobOut:
    """What the job has so far; only for the person who submitted it (others get 404)."""
    jobs: AskJobs = request.app.state.ask_jobs
    return _job_out(jobs, jobs.get(job_id, user.user_id, clock.now()))
