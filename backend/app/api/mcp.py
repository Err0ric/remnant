"""Read-only MCP server endpoint and its settings (ADR-0003). Routers only."""

import json
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.access import AdminUser, CurrentUser, client_ip
from app.auth.service import AuthService
from app.core.errors import ForbiddenError, ParamInvalidError
from app.mcp.server import McpServer
from app.mcp.settings import McpSettingsStore

router = APIRouter(tags=["mcp"])

MAX_BODY = 1024 * 1024
SESSION_HEADER = "Mcp-Session-Id"


def _origin_ok(request: Request) -> bool:
    """MCP Streamable HTTP: refuse a browser page on another site (DNS rebinding)."""
    origin = request.headers.get("origin")
    if not origin:
        return True
    return urlsplit(origin).netloc == request.headers.get("host", "")


@router.post("/mcp", include_in_schema=False)
async def mcp_post(request: Request, user: CurrentUser) -> Response:
    """JSON-RPC over MCP Streamable HTTP, answered as JSON. Needs a per-user API token
    (or the loopback single-user mode); a browser session cannot call it."""
    if getattr(request.state, "via", None) == "cookie":
        raise ForbiddenError("Use a personal API token for MCP clients, not a browser session")
    if not _origin_ok(request):
        raise ForbiddenError("Requests from other web pages are refused")
    store: McpSettingsStore = request.app.state.mcp_settings
    settings = await run_in_threadpool(store.get)
    if not settings.enabled:
        raise ForbiddenError("The MCP server is off. An administrator can turn it on in Settings.")
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise ParamInvalidError("Request too large")
    try:
        message: Any = json.loads(raw)
    except ValueError:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        )
    server: McpServer = request.app.state.mcp
    reply = await run_in_threadpool(
        server.handle,
        message,
        user,
        settings,
        request.headers.get(SESSION_HEADER),
        client_ip(request),
    )
    headers = {SESSION_HEADER: reply.session_id} if reply.session_id else {}
    if reply.body is None:
        return Response(status_code=202, headers=headers)
    return JSONResponse(reply.body, headers=headers)


@router.get("/mcp", include_in_schema=False)
async def mcp_get(_: CurrentUser) -> Response:
    """No server-initiated stream: nothing here pushes to clients."""
    return Response(status_code=405, headers={"Allow": "POST"})


@router.delete("/mcp", include_in_schema=False)
async def mcp_delete(_: CurrentUser) -> Response:
    return Response(status_code=204)  # sessions only name the client; nothing to end


class McpSettingsOut(BaseModel):
    enabled: bool
    endpoint_local: bool
    updated_at: str | None
    path: str = "/api/mcp"


class McpSettingsIn(BaseModel):
    enabled: bool
    endpoint_local: bool


@router.get("/mcp/settings")
async def get_mcp_settings(request: Request, _: AdminUser) -> McpSettingsOut:
    store: McpSettingsStore = request.app.state.mcp_settings
    s = await run_in_threadpool(store.get)
    return McpSettingsOut(
        enabled=s.enabled, endpoint_local=s.endpoint_local, updated_at=s.updated_at
    )


@router.put("/mcp/settings")
async def put_mcp_settings(
    body: McpSettingsIn, request: Request, user: AdminUser
) -> McpSettingsOut:
    store: McpSettingsStore = request.app.state.mcp_settings
    before = await run_in_threadpool(store.get)
    s = await run_in_threadpool(store.save, body.enabled, body.endpoint_local, user.user_id)
    auth: AuthService = request.app.state.auth
    await run_in_threadpool(
        auth.audit.write,
        "mcp.settings",
        "success",
        user.user_id,
        client_ip(request),
        {
            "enabled": [before.enabled, s.enabled],
            "endpoint_local": [before.endpoint_local, s.endpoint_local],
        },
    )
    return McpSettingsOut(
        enabled=s.enabled, endpoint_local=s.endpoint_local, updated_at=s.updated_at
    )
