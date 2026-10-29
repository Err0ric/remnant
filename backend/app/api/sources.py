"""/api/sources: list, add, and remove file sources. Router only."""

import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import PlainTextResponse
from pydantic import (
    BaseModel,
    Field,
    SecretStr,
    StringConstraints,
    ValidationError,
    model_validator,
)
from starlette.concurrency import run_in_threadpool

from app.ai.claude_plugin import SCRIPT_SHA256
from app.ai.claude_plugin import VERSION as PLUGIN_VERSION
from app.ai.claude_plugin import build_managed as build_plugin_bundle
from app.ai.claude_plugin import build_zip as build_plugin_zip
from app.alerts.dispatch import AlertDispatcher
from app.api.access import AdminUser, CurrentUser, client_ip
from app.api.schedules import DeliveryOut
from app.auth.service import AuthService
from app.auth.tls import resolve_tls
from app.core.branding import PRODUCT_NAME
from app.core.errors import (
    ConfigError,
    NotFoundError,
    ParamInvalidError,
    RateLimitedError,
    SourceRejectedError,
)
from app.core.ids import AUTO_PARSER
from app.engine.views import permitted_sources
from app.ingest.agent import AgentOs
from app.ingest.agent import render as render_agent
from app.ingest.connectors.anthropic import AnthropicSettings
from app.ingest.connectors.base import ConnectorError
from app.ingest.connectors.loki import LokiSettings
from app.ingest.connectors.loki import test_connection as loki_test
from app.ingest.connectors.m365 import M365Settings, check_certificate
from app.ingest.connectors.registry import API_KINDS, probe, secret_text
from app.ingest.discovery import DiscoveryReport, discover
from app.ingest.listener import ListenerStatus, SyslogListeners
from app.ingest.quiet import MAX_QUIET_S, MIN_QUIET_S, QuietWatch, Watch, default_quiet_s
from app.ingest.skew import skew_text
from app.ingest.sources import SourceConfig, SourceStore, spool_dir
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


class SenderOut(BaseModel):
    address: str
    count: int
    last_seen: datetime | None
    allowed: bool


class ListenerOut(BaseModel):
    """A syslog listener source's socket (ADR-0021). Senders are for administrators."""

    protocol: str
    port: int
    listening: bool
    received: int
    dropped_not_allowed: int
    dropped_full: int
    connections: int
    last_message_at: datetime | None
    senders: list[SenderOut] = []


class StatusOut(BaseModel):
    state: Literal["waiting", "reading", "error", "disabled"]
    files: int
    last_pass_at: datetime | None
    last_event_at: datetime | None
    events_since_start: int
    error: str | None
    records_skipped: int
    files_waiting: int
    behind_s: float | None = None  # Loki and API sources: how far reading is behind now
    warnings: list[str] = []  # API sources: feeds that failed while others worked
    retry_at: datetime | None = None  # API sources: next try after errors
    listener: ListenerOut | None = None  # syslog listener sources
    # Event times steadily this many hours off (positive: early): check the time zone.
    time_offset_h: float | None = None
    time_offset_text: str | None = None


class QuietOut(BaseModel):
    """Quiet-source alert state (ADR-0014). Targets are on the admin-only watch list."""

    quiet_after_s: int
    state: Literal["ok", "quiet"]
    quiet_since: str | None
    last_seen: str | None


class SourceOut(SourceConfig):
    status: StatusOut
    quiet: QuietOut | None = None

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
        warnings=list(st.warnings),
        retry_at=st.retry_at,
        time_offset_h=st.time_offset_h,
        time_offset_text=skew_text(st.time_offset_h) if st.time_offset_h else None,
    )


