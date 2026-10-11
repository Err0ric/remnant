"""/api/tokens (your own CLI and API tokens) and admin sign-out-everywhere. Router only."""

from datetime import timedelta

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.api.access import AdminUser, CurrentUser, InteractiveUser, client_ip
from app.auth.service import AuthService
from app.auth.sessions import TokenInfo
from app.auth.users import LOCAL_USER
from app.core.errors import ConflictError, NotFoundError

router = APIRouter(tags=["tokens"])

MAX_DAYS = 365


class TokenOut(BaseModel):
    token_id: str
    label: str
    created_at: str
    expires_at: str
    last_used_at: str | None


class TokenCreate(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    days: int = Field(default=90, ge=1, le=MAX_DAYS)


class TokenCreated(TokenOut):
    token: str  # shown once


def _auth(request: Request) -> AuthService:
    auth: AuthService = request.app.state.auth
    return auth


def _out(t: TokenInfo) -> TokenOut:
    return TokenOut(
        token_id=t.token_id,
        label=t.label,
        created_at=t.created_at,
        expires_at=t.expires_at,
        last_used_at=t.last_used_at,
    )


@router.get("/tokens")
async def list_tokens(request: Request, user: CurrentUser) -> list[TokenOut]:
    auth = _auth(request)
    tokens = await run_in_threadpool(auth.sessions.list_tokens, user.user_id, auth.clock())
    return [_out(t) for t in tokens]


@router.post("/tokens", status_code=status.HTTP_201_CREATED)
async def create_token(body: TokenCreate, request: Request, user: InteractiveUser) -> TokenCreated:
    if user.user_id == LOCAL_USER.user_id:
        raise ConflictError("This install runs without sign-in, so it needs no tokens")
    auth = _auth(request)
    token, _, token_id = await run_in_threadpool(
        auth.sessions.issue,
        user.user_id,
        "cli",
        timedelta(days=body.days),
        auth.clock(),
        body.label,
    )
    await run_in_threadpool(
        auth.audit.write,
        "token.create",
        "success",
        user.user_id,
        client_ip(request),
        {"token_id": token_id, "label": body.label, "days": body.days},
    )
    created = next(
        t for t in auth.sessions.list_tokens(user.user_id, auth.clock()) if t.token_id == token_id
    )
    return TokenCreated(**_out(created).model_dump(), token=token)


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(token_id: str, request: Request, user: CurrentUser) -> Response:
    auth = _auth(request)
    if not await run_in_threadpool(auth.sessions.revoke_token, user.user_id, token_id):
        raise NotFoundError("No such token")
    await run_in_threadpool(
        auth.audit.write,
        "token.revoke",
        "success",
        user.user_id,
        client_ip(request),
        {"token_id": token_id},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/users/{user_id}/signout", status_code=status.HTTP_204_NO_CONTENT)
async def sign_out_everywhere(user_id: str, request: Request, actor: AdminUser) -> Response:
    """Admin response to a lost laptop: end every session and token of one user."""
    auth = _auth(request)
    if await run_in_threadpool(auth.users.get, user_id) is None:
        raise NotFoundError("No such user")
    count = await run_in_threadpool(auth.sessions.revoke_user, user_id)
    await run_in_threadpool(
        auth.audit.write,
        "user.signout_all",
        "success",
        actor.user_id,
        client_ip(request),
        {"target": user_id, "sessions": count},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
