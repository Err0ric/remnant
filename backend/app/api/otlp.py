"""OTLP/HTTP JSON receiver routes (ADR-0015 row 3). Router only.

`POST /api/otlp/v1/logs` and `/api/otlp/v1/metrics` take standard OTLP JSON with
`Authorization: Bearer <ingest token>`. The token names one OTLP source and can only
write to it; there is no session, cookie, or CSRF involved. Exporters point at
`OTEL_EXPORTER_OTLP_ENDPOINT=https://<host>/api/otlp` with protocol `http/json`.
"""

import threading
import time
from collections import deque
from collections.abc import Iterator
from typing import Any

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.auth.service import AuthService
from app.core.errors import (
    AuthRequiredError,
    PayloadTooLargeError,
    RateLimitedError,
    SetupRequiredError,
    UnsupportedMediaError,
)
from app.ingest.otlp import (
    MAX_BODY,
    NativeLine,
    Spool,
    SpoolFullError,
    decode_body,
    lines,
    log_records,
    metric_records,
)
from app.ingest.sources import SourceConfig, SourceStore

router = APIRouter(tags=["otlp"])
log = structlog.get_logger()

PER_MINUTE = 1200  # requests per source; Claude Code sends logs every 5 s per user
_MAX_COMPRESSED = MAX_BODY  # a compressed body larger than the cap is refused unread


class _Limiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, now: float) -> None:
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= PER_MINUTE:
                raise RateLimitedError("Too many requests for this source", 10)
            q.append(now)


_limiter = _Limiter()


def _source(request: Request) -> SourceConfig:
    auth: AuthService = request.app.state.auth
    if auth.mode() == "setup":
        raise SetupRequiredError("Finish setup first")
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    store: SourceStore = request.app.state.sources
    source = store.otlp_source_for(token.strip()) if scheme.lower() == "bearer" else None
    if source is None:
        log.warning("otlp.refused", reason="token")  # never the token itself
        raise AuthRequiredError("Send the source's ingest token as a bearer token")
    return source


async def _body(request: Request) -> Any:
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype in ("application/x-protobuf", "application/protobuf"):
        raise UnsupportedMediaError(
            "Use OTLP over HTTP with JSON: set OTEL_EXPORTER_OTLP_PROTOCOL=http/json"
        )
    if ctype != "application/json":
        raise UnsupportedMediaError("Send OTLP JSON (Content-Type: application/json)")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > _MAX_COMPRESSED:
        raise PayloadTooLargeError("The request is too large")
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > _MAX_COMPRESSED:
            raise PayloadTooLargeError("The request is too large")
    return decode_body(bytes(raw), request.headers.get("content-encoding"))


async def _accept(
    request: Request, records: Iterator[dict[str, Any] | NativeLine], source: SourceConfig
) -> JSONResponse:
    spool: Spool = request.app.state.otlp_spool
    auth: AuthService = request.app.state.auth
    chunk = lines(records)
    try:
        await run_in_threadpool(spool.append, source.source_id, chunk, auth.clock())
    except SpoolFullError as exc:
        raise RateLimitedError("This source has a backlog; try again shortly", 60) from exc
    # OTLP success: an empty ExportLogsServiceResponse / ExportMetricsServiceResponse.
    return JSONResponse({})


@router.post("/otlp/v1/logs")
async def otlp_logs(request: Request) -> JSONResponse:
    source = await run_in_threadpool(_source, request)
    _limiter.check(source.source_id, time.monotonic())
    payload = await _body(request)
    return await _accept(request, log_records(payload, source.otlp_keep_content), source)


@router.post("/otlp/v1/metrics")
async def otlp_metrics(request: Request) -> JSONResponse:
    source = await run_in_threadpool(_source, request)
    _limiter.check(source.source_id, time.monotonic())
    payload = await _body(request)
    return await _accept(request, metric_records(payload), source)