def _listener_out(st: ListenerStatus) -> ListenerOut:
    senders = sorted(st.senders.items(), key=lambda kv: -kv[1].count)[:50]
    return ListenerOut(
        protocol=st.protocol,
        port=st.port,
        listening=st.listening,
        received=st.received,
        dropped_not_allowed=st.dropped_not_allowed,
        dropped_full=st.dropped_full,
        connections=st.connections,
        last_message_at=st.last_message_at,
        senders=[
            SenderOut(address=a, count=v.count, last_seen=v.last_seen, allowed=v.allowed)
            for a, v in senders
        ],
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
    watches = {w.source_id: w for w in await run_in_threadpool(_quiet(request).all)}
    listeners: SyslogListeners = request.app.state.listeners
    sockets = listeners.status()
    out = [
        SourceOut(
            **s.model_dump(),
            status=_status_out(s, statuses.get(s.source_id)),
            quiet=_quiet_out(watches.get(s.source_id)),
        )
        for s in sources
    ]
    for item in out:
        sock = sockets.get(item.source_id) if item.kind == "syslog" else None
        if sock is not None:
            item.status.listener = _listener_out(sock)
    if not admin:
        # The server's folder layout is for administrators only.
        for item in out:
            item.path = ""
            item.loki = None  # the Loki address and query are for administrators too
            item.m365 = item.anthropic = None  # tenant and app ids likewise
            item.status.warnings = []
            if item.status.listener is not None:
                item.status.listener.senders = []  # addresses on the network: admins only
            if item.status.error:
                item.status.error = (
                    "This source cannot be read right now. An administrator can see why."
                )
    return out


@router.get("/sources/settings")
async def source_settings(request: Request, _: AdminUser) -> SourceSettings:
    # Folder layout of the server is for administrators only.
    return SourceSettings(allowed_roots=[str(p) for p in _store(request).allowed_roots])


class ApiCredentials(BaseModel):
    """Credentials for an API source: stored encrypted, never returned or logged.
    Anthropic: api_key. Microsoft 365: certificate_pem and private_key_pem, or
    client_secret, matching the source's auth setting."""

    api_key: SecretStr | None = Field(default=None, max_length=512)
    client_secret: SecretStr | None = Field(default=None, max_length=512)
    certificate_pem: str | None = Field(default=None, max_length=16384)
    private_key_pem: SecretStr | None = Field(default=None, max_length=16384)

    def secret_for(self, source: SourceConfig) -> str:
        if source.kind not in API_KINDS:
            raise SourceRejectedError("Credentials of this kind are for API sources")
        try:
            return secret_text(
                source.kind,
                api_key=_plain(self.api_key),
                client_secret=_plain(self.client_secret),
                certificate_pem=self.certificate_pem,
                private_key_pem=_plain(self.private_key_pem),
                auth=source.m365.auth if source.m365 else "certificate",
            )
        except ConnectorError as exc:
            raise SourceRejectedError(str(exc)) from None


def _plain(value: SecretStr | None) -> str | None:
    return value.get_secret_value() if value else None


class SourceCreate(SourceConfig):
    # A Loki password or token (ADR-0011): stored encrypted, never returned or logged.
    loki_secret: SecretStr | None = Field(default=None, max_length=4096)
    credentials: ApiCredentials | None = None  # m365 and anthropic sources


class SourceCreated(SourceConfig):
    # OTLP sources: the ingest token, shown this once (ADR-0015 row 3).
    otlp_token: str | None = None


@router.post("/sources", status_code=status.HTTP_201_CREATED)
async def add_source(body: SourceCreate, request: Request, user: AdminUser) -> SourceCreated:
    store = _store(request)
    config = SourceConfig(**body.model_dump(exclude={"loki_secret", "credentials"}))
    secret = body.loki_secret.get_secret_value() if body.loki_secret else None
    if config.kind in API_KINDS:
        secret = (body.credentials or ApiCredentials()).secret_for(config)
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
    token = None
    if created.kind == "otlp":
        token = await run_in_threadpool(store.issue_otlp_token, created.source_id)
    await run_in_threadpool(
        _audit(request).audit.write,
        "source.create",
        "success",
        user.user_id,
        client_ip(request),
        {**config.model_dump(), "has_secret": secret is not None},
    )
    # Alert if quiet starts on, with no targets: a gap becomes an alert item, and messages
    # go out once an admin adds targets (ADR-0037). Audited as source.quiet_alert_change.
    await run_in_threadpool(
        _quiet(request).set,
        created.source_id,
        default_quiet_s(created.kind or "file"),
        [],
        user,
        client_ip(request),
    )
    return SourceCreated(**created.model_dump(), otlp_token=token)


@router.get("/sources/{source_id}/agent-config")
async def agent_config(
    source_id: str,
    request: Request,
    user: AdminUser,
    os: AgentOs = "windows",
    # The name in the server's certificate, when agents connect by address (self-signed).
    server_name: Annotated[
        str | None,
        Query(max_length=253, pattern=r"^[A-Za-z0-9]([A-Za-z0-9-]{0,62})(\.[A-Za-z0-9-]{1,63})*$"),
    ] = None,
) -> PlainTextResponse:
    """OpenTelemetry Collector config for an agent group (ADR-0017 row 2). Holds no secret:
    the token is read from a file on the endpoint. Audited source.agent_config."""
    found = [s for s in await run_in_threadpool(_store(request).list) if s.source_id == source_id]
    if not found:
        raise NotFoundError("No such source")
    if found[0].kind != "otlp":
        raise SourceRejectedError("Agent configs are for OTLP sources")
    base = request.app.state.public_url or str(request.base_url).rstrip("/")
    text = render_agent(os, f"{base}/api/otlp", source_id, PRODUCT_NAME, server_name)
    await run_in_threadpool(
        _audit(request).audit.write,
        "source.agent_config",
        "success",
        user.user_id,
        client_ip(request),
        {"source_id": source_id, "os": os, "server_name": server_name},
    )
    name = f"{PRODUCT_NAME.lower()}-agent-{source_id}-{os}.yaml"
    return PlainTextResponse(
        text,
        media_type="application/yaml",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


class OtlpToken(BaseModel):
    token: str


# The hooks plugin (ADR-0026). A pilot user is an email or an OS user name.
PilotUser = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9._%+@\\-]{1,254}$")
]


