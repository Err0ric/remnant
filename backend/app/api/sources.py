"""/api/sources: list, add, and remove file sources. Router only."""

import threading
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field, SecretStr, model_validator
from starlette.concurrency import run_in_threadpool

from app.api.access import AdminUser, CurrentUser, client_ip
from app.auth.service import AuthService
from app.core.errors import NotFoundError, RateLimitedError
from app.core.ids import AUTO_PARSER
from app.engine.views import permitted_sources
from app.ingest.connectors.loki import LokiSettings
from app.ingest.connectors.loki import test_connection as loki_test
from app.ingest.discovery import DiscoveryReport, discover
from app.ingest.sources import SourceConfig, SourceStore
from app.ingest.watcher import IngestService, SourceStatus, source_state
from app.meta.db import MetaDB
from app.templates.drafts import DraftStore
from app.templates.registry import TemplateRegistry

router = APIRouter(tags=["sources"])
_discovery_running = threading.Lock()  # one folder scan at a time per server


def _store(request: Request) -> SourceStore:
    store: SourceStore = request.app.state.sources
    return store


def _audit(request: Request) -> AuthService:
    auth: AuthService = request.app.state.auth
    return auth


class StatusOut(BaseModel):
    state: Literal["waiting", "reading", "error", "disabled"]
    files: int
    last_pass_at: datetime | None
    last_event_at: datetime | None
    events_since_start: int
    error: str | None
    records_skipped: int
    files_waiting: int
    behind_s: float | None = None  # Loki sources: how far reading is behind now


class SourceOut(SourceConfig):
    status: StatusOut

    @model_validator(mode="after")
    def _kind_fields(self) -> "SourceOut":
        # Output only: Loki settings are withheld from non-admins, so the input rule that
        # a Loki source carries them does not apply here.
        return self


class SourceSettings(BaseModel):
    allowed_roots: list[str]


def _status_out(source: SourceConfig, st: SourceStatus | None) -> StatusOut:
    state = source_state(source.enabled, st)
    st = st or SourceStatus()
    return StatusOut(
        state=state,
        files=st.files,
        last_pass_at=st.last_pass_at,
        last_event_at=st.last_event_at,
        events_since_start=st.events_since_start,
        error=st.error,
        records_skipped=st.records_skipped,
        files_waiting=st.files_waiting,
        behind_s=st.behind_s,
    )


@router.get("/sources")
async def list_sources(request: Request, user: CurrentUser) -> list[SourceOut]:
    sources = await run_in_threadpool(_store(request).list)
    meta: MetaDB = request.app.state.meta
    allowed = await run_in_threadpool(permitted_sources, meta, user)
    admin = allowed is None
    if not admin:  # non-admins see only sources their groups grant
        sources = [s for s in sources if s.source_id in set(allowed or [])]
    ingest: IngestService = request.app.state.ingest
    statuses = ingest.status()
    out = [
        SourceOut(**s.model_dump(), status=_status_out(s, statuses.get(s.source_id)))
        for s in sources
    ]
    if not admin:
        # The server's folder layout is for administrators only.
        for item in out:
            item.path = ""
            item.loki = None  # the Loki address and query are for administrators too
            if item.status.error:
                item.status.error = (
                    "This source cannot be read right now. An administrator can see why."
                )
    return out


@router.get("/sources/settings")
async def source_settings(request: Request, _: AdminUser) -> SourceSettings:
    # Folder layout of the server is for administrators only.
    return SourceSettings(allowed_roots=[str(p) for p in _store(request).allowed_roots])


class SourceCreate(SourceConfig):
    # A Loki password or token (ADR-0011): stored encrypted, never returned or logged.
    loki_secret: SecretStr | None = Field(default=None, max_length=4096)


@router.post("/sources", status_code=status.HTTP_201_CREATED)
async def add_source(body: SourceCreate, request: Request, user: AdminUser) -> SourceConfig:
    store = _store(request)
    config = SourceConfig(**body.model_dump(exclude={"loki_secret"}))
    secret = body.loki_secret.get_secret_value() if body.loki_secret else None
    if config.template_id in (None, AUTO_PARSER):
        created = await run_in_threadpool(store.add, config, secret)
    else:
        # Checked and added under the template lock, so the template cannot be deleted in
        # between (a source must never fall back to a parser silently).
        drafts: DraftStore = request.app.state.drafts
        tid = config.template_id
        created = await run_in_threadpool(
            drafts.with_template, tid, lambda: store.add(config, secret)
        )
    await run_in_threadpool(
        _audit(request).audit.write,
        "source.create",
        "success",
        user.user_id,
        client_ip(request),
        {**config.model_dump(), "has_loki_secret": secret is not None},
    )
    return created


class LokiTest(LokiSettings):
    secret: SecretStr | None = Field(default=None, max_length=4096)


