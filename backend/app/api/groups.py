"""/api/groups: source groups, admin only. Router only."""

from typing import Annotated

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field, StringConstraints
from starlette.concurrency import run_in_threadpool

from app.api.access import AdminUser, client_ip
from app.auth.groups import Group, GroupStore
from app.auth.service import AuthService
from app.auth.suggestions import Kind, Suggestion, accept, suggest
from app.ingest.sources import SourceStore
from app.templates.registry import TemplateRegistry

router = APIRouter(tags=["groups"])


class GroupOut(BaseModel):
    group_id: str
    name: str
    description: str
    source_ids: list[str]
    user_ids: list[str]


# Trimmed before the length check, so "   " is rejected rather than stored as "".
GroupName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class GroupCreate(BaseModel):
    name: GroupName
    description: str = Field(default="", max_length=500)


class GroupUpdate(BaseModel):
    name: GroupName | None = None
    description: str | None = Field(default=None, max_length=500)


class SourceSet(BaseModel):
    source_ids: list[str] = Field(max_length=1000)


class MemberSet(BaseModel):
    user_ids: list[str] = Field(max_length=1000)


def _store(request: Request) -> GroupStore:
    store: GroupStore = request.app.state.groups
    return store


def _out(g: Group) -> GroupOut:
    return GroupOut(
        group_id=g.group_id,
        name=g.name,
        description=g.description,
        source_ids=g.source_ids,
        user_ids=g.user_ids,
    )


@router.get("/groups")
async def list_groups(request: Request, _: AdminUser) -> list[GroupOut]:
    return [_out(g) for g in await run_in_threadpool(_store(request).all)]


@router.post("/groups", status_code=status.HTTP_201_CREATED)
async def create_group(body: GroupCreate, request: Request, actor: AdminUser) -> GroupOut:
    g = await run_in_threadpool(
        _store(request).create, body.name, body.description, actor, client_ip(request)
    )
    return _out(g)


@router.patch("/groups/{group_id}")
async def update_group(
    group_id: str, body: GroupUpdate, request: Request, actor: AdminUser
) -> GroupOut:
    g = await run_in_threadpool(
        _store(request).update, group_id, actor, client_ip(request), body.name, body.description
    )
    return _out(g)


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(group_id: str, request: Request, actor: AdminUser) -> Response:
    await run_in_threadpool(_store(request).delete, group_id, actor, client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/groups/{group_id}/sources")
async def set_group_sources(
    group_id: str, body: SourceSet, request: Request, actor: AdminUser
) -> GroupOut:
    g = await run_in_threadpool(
        _store(request).set_sources, group_id, body.source_ids, actor, client_ip(request)
    )
    return _out(g)


@router.put("/groups/{group_id}/members")
async def set_group_members(
    group_id: str, body: MemberSet, request: Request, actor: AdminUser
) -> GroupOut:
    g = await run_in_threadpool(
        _store(request).set_members, group_id, body.user_ids, actor, client_ip(request)
    )
    return _out(g)


class SuggestionOut(BaseModel):
    kind: Kind
    key: str
    name: str
    group_id: str | None
    source_ids: list[str]
    missing: list[str]


class SuggestionAccept(BaseModel):
    kind: Kind
    key: str = Field(min_length=1, max_length=32)
    source_ids: list[str] = Field(min_length=1, max_length=1000)


def _suggestions(request: Request) -> list[Suggestion]:
    sources: SourceStore = request.app.state.sources
    registry: TemplateRegistry = request.app.state.templates
    return suggest(sources.list(), registry.get, _store(request).all())


@router.get("/groups/suggestions")
async def list_suggestions(request: Request, _: AdminUser) -> list[SuggestionOut]:
    """Suggestions only: listing creates and grants nothing."""
    found = await run_in_threadpool(_suggestions, request)
    return [
        SuggestionOut(
            kind=s.kind,
            key=s.key,
            name=s.name,
            group_id=s.group_id,
            source_ids=s.source_ids,
            missing=s.missing,
        )
        for s in found
    ]


@router.post("/groups/suggestions/accept")
async def accept_suggestion(body: SuggestionAccept, request: Request, actor: AdminUser) -> GroupOut:
    auth: AuthService = request.app.state.auth

    def run() -> Group:
        return accept(
            _suggestions(request),
            body.kind,
            body.key,
            body.source_ids,
            _store(request),
            auth.audit,
            actor,
            client_ip(request),
        )

    return _out(await run_in_threadpool(run))