class ClaudePluginIn(BaseModel):
    # Only these people send while the plugin rolls out (empty: everyone who has it).
    pilot_users: list[PilotUser] = Field(default_factory=list, max_length=200)
    # Where the plugin sends: the address people's machines reach this server at. Fixed in
    # the plugin; nothing on the machine or in a session can change it.
    server_url: str | None = Field(default=None, max_length=300)
    # One plugin per platform (ADR-0026 amendment 2026-10-29 row 3).
    platform: Literal["windows", "posix"] = "posix"
    # A bundle for endpoint management: the plugin plus the machine-wide hooks.conf that
    # wins over the plugin's own copy (row 7). Off: the plugin's own config holds it all.
    managed: bool = False
    # Bundle this server's certificate when it is the generated self-signed one, so the
    # scripts check the server against it (row 16). Never a switch to skip checking.
    trust_server_certificate: bool = True


class ClaudePluginInfo(BaseModel):
    version: str
    script_sha256: str  # the macOS and Linux script, as before
    scripts: dict[str, str]  # platform -> SHA-256 of its script
    self_signed: bool  # this server serves its generated self-signed certificate


@router.get("/sources/claude-plugin")
async def claude_plugin_info(request: Request, _: AdminUser) -> ClaudePluginInfo:
    """The hooks plugins' version and the SHA-256 of each script, to check a copy against."""
    return ClaudePluginInfo(
        version=PLUGIN_VERSION,
        script_sha256=SCRIPT_SHA256["posix"],
        scripts=dict(SCRIPT_SHA256),
        self_signed=_self_signed_pem(request) is not None,
    )


def _self_signed_pem(request: Request) -> bytes | None:
    """This server's certificate when it is the generated self-signed one (public)."""
    try:
        tls = resolve_tls(request.app.state.config)
    except ConfigError:
        return None
    if tls is None or not tls.self_signed:
        return None
    return tls.cert.read_bytes()


