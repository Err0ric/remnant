"""Live mode (ADR-0036): a server-sent event stream that follows one row query. Router only.

Events: `start` (stream id, since), `rows` (columns, rows, cursor), `lag` (per source,
every 10 s), `notice` (a message), `end` (reason). A dropped connection is a stop."""

import asyncio
import json
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.api.access import AdminUser, CurrentUser, client_ip
from app.auth.service import AuthService
from app.auth.users import User
from app.core.errors import AppError, NotFoundError
from app.engine.duckdb import QueryEngine
from app.engine.views import permitted_sources, scope_sources
from app.search import live as lv

router = APIRouter(tags=["search"])
MAX_SQL = 20_000


class StreamOut(BaseModel):
    stream_id: str
    client: str
    started_at: str
    label: str


class LimitIn(BaseModel):
    minutes: int = Field(ge=1, le=24 * 60)


class LimitOut(BaseModel):
    minutes: int


def _reg(request: Request) -> lv.LiveRegistry:
    r: lv.LiveRegistry = request.app.state.live
    return r


def _audit(request: Request, action: str, user: User, detail: dict[str, Any]) -> None:
    auth: AuthService = request.app.state.auth
    auth.audit.write(action, "success", user.user_id, client_ip(request), detail)


def _sse(event: str, data: Any) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n".encode()


def _narrowed(start: list[str] | None, now: list[str] | None) -> bool:
    """Access shrank since the start: an admin is no longer one, or a source went away."""
    if start is None:
        return now is not None
    return now is not None and not set(start) <= set(now)


@router.get("/search/live")
async def live(
    request: Request,
    user: CurrentUser,
    q: Annotated[str, Query(min_length=1, max_length=MAX_SQL)],
    client: lv.Client = "browser",
    sources: Annotated[list[str] | None, Query(max_length=200)] = None,
    since: datetime | None = None,
    after: Annotated[list[str] | None, Query(max_length=1000)] = None,
) -> StreamingResponse:
    """Follow new rows of `q` (row queries only). With `since` (Resume), first sends what
    arrived after it, up to 1,000 rows, newest kept. Audited `search.live_start` and
    `search.live_stop`."""
    sql = lv.live_sql(q)  # refuses non-row queries before anything starts
    newest_sql = lv.live_sql(q, newest=True)
    meta = request.app.state.meta
    engine: QueryEngine = request.app.state.engine
    reg = _reg(request)
    allowed = await run_in_threadpool(permitted_sources, meta, user)
    scope = scope_sources(allowed, sources)
    now = datetime.now(UTC)
    stream = reg.open(user.user_id, client, now)
    resumed = since is not None
    cursor = lv.Cursor(
        (since if since.tzinfo else since.replace(tzinfo=UTC)).astimezone(UTC) if since else now,
        set(after or []),
    )
    kinds = {s.source_id: s.kind or "file" for s in request.app.state.sources.list()}
    # The partitions a poll reads start a day before the stream, or before the cursor it
    # resumes from (a CLI follow after `tail -n`), whichever is earlier.
    reads_from = min(now, cursor.t)
    await run_in_threadpool(
        _audit, request, "search.live_start", user,
        {"stream_id": stream.stream_id, "sql_sha256": lv.sql_hash(q), "sql": q[:4000],
         "client": client, "resumed": resumed,
         "sources_in_scope": "all" if scope is None else scope},
    )  # fmt: skip

    async def body() -> AsyncIterator[bytes]:
        began = time.monotonic()
        limit = reg.limit_s()
        sent = 0
        reason = "user"
        last_lag = -lv.LAG_EVERY_S
        first = True
        try:
            yield _sse("start", {"stream_id": stream.stream_id, "since": cursor.t.isoformat(),
                                 "limit_s": limit, "poll_s": reg.poll_s})  # fmt: skip
            while True:
                if stream.stop.is_set():
                    reason = "user"
                    yield _sse("end", {"reason": "stopped", "message": "Stopped."})
                    return
                if await request.is_disconnected():
                    reason = "disconnect"
                    return
                if time.monotonic() - began >= limit:
                    reason = "time limit"
                    text = lv.MSG_LIMIT.format(minutes=round(limit / 60))
                    yield _sse("end", {"reason": "time_limit", "message": text})
                    return
                current = await run_in_threadpool(permitted_sources, meta, user)
                if _narrowed(allowed, current):
                    reason = "access changed"
                    yield _sse("end", {"reason": "access", "message": lv.MSG_ACCESS})
                    return
                try:
                    got = await run_in_threadpool(lv.poll, engine, sql, scope, cursor, reads_from)
                    if got.too_many and first and resumed:
                        got = await run_in_threadpool(
                            lv.poll, engine, newest_sql, scope, cursor, reads_from, True
                        )
                        yield _sse("notice", {"message": lv.MSG_BACKFILL})
                except AppError as exc:
                    reason = "error"
                    yield _sse("end", {"reason": "error", "message": str(exc)[:300]})
                    return
                if got.too_many:
                    reason = "too many rows"
                    text = lv.MSG_TOO_MANY.format(secs=reg.poll_s)
                    yield _sse("end", {"reason": "too_many", "message": text})
                    return
                if got.rows:
                    sent += len(got.rows)
                    mark = {"t": cursor.t.isoformat(), "ids": sorted(cursor.ids)[:1000]}
                    yield _sse("rows", {"columns": got.columns, "rows": got.rows, "cursor": mark})
                else:
                    yield b": ping\n\n"
                first = False
                if time.monotonic() - last_lag >= lv.LAG_EVERY_S:
                    last_lag = time.monotonic()
                    sources_lag = await run_in_threadpool(
                        lv.lag, engine, scope, kinds, datetime.now(UTC)
                    )
                    yield _sse("lag", {"sources": sources_lag})
                await asyncio.sleep(reg.poll_s)
        finally:
            reg.close(stream.stream_id)
            await run_in_threadpool(
                _audit, request, "search.live_stop", user,
                {"stream_id": stream.stream_id, "reason": reason,
                 "duration_s": round(time.monotonic() - began), "events_sent": sent},
            )  # fmt: skip

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/search/live/streams")
async def my_streams(request: Request, user: CurrentUser) -> list[StreamOut]:
    """The caller's open live streams, browser, CLI, and TUI together (row 5)."""
    return [
        StreamOut(
            stream_id=s.stream_id,
            client=s.client,
            started_at=s.started_at.isoformat(),
            label=s.describe(),
        )
        for s in _reg(request).mine(user.user_id)
    ]


@router.delete("/search/live/streams/{stream_id}", status_code=status.HTTP_204_NO_CONTENT)
async def stop_stream(stream_id: str, request: Request, user: CurrentUser) -> Response:
    """Stop one of the caller's streams; it ends at its next poll."""
    if not _reg(request).stop(user.user_id, stream_id):
        raise NotFoundError("No such live search")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/settings/live")
async def get_limit(request: Request, user: CurrentUser) -> LimitOut:
    return LimitOut(minutes=await run_in_threadpool(lv.limit_minutes, request.app.state.meta))


@router.put("/settings/live")
async def put_limit(body: LimitIn, request: Request, user: AdminUser) -> LimitOut:
    """The live time limit for every role (row 5). Audited `settings.live_limit`."""
    meta = request.app.state.meta
    before = await run_in_threadpool(lv.limit_minutes, meta)
    after = await run_in_threadpool(lv.set_limit_minutes, meta, body.minutes, user.user_id)
    await run_in_threadpool(
        _audit, request, "settings.live_limit", user, {"from": before, "to": after}
    )
    return LimitOut(minutes=after)
