"""/api/ask: Ask mode (SPEC 5.3). Router only.

Returns SQL for the analyst to review; never runs it for them. Scope comes from the
caller's grants exactly as in /api/query. Auditors have no Ask (SPEC 3.6).
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, StringConstraints
from starlette.concurrency import run_in_threadpool

from app.api.access import client_ip, require_role
from app.auth.service import AuthService
from app.auth.users import User
from app.core.config import AppConfig
from app.core.errors import ProviderConfigError, RateLimitedError
from app.engine.duckdb import QueryScope
from app.engine.views import permitted_sources, scope_sources
from app.llm import gate
from app.llm.agent import AskAgent, AskExample, AskTurn
from app.llm.provider import Locality
from app.llm.registry import ProviderRecord, ProviderStore
from app.meta.db import MetaDB
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


class AskProvider(BaseModel):
    provider_id: str
    name: str
    model: str
    locality: Locality


class AskResponse(BaseModel):
    sql: str
    explanation: str
    assumptions: list[str]
    check: Literal["ok", "empty", "failed"]
    check_detail: str | None
    attempts: int
    provider: AskProvider
    call_ids: list[str]


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
    try:
        with _one_at_a_time(user.user_id):
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
    detail |= {"call_ids": outcome.call_ids, "check": outcome.check}
    await run_in_threadpool(
        auth.audit.write, "ask.request", "success", user.user_id, client_ip(request), detail
    )
    return AskResponse(
        sql=outcome.answer.sql,
        explanation=outcome.answer.explanation,
        assumptions=outcome.answer.assumptions,
        check=outcome.check,
        check_detail=outcome.check_detail,
        attempts=outcome.attempts,
        provider=chosen,
        call_ids=outcome.call_ids,
    )