def _plugin_url(raw: str) -> str:
    parts = urlsplit(raw.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("https", "http") or not host or parts.query or parts.fragment:
        raise ParamInvalidError("Give the server address, for example https://siem.example:8080")
    if parts.username or parts.password:
        raise ParamInvalidError("The address cannot hold a user name or password")
    if parts.scheme == "http" and host not in ("127.0.0.1", "localhost", "::1"):
        raise ParamInvalidError("Use https: the token travels with every record")
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


@router.post("/sources/{source_id}/claude-plugin")
async def claude_plugin(
    source_id: str, body: ClaudePluginIn, request: Request, user: AdminUser
) -> Response:
    """The hooks plugin for this OTLP source as a zip: server address, a new token for the
    source (earlier copies stop sending), content on only when the source keeps content,
    and the pilot list. Audited source.claude_plugin (never the token)."""
    store = _store(request)
    found = [s for s in await run_in_threadpool(store.list) if s.source_id == source_id]
    if not found:
        raise NotFoundError("No such source")
    if found[0].kind != "otlp":
        raise SourceRejectedError("The Claude plugin sends to an OTLP source")
    base = body.server_url or request.app.state.public_url
    if not base:
        raise ParamInvalidError("Give the address people's machines reach this server at")
    url = _plugin_url(base)
    send_content = bool(found[0].otlp_keep_content)
    ca = _self_signed_pem(request) if body.trust_server_certificate else None
    token = await run_in_threadpool(store.issue_otlp_token, source_id)
    if body.managed:
        data = build_plugin_bundle(url, token, send_content, body.pilot_users, body.platform, ca)
    else:
        data = build_plugin_zip(url, token, send_content, body.pilot_users, body.platform, ca)
    sha = SCRIPT_SHA256[body.platform]
    await run_in_threadpool(
        _audit(request).audit.write,
        "source.claude_plugin",
        "success",
        user.user_id,
        client_ip(request),
        {
            "source_id": source_id,
            "server_url": url,
            "send_content": send_content,
            "pilot_users": body.pilot_users,
            "version": PLUGIN_VERSION,
            "platform": body.platform,
            "managed": body.managed,
            "server_certificate": ca is not None,
            "script_sha256": sha,
        },
    )
    kind = "managed" if body.managed else "plugin"
    name = f"{PRODUCT_NAME.lower()}-claude-hooks-{body.platform}-{kind}-{source_id}.zip"
    return Response(
        data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Script-Sha256": sha,
            "Cache-Control": "no-store",
        },
    )


@router.post("/sources/{source_id}/otlp-token")
async def rotate_otlp_token(source_id: str, request: Request, user: AdminUser) -> OtlpToken:
    """A new ingest token for an OTLP source; the old one stops working at once. Shown
    once, stored hashed, audited source.otlp_token (never the token)."""
    token = await run_in_threadpool(_store(request).issue_otlp_token, source_id)
    await run_in_threadpool(
        _audit(request).audit.write,
        "source.otlp_token",
        "success",
        user.user_id,
        client_ip(request),
        {"source_id": source_id},
    )
    return OtlpToken(token=token)


class LokiTest(LokiSettings):
    secret: SecretStr | None = Field(default=None, max_length=4096)


class LokiStreamGroup(BaseModel):
    labels: dict[str, str]
    streams: int  # streams with these labels, apart from per-id labels


class LokiTestOut(BaseModel):
    lines: int  # lines in the last hour, up to 100
    stream_count: int  # distinct streams among those lines
    groups: list[LokiStreamGroup]  # up to 20, largest first
    ignored_labels: list[str]  # per-id labels left out of the grouping (proc_id, pid, ...)
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


class ApiTest(BaseModel):
    """Settings and credentials to try before an API source is saved."""

    kind: Literal["m365", "anthropic"]
    m365: M365Settings | None = None
    anthropic: AnthropicSettings | None = None
    credentials: ApiCredentials = ApiCredentials()


class ApiTestOut(BaseModel):
    feeds: dict[str, str]  # feed -> "ok" or why it failed
    thumbprint: str | None = None  # Microsoft 365 certificates: the value Entra shows


def _api_source(kind: Literal["m365", "anthropic"], body: ApiTest) -> SourceConfig:
    try:
        return SourceConfig(
            source_id="connection_test",
            format="json",
            kind=kind,
            m365=body.m365 if kind == "m365" else None,
            anthropic=body.anthropic if kind == "anthropic" else None,
        )
    except ValidationError as exc:
        msg = str(exc.errors()[0]["msg"]).removeprefix("Value error, ")
        raise SourceRejectedError(msg) from None


