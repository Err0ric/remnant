"""One person under several names (ADR-0018): organization domains, aliases, and
suggestions. Administrators only; changes audited `identity.change`. Router only."""

from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.api.access import AdminUser, client_ip
from app.auth.service import AuthService
from app.engine.duckdb import QueryEngine, QueryScope
from app.search.entities import to_json
from app.search.identity import IdentityStore, suggestions

router = APIRouter(tags=["identities"])


class AliasOut(BaseModel):
    alias: str
    person: str
    created_by: str | None
    created_at: str


class DomainSuggestionOut(BaseModel):
    domain: str
    addresses: int
    shared: int
    examples: list[str]


class AliasSuggestionOut(BaseModel):
    alias: str
    person: str
    hosts: list[str]


class IdentitiesOut(BaseModel):
    domains: list[str]
    aliases: list[AliasOut]
    domain_suggestions: list[DomainSuggestionOut]
    alias_suggestions: list[AliasSuggestionOut]


class DomainsIn(BaseModel):
    domains: list[str] = Field(max_length=20)


class AliasIn(BaseModel):
    alias: str = Field(min_length=1, max_length=256)
    person: str | None = Field(default=None, max_length=256)  # null removes the alias


def _store(request: Request) -> IdentityStore:
    store: IdentityStore = request.app.state.identities
    return store


async def _audit(request: Request, user: AdminUser, detail: dict[str, object]) -> None:
    auth: AuthService = request.app.state.auth
    await run_in_threadpool(
        auth.audit.write, "identity.change", "success", user.user_id, client_ip(request), detail
    )


@router.get("/identities")
async def identities(
    request: Request, user: AdminUser, start: datetime | None = None
) -> IdentitiesOut:
    """Current domains and aliases, and suggestions from the events in range (all sources:
    administrators only)."""
    store = _store(request)
    m = await run_in_threadpool(store.load)
    engine: QueryEngine = request.app.state.engine
    doms, als = await run_in_threadpool(
        suggestions, engine, QueryScope(sources=None, start=start), m
    )
    return IdentitiesOut(
        domains=m.domains,
        aliases=[AliasOut(**a) for a in await run_in_threadpool(store.aliases)],
        domain_suggestions=[DomainSuggestionOut(**to_json(d)) for d in doms],
        alias_suggestions=[AliasSuggestionOut(**to_json(a)) for a in als],
    )


@router.put("/identities/domains")
async def set_domains(body: DomainsIn, request: Request, user: AdminUser) -> list[str]:
    clean = await run_in_threadpool(_store(request).set_domains, body.domains, user.user_id)
    await _audit(request, user, {"domains": clean})
    return clean


@router.put("/identities/aliases")
async def set_alias(body: AliasIn, request: Request, user: AdminUser) -> list[AliasOut]:
    store = _store(request)
    await run_in_threadpool(store.set_alias, body.alias, body.person, user.user_id)
    await _audit(request, user, {"alias": body.alias, "person": body.person})
    return [AliasOut(**a) for a in await run_in_threadpool(store.aliases)]
