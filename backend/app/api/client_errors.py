"""`POST /api/client-errors`: the web UI reports a page or panel that failed to render or a
page chunk that failed to load (owner 2026-11-02), so it shows on Health and in the
server's log. Signed-in users only (CSRF like every POST); rate-limited; the body holds no
log content (the browser scrubs the message). Router only."""

from datetime import UTC, datetime
from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, StringConstraints

from app.api.access import CurrentUser
from app.core.client_errors import ClientError, ClientErrors

router = APIRouter(tags=["meta"])
log = structlog.get_logger(__name__)

Short = Annotated[str, StringConstraints(max_length=200)]


class ClientErrorIn(BaseModel):
    kind: Literal["render", "panel", "chunk", "unhandled"]
    error_id: Annotated[str, StringConstraints(pattern=r"^e-[0-9a-f]{6}$")]
    name: Annotated[str, StringConstraints(max_length=40)] = "Error"
    message: Short = ""
    route: Annotated[str, StringConstraints(max_length=120)] = ""
    build: Annotated[str, StringConstraints(max_length=60)] = ""


@router.post("/client-errors", status_code=204)
async def client_error(body: ClientErrorIn, request: Request, user: CurrentUser) -> Response:
    """Record one browser error. Over the limit it is counted and dropped, still 204."""
    store: ClientErrors = request.app.state.client_errors
    now = datetime.now(UTC)
    if store.allow(user.user_id, now):
        served = request.app.state.ui_build
        stale = bool(served and body.build and body.build not in ("dev", served))
        store.add(
            ClientError(
                now, body.error_id, body.kind, body.name, body.message, body.route,
                body.build, stale, user.user_id,
            )
        )  # fmt: skip
        log.warning(
            "client.error",
            error_id=body.error_id,
            kind=body.kind,
            name=body.name,
            message=body.message,
            route=body.route,
            build=body.build,
            stale_page=stale,
            user_id=user.user_id,
        )
    return Response(status_code=204)