@router.post("/sources/api/test")
async def test_api(body: ApiTest, request: Request, user: AdminUser) -> ApiTestOut:
    """One small read per enabled feed with these settings, before the source is saved.
    Audited source.api_test with the kind and feeds, never the credentials."""
    config = _api_source(body.kind, body)
    secret = body.credentials.secret_for(config)
    ingest: IngestService = request.app.state.ingest
    now = request.app.state.auth.clock()
    settings = config.m365 or config.anthropic
    if settings is None:
        raise SourceRejectedError(f"Give the {body.kind} settings")
    thumb = None
    if body.credentials.certificate_pem and body.credentials.private_key_pem:
        thumb = check_certificate(
            body.credentials.certificate_pem, body.credentials.private_key_pem.get_secret_value()
        )
    outcome: Literal["success", "failure"] = "failure"
    try:
        feeds = await run_in_threadpool(
            probe, body.kind, settings, secret, now, ingest.api_transport
        )
        outcome = (
            "success" if feeds and all(v.startswith("ok") for v in feeds.values()) else "failure"
        )
    except ConnectorError as exc:
        raise SourceRejectedError(str(exc)) from None
    finally:
        await run_in_threadpool(
            _audit(request).audit.write,
            "source.api_test",
            outcome,
            user.user_id,
            client_ip(request),
            {"kind": body.kind, **settings.model_dump()},
        )
    return ApiTestOut(feeds=feeds, thumbprint=thumb)


