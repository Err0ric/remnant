"""/api/ask: Ask mode (SPEC 5.3). Router only.

Returns the SQL with an `ask_id`; `POST /api/ask/{ask_id}/run` runs exactly that SQL for
the person who asked, through the guard on their own view, audited like any query with
purpose `ask` (ADR-0042 slice 1a). With `ask.auto_run` on, the panel calls it at once.
Scope comes from the caller's grants exactly as in /api/query. Auditors have no Ask
(SPEC 3.6).
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, StringConstraints
from starlette.concurrency import run_in_threadpool

from app.api.access import client_ip, require_role
from app.api.cancel import watch_disconnect
from app.api.query import QueryRequest, QueryResponse, _geo, _intel, _run_audited
from app.auth.service import AuthService
from app.auth.users import User
from app.core.config import AppConfig
from app.core.errors import AppError, ParamInvalidError, ProviderConfigError, RateLimitedError
from app.engine.duckdb import QueryScope
from app.engine.views import permitted_sources, scope_sources
from app.llm import gate
from app.llm.agent import AskAgent, AskExample, AskTurn
from app.llm.ask_summary import summarize
from app.llm.provider import Locality
from app.llm.queue import QUEUES
from app.llm.registry import ProviderRecord, ProviderStore
from app.meta.db import MetaDB
from app.search.ask_drill import DrillError, drill_sql
from app.search.ask_flow import Routed, route_question
from app.search.ask_route import Plan, rank
from app.search.ask_runs import AskRuns, Drill, Ran
from app.search.ask_summary import check_claims, headline, removed_note, sample
from app.search.library import Library, LibraryQuery, editor_sql
from app.search.saved import SavedSearchStore

router = APIRouter(tags=["ask"])

AskUser = Annotated[User, Depends(require_role("admin", "analyst"))]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)]


class Turn(BaseModel):
    question: Text
    sql: str = Field(min_length=1, max_length=20_000)


class AskRequest(BaseModel):
    question: Text
    provider_id: str | None = Field(default=None, max_length=64)
    start: datetime | None = None
    end: datetime | None = None
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
    by: Literal["model", "forced", "follow_up"]
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
    start: datetime | None = None
    end: datetime | None = None


_running: set[str] = set()
_running_lock = threading.Lock()


@contextmanager
def _one_at_a_time(user_id: str) -> Iterator[None]:
    """One Ask per user at a time: each can run several model calls and previews."""
    with _running_lock:
        if user_id in _running:
            raise RateLimitedError("Your previous question is still running", retry_after_s=5)
        _running.add(user_id)
    try:
        yield
    finally:
        with _running_lock:
            _running.discard(user_id)


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


@router.post("/ask")
async def ask(body: AskRequest, request: Request, user: AskUser) -> AskResponse:
    meta: MetaDB = request.app.state.meta
    auth: AuthService = request.app.state.auth
    agent: AskAgent = request.app.state.ask
    choices = await run_in_threadpool(_enabled, request)
    if body.provider_id is None:
        if not choices:
            raise ProviderConfigError("No AI provider is enabled. An admin can add one.")
        chosen = choices[0]
    else:
        match = [p for p in choices if p.provider_id == body.provider_id]
        if not match:
            raise ProviderConfigError("That AI provider is not available")
        chosen = match[0]

    allowed = await run_in_threadpool(permitted_sources, meta, user)
    scope = QueryScope(sources=scope_sources(allowed, body.sources), start=body.start, end=body.end)
    history = [AskTurn(t.question, t.sql) for t in body.history]
    searches: SavedSearchStore = request.app.state.searches
    found = await run_in_threadpool(searches.examples, user, body.question)
    examples = [AskExample(s.name, s.sql) for s in found]
    detail: dict[str, object] = {
        "question": body.question,
        "provider_id": chosen.provider_id,
        "sources_requested": body.sources,
        "examples": [s.id for s in found],
    }
    now = datetime.now(UTC)
    routed: Routed | None = None
    try:
        async with watch_disconnect(request):
            with _one_at_a_time(user.user_id):
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
        raise
    config: AppConfig = request.app.state.config
    runs: AskRuns = request.app.state.ask_runs
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
            drill=_drill(c.query, routed.plan),
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
        call_ids, now, body.question, provider_id=chosen.provider_id,
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
    ident = state.identities.load()
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


@router.post("/ask/{ask_id}/run")
async def run_answer(ask_id: str, request: Request, user: AskUser) -> AskRunResponse:
    """Run the SQL an answer produced, as the person who asked, on their current view.
    Audited as query.run with purpose `ask`, the answer's id, its model call ids, and its
    origin (`generated`, or the library query `<pack>/<id>@<version>`). Returns a headline
    written by code from the rows."""
    runs: AskRuns = request.app.state.ask_runs
    config: AppConfig = request.app.state.config
    run = runs.get(ask_id, user.user_id, datetime.now(UTC))
    end = run.end or datetime.now(UTC)
    start = run.start
    if start is None or end - start > timedelta(days=ASK_MAX_DAYS):
        start = end - timedelta(days=ASK_MAX_DAYS)
    body = QueryRequest(
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
    head = headline(result.columns, result.rows, result.truncated, run.template)
    rows = sample(result.columns, result.rows, result.truncated)
    runs.ran(run.ask_id, Ran(rows, list(result.sources), head, start, end))
    note = None
    if config.ask.summarize and result.rows and rows is None:
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


@router.post("/ask/{ask_id}/answer")
async def answer(ask_id: str, request: Request, user: AskUser) -> AnswerOut:
    """The answer step (ADR-0042 row 8, slice 1c): statements about the rows the run kept,
    each citing their event ids; never rows from the client. Statements that cite no sent
    row are removed and counted. Any failure of the model leaves the rows and the headline
    without a summary. Audited as ask.answer."""
    runs: AskRuns = request.app.state.ask_runs
    config: AppConfig = request.app.state.config
    auth: AuthService = request.app.state.auth
    run, ran = runs.result(ask_id, user.user_id, datetime.now(UTC))
    if not config.ask.summarize:
        raise ProviderConfigError("Summaries are turned off on this server (ask.summarize)")
    if ran.sample is None or not run.provider_id:
        return AnswerOut(
            headline=ran.headline, claims=[], removed=0, call_id=None,
            note="No summary: these rows have no event ids to cite.",
        )  # fmt: skip
    detail: dict[str, object] = {"ask_id": run.ask_id, "provider_id": run.provider_id}
    try:
        async with watch_disconnect(request):
            with _one_at_a_time(user.user_id):
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
        return AnswerOut(
            headline=ran.headline, claims=[], removed=0, call_id=None,
            note=f"No summary: {exc}",
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
    run, ran = runs.result(ask_id, user.user_id, datetime.now(UTC))
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
