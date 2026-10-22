"""/api/explain: explain selected events with cited claims (Slice 4). Router only.

Admins and analysts only (auditors have no AI features, SPEC 3.6). Scope is the caller's
permitted sources; events outside it are never fetched or sent.
"""

from typing import Annotated

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, StringConstraints
from starlette.concurrency import run_in_threadpool

from app.api.access import client_ip
from app.api.ask import AskProvider, AskUser, _enabled, _one_at_a_time
from app.api.cancel import watch_disconnect
from app.auth.service import AuthService
from app.core.errors import ProviderConfigError
from app.engine.duckdb import QueryScope
from app.engine.views import permitted_sources
from app.llm.explain import MAX_EVENTS, Explainer
from app.meta.db import MetaDB

router = APIRouter(tags=["explain"])


class ExplainRequest(BaseModel):
    event_ids: list[Annotated[str, StringConstraints(max_length=64)]] = Field(
        min_length=1, max_length=MAX_EVENTS
    )
    provider_id: str | None = Field(default=None, max_length=64)
    question: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class ClaimOut(BaseModel):
    text: str
    event_ids: list[str]
    verified: bool  # cites at least one event, and only events that were sent


class ExplainResponse(BaseModel):
    claims: list[ClaimOut]
    citation_check: str  # pass: every claim's ids were sent and at least one id is cited
    call_id: str
    events_sent: list[str]
    not_found: int
    sources: list[str]
    provider: AskProvider


@router.post("/explain")
async def explain(body: ExplainRequest, request: Request, user: AskUser) -> ExplainResponse:
    meta: MetaDB = request.app.state.meta
    auth: AuthService = request.app.state.auth
    explainer: Explainer = request.app.state.explainer
    choices = await run_in_threadpool(_enabled, request)
    match = [p for p in choices if body.provider_id in (None, p.provider_id)]
    if not match:
        raise ProviderConfigError(
            "No AI provider is enabled. An admin can add one."
            if not choices
            else "That AI provider is not available"
        )
    chosen = match[0]
    allowed = await run_in_threadpool(permitted_sources, meta, user)
    detail: dict[str, object] = {
        "provider_id": chosen.provider_id,
        "requested": len(body.event_ids),
    }
    try:
        async with watch_disconnect(request):
            with _one_at_a_time(user.user_id):
                out = await run_in_threadpool(
                    explainer.explain,
                    user.user_id,
                    chosen.provider_id,
                    QueryScope(sources=allowed),
                    body.event_ids,
                    body.question,
                )
    except Exception as exc:  # every outcome is audited
        detail["error"] = type(exc).__name__
        await run_in_threadpool(
            auth.audit.write, "explain.request", "failure", user.user_id, client_ip(request), detail
        )
        raise
    detail |= {
        "call_id": out.call_id,
        "events_sent": len(out.events_sent),
        "citation_check": out.citation_check,
        "sources_in_scope": out.sources,
    }
    await run_in_threadpool(
        auth.audit.write, "explain.request", "success", user.user_id, client_ip(request), detail
    )
    return ExplainResponse(
        claims=[
            ClaimOut(text=c.text, event_ids=c.event_ids, verified=c.verified) for c in out.claims
        ],
        citation_check=out.citation_check,
        call_id=out.call_id,
        events_sent=out.events_sent,
        not_found=out.not_found,
        sources=out.sources,
        provider=chosen,
    )