@router.put("/sources/{source_id}/credentials", status_code=status.HTTP_204_NO_CONTENT)
async def replace_credentials(
    source_id: str, body: ApiCredentials, request: Request, user: AdminUser
) -> Response:
    """Replace an API source's credentials (a renewed certificate or a new key). Reading
    continues from the saved position. Audited source.credentials, never the values."""
    store = _store(request)
    found = [s for s in await run_in_threadpool(store.list) if s.source_id == source_id]
    if not found:
        raise NotFoundError("No such source")
    secret = body.secret_for(found[0])
    await run_in_threadpool(store.set_connector_secret, source_id, secret)
    await run_in_threadpool(
        _audit(request).audit.write,
        "source.credentials",
        "success",
        user.user_id,
        client_ip(request),
        {"source_id": source_id},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    store = _store(request)
    if not await run_in_threadpool(store.delete, source_id):
        raise NotFoundError(f"No source named {source_id}")
    if store.spool_root is not None:  # records not yet read go with the source
        await run_in_threadpool(
            shutil.rmtree, spool_dir(store.spool_root, source_id), ignore_errors=True
        )
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
    # OTLP sources: keep prompt and tool content (ADR-0015 row 4).
    otlp_keep_content: bool | None = None
    # Loki sources: which stream labels stand in for the syslog header (docs/ingest/loki.md).
    loki_label_map: (
        dict[Literal["hostname", "app_name", "procid", "severity", "facility"], list[str]] | None
    ) = None
    # The zone for times that carry none (RFC 3164 headers, Palo Alto Generated Time).
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    # Days to keep; the nightly retention job applies it (install finding F44).
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    # API and Loki settings that do not depend on the stored credential (F44): feeds,
    # first-run history, the Loki query. Only the keys given change.
    connector: dict[str, Any] | None = Field(default=None, max_length=5)

    @model_validator(mode="after")
    def _something(self) -> "SourcePatch":
        if not self.model_fields_set & {
            "classification",
            "template_id",
            "otlp_keep_content",
            "loki_label_map",
            "timezone",
            "retention_days",
            "connector",
        }:
            raise ValueError("Nothing to change")
        if "otlp_keep_content" in self.model_fields_set and self.otlp_keep_content is None:
            raise ValueError("otlp_keep_content cannot be empty")
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
    if body.otlp_keep_content is not None:
        keep = body.otlp_keep_content
        before_keep, source = await run_in_threadpool(store.set_keep_content, source_id, keep)
        await run_in_threadpool(
            _audit(request).audit.write,
            "source.otlp_content",
            "success",
            user.user_id,
            client_ip(request),
            {"source_id": source_id, "from": before_keep, "to": keep},
        )
    if body.loki_label_map is not None:
        new_map = {str(k): v for k, v in body.loki_label_map.items()}
        before_map, source = await run_in_threadpool(store.set_loki_label_map, source_id, new_map)
        await run_in_threadpool(
            _audit(request).audit.write,
            "source.loki_label_map",
            "success",
            user.user_id,
            client_ip(request),
            {"source_id": source_id, "from": before_map, "to": new_map},
        )
    if body.timezone is not None:
        try:
            before_tz, source = await run_in_threadpool(
                store.set_timezone, source_id, body.timezone
            )
        except ValueError as exc:
            raise ParamInvalidError(f"Unknown time zone {body.timezone!r}") from exc
        request.app.state.ingest.skew.forget(source_id)
        await run_in_threadpool(
            _audit(request).audit.write,
            "source.timezone",
            "success",
            user.user_id,
            client_ip(request),
            {"source_id": source_id, "from": before_tz, "to": body.timezone},
        )
    if body.retention_days is not None:
        days = body.retention_days
        before_days, source = await run_in_threadpool(store.set_retention, source_id, days)
        await run_in_threadpool(
            _audit(request).audit.write,
            "source.retention_change",
            "success",
            user.user_id,
            client_ip(request),
            {"source_id": source_id, "from": before_days, "to": days},
        )
    if body.connector is not None:
        changes = body.connector
        old, new, source = await run_in_threadpool(store.set_connector_settings, source_id, changes)
        await run_in_threadpool(
            _audit(request).audit.write,
            "source.settings_change",
            "success",
            user.user_id,
            client_ip(request),
            {"source_id": source_id, "from": old, "to": new},
        )
    assert source is not None  # the validator requires at least one change
    return source


# --- quiet-source alerts (ADR-0014) --------------------------------------------------------


def _quiet(request: Request) -> QuietWatch:
    quiet: QuietWatch = request.app.state.quiet
    return quiet


def _quiet_out(w: Watch | None) -> QuietOut | None:
    if w is None:
        return None
    return QuietOut(
        quiet_after_s=w.quiet_after_s,
        state="quiet" if w.state == "quiet" else "ok",
        quiet_since=w.quiet_since,
        last_seen=w.last_seen,
    )


class WatchOut(QuietOut):
    source_id: str
    target_ids: list[str]
    updated_at: str
    updated_by: str | None


class WatchIn(BaseModel):
    # null turns the alert off for this source.
    quiet_after_s: int | None = Field(ge=MIN_QUIET_S, le=MAX_QUIET_S)
    target_ids: list[str] = Field(default_factory=list, max_length=10)


def _watch_out(w: Watch) -> WatchOut:
    base = _quiet_out(w)
    assert base is not None
    return WatchOut(
        **base.model_dump(),
        source_id=w.source_id,
        target_ids=w.target_ids,
        updated_at=w.updated_at,
        updated_by=w.updated_by,
    )


@router.get("/sources/watches")
async def list_watches(request: Request, _: AdminUser) -> list[WatchOut]:
    """Every source's quiet alert setting, with its targets."""
    return [_watch_out(w) for w in await run_in_threadpool(_quiet(request).all)]


@router.put("/sources/{source_id}/watch")
async def set_watch(
    source_id: str, body: WatchIn, request: Request, user: AdminUser
) -> WatchOut | None:
    """Alert when this source receives nothing for `quiet_after_s`; null turns it off.
    Audited as source.quiet_alert_change with the old and new setting."""
    w = await run_in_threadpool(
        _quiet(request).set,
        source_id,
        body.quiet_after_s,
        body.target_ids,
        user,
        client_ip(request),
    )
    return _watch_out(w) if w else None


@router.get("/sources/{source_id}/deliveries")
async def watch_deliveries(source_id: str, request: Request, _: AdminUser) -> list[DeliveryOut]:
    """Quiet and resumed alerts sent for this source, newest first (no message content)."""
    dispatcher: AlertDispatcher = request.app.state.alert_dispatcher
    rows = await run_in_threadpool(lambda: dispatcher.deliveries(source_id=source_id, limit=50))
    return [
        DeliveryOut(
            delivery_id=d.delivery_id,
            target_name=d.target_name,
            kind=d.kind,
            status=d.status,
            attempts=d.attempts,
            next_attempt_at=d.next_attempt_at,
            last_error=d.last_error,
            created_at=d.created_at,
            sent_at=d.sent_at,
        )
        for d in rows
    ]