class LokiTestOut(BaseModel):
    lines: int  # lines in the last hour, up to 100
    streams: list[dict[str, str]]  # label sets that matched, up to 20
    newest: str | None


@router.post("/sources/loki/test")
async def test_loki(body: LokiTest, request: Request, user: AdminUser) -> LokiTestOut:
    """One small query with these settings, before a Loki source is saved (ADR-0011)."""
    settings = LokiSettings(**body.model_dump(exclude={"secret"}))
    secret = body.secret.get_secret_value() if body.secret else None
    ingest: IngestService = request.app.state.ingest
    client = ingest.loki_client(settings, secret)
    now = request.app.state.auth.clock()
    outcome: Literal["success", "failure"] = "failure"
    try:
        out = await run_in_threadpool(loki_test, client, now)
        outcome = "success"
    finally:
        await run_in_threadpool(
            _audit(request).audit.write,
            "source.loki_test",
            outcome,
            user.user_id,
            client_ip(request),
            {"url": settings.url, "query": settings.query, "auth": settings.auth},
        )
    return LokiTestOut(**out)


class DiscoverIn(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


def _discover_locked(path: str, roots: list[Path], registry: TemplateRegistry) -> DiscoveryReport:
    # Held by the worker thread itself, so a cancelled request cannot release it while
    # the scan is still running.
    if not _discovery_running.acquire(blocking=False):
        raise RateLimitedError("A folder scan is already running", retry_after_s=5)
    try:
        return discover(path, roots, registry.all(), registry.tables)
    finally:
        _discovery_running.release()


@router.post("/sources/discover")
async def discover_sources(body: DiscoverIn, request: Request, user: AdminUser) -> DiscoveryReport:
    """Suggest sources for a folder. Reads files only: creates and grants nothing."""
    registry: TemplateRegistry = request.app.state.templates
    detail: dict[str, object] = {"path": body.path[:500]}
    try:
        report = await run_in_threadpool(
            _discover_locked, body.path, _store(request).allowed_roots, registry
        )
    except Exception as exc:
        outcome: Literal["denied", "failure"] = (
            "denied" if isinstance(exc, RateLimitedError) else "failure"
        )
        await run_in_threadpool(
            _audit(request).audit.write,
            "source.discover",
            outcome,
            user.user_id,
            client_ip(request),
            detail,
        )
        raise
    detail.update(root=report.root, candidates=len(report.candidates))
    await run_in_threadpool(
        _audit(request).audit.write,
        "source.discover",
        "success",
        user.user_id,
        client_ip(request),
        detail,
    )
    return report


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(source_id: str, request: Request, user: AdminUser) -> Response:
    if not await run_in_threadpool(_store(request).delete, source_id):
        raise NotFoundError(f"No source named {source_id}")
    await run_in_threadpool(
        _audit(request).audit.write,
        "source.delete",
        "success",
        user.user_id,
        client_ip(request),
        {"source_id": source_id},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class SourcePatch(BaseModel):
    # Either or both. template_id null is the generic parser, `auto` the Automatic one.
    classification: Literal["local_only", "cloud_allowed"] | None = None
    template_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{1,63}$")

    @model_validator(mode="after")
    def _something(self) -> "SourcePatch":
        if not self.model_fields_set & {"classification", "template_id"}:
            raise ValueError("Nothing to change")
        if "classification" in self.model_fields_set and self.classification is None:
            raise ValueError("classification cannot be empty")
        return self


@router.patch("/sources/{source_id}")
async def update_source(
    source_id: str, body: SourcePatch, request: Request, user: AdminUser
) -> SourceConfig:
    """Change a source's classification (SPEC 6.2) or parser (ADR-0012). Only new events
    take either: events already stored keep their label, so relabelling never releases
    older data (T8), and keep the parser they were read with."""
    store = _store(request)
    source: SourceConfig | None = None
    if "template_id" in body.model_fields_set:
        tid = body.template_id

        def change() -> tuple[str | None, SourceConfig]:
            return store.set_parser(source_id, tid)

        if tid in (None, AUTO_PARSER):
            before_tid, source = await run_in_threadpool(change)
        else:
            # Under the template lock, as when adding a source: the template cannot be
            # deleted between the check and the change.
            drafts: DraftStore = request.app.state.drafts
            before_tid, source = await run_in_threadpool(drafts.with_template, tid, change)
        await run_in_threadpool(
            _audit(request).audit.write,
            "source.parser_change",
            "success",
            user.user_id,
            client_ip(request),
            {"source_id": source_id, "from": before_tid, "to": tid},
        )
    if body.classification is not None:
        before, source = await run_in_threadpool(
            store.set_classification, source_id, body.classification
        )
        await run_in_threadpool(
            _audit(request).audit.write,
            "source.classify",
            "success",
            user.user_id,
            client_ip(request),
            {"source_id": source_id, "from": before, "to": body.classification},
        )
    assert source is not None  # the validator requires at least one change
    return source
