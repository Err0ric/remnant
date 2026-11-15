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
from app.alerts.external_cap import ExternalAlertSettings, Level, Notify, Pause
from app.alerts.fallback import SourceFallbacks
from app.api.access import AdminUser, CurrentUser, client_ip
from app.api.schedules import DeliveryOut
from app.auth.service import AuthService
from app.auth.tls import resolve_tls
from app.core import clock
from app.core.branding import PRODUCT_NAME
from app.core.errors import (
    ConfigError,
    NotFoundError,
    ParamInvalidError,
    RateLimitedError,
    SourceRejectedError,
)
from app.core.ids import AUTO_PARSER
from app.detect.reparse_rules import ReparseRules, RuleFailure
from app.engine.views import permitted_sources
from app.ingest.agent import AgentOs
from app.ingest.agent import render as render_agent
from app.ingest.connectors.anthropic import AnthropicSettings
from app.ingest.connectors.base import ConnectorError
from app.ingest.connectors.loki import LokiSettings
from app.ingest.connectors.loki import test_connection as loki_test
from app.ingest.connectors.m365 import M365Settings, check_certificate
from app.ingest.connectors.proxmox import ProxmoxSettings
from app.ingest.connectors.registry import API_KINDS, check_on_save, probe, secret_text
from app.ingest.discovery import DiscoveryReport, discover
from app.ingest.listener import ListenerStatus, SyslogListeners
from app.ingest.quiet import MAX_QUIET_S, MIN_QUIET_S, QuietWatch, Watch, default_quiet_s
from app.ingest.reparse import ReparseJob, ReparseJobs
from app.ingest.skew import skew_text
from app.ingest.sources import (
    CLAUDE_QUIET_OK_DAYS,
    QuietOkDays,
    SourceConfig,
    SourceStore,
    built_in,
    quiet_expected,
    spool_dir,
)
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


class AlertPauseOut(BaseModel):
    """A vendor alert source over its hourly cap (D231): alerts below High are held."""

    paused_since: str
    held: dict[str, int]


JobState = Literal["running", "done", "failed", "interrupted"]
RulesState = Literal["running", "done", "partial", "failed", "interrupted"]


class ReparseRuleFailedOut(BaseModel):
    rule_id: str
    title: str
    error: str


class ReparseLastOut(BaseModel):
    """A source's latest reparse job, on the source list (administrators only)."""

    job_id: str
    state: JobState
    finished_at: str | None
    rows_rewritten: int
    time_min: str | None
    time_max: str | None
    rules_state: RulesState | None
    rules_run_at: str | None
    rules_finished_at: str | None
    rules_count: int
    rules_matched: int
    rules_items: int
    rules_error: str | None
    rules_failed: list[ReparseRuleFailedOut]  # when partial: the rules to run again
    # The rule re-run is offered or was started: a done job, or a stopped one that rewrote
    # the last waiting rows (no later reparse would take its events over).
    rules_ready: bool = False


class SourceOut(SourceConfig):
    status: StatusOut
    quiet: QuietOut | None = None
    # Server-set: the source's template sends vendor alerts (ADR-0049), and its cap pause.
    emits_alerts: bool = False
    alert_pause: AlertPauseOut | None = None
    # Server-set, never accepted on input: a built-in source, and one with events only when
    # someone uses or probes the server, so its quiet is expected (handoff items 4 and 9).
    built_in: bool = False
    quiet_expected: bool = False
    # Server-set, administrators only: events stored while the template was missing wait
    # for a reparse and the template loads now (ADR-0050 row 7). From the fallback table,
    # without reading the lake; the exact count is GET /sources/{id}/reparse.
    reparse_pending: bool = False
    # Server-set, administrators only: the source's latest reparse job, from reparse_jobs
    # only, so the rule re-run over its range stays reachable once the fallback row is gone.
    reparse_last: ReparseLastOut | None = None

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
    pauses = await run_in_threadpool(_vendor(request).pauses)
    alerting = {t.id for t in request.app.state.templates.all() if t.emits == "alerts"}
    listeners: SyslogListeners = request.app.state.listeners
    sockets = listeners.status()
    offers = await run_in_threadpool(_reparse_offers, request) if admin else {}
    jobs, failed, ready = (
        await run_in_threadpool(_latest_jobs, request, sources) if admin else ({}, {}, set())
    )
    out = [
        SourceOut(
            **s.model_dump(),
            status=_status_out(s, statuses.get(s.source_id)),
            quiet=_quiet_out(watches.get(s.source_id)),
            emits_alerts=s.template_id in alerting,
            alert_pause=_pause_out(pauses.get(s.source_id)),
            built_in=built_in(s),
            quiet_expected=quiet_expected(s),
            reparse_pending=s.template_id is not None and offers.get(s.source_id) == s.template_id,
            reparse_last=_last_out(jobs.get(s.source_id), failed, ready),
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
            item.proxmox = None  # the hypervisor's address and token id likewise
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
    client_secret, matching the source's auth setting. Proxmox: token_secret."""

    api_key: SecretStr | None = Field(default=None, max_length=512)
    token_secret: SecretStr | None = Field(default=None, max_length=64)
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
                token_secret=_plain(self.token_secret),
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
    # OTLP sources: who sends (owner 2026-11-02). Claude Code telemetry and the hooks plugin
    # send only while people use Claude Code, so their source-level quiet alert starts off;
    # collectors and endpoint agents send all the time, so theirs starts on.
    sender: Literal["claude", "collector"] | None = None


class SourceCreated(SourceConfig):
    # OTLP sources: the ingest token, shown this once (ADR-0015 row 3).
    otlp_token: str | None = None


CLAUDE_TEMPLATES = ("claude_hooks", "claude_code_otel")


def claude_source(source: SourceConfig, sender: str | None) -> bool:
    """Claude Code telemetry or the hooks plugin: they send only while people use it."""
    return source.kind == "otlp" and (sender == "claude" or source.template_id in CLAUDE_TEMPLATES)


def quiet_off_by_default(source: SourceConfig, sender: str | None) -> bool:
    """Claude Code telemetry and hooks sources, and the Proxmox inventory, start with no
    source-level quiet alert."""
    if source.kind == "proxmox":
        return True  # writes only on a change, plus one heartbeat a day (ADR-0045 A3b)
    return claude_source(source, sender)


@router.post("/sources", status_code=status.HTTP_201_CREATED)
async def add_source(body: SourceCreate, request: Request, user: AdminUser) -> SourceCreated:
    store = _store(request)
    config = SourceConfig(**body.model_dump(exclude={"loki_secret", "credentials", "sender"}))
    if "quiet_ok_days" not in body.model_fields_set and claude_source(config, body.sender):
        config.quiet_ok_days = CLAUDE_QUIET_OK_DAYS  # quiet is normal for a week (D260)
    secret = body.loki_secret.get_secret_value() if body.loki_secret else None
    if config.kind in API_KINDS:
        secret = (body.credentials or ApiCredentials()).secret_for(config)
        await _check_token(request, config, secret)
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
    # Not for Claude Code sources: no records overnight is normal (D166); Health watches
    # each device's queue instead.
    if not quiet_off_by_default(created, body.sender):
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
    # The named token the package carries (D127): an existing one by id, or a new one
    # with this name. Earlier packages keep sending until their token is revoked.
    token_id: str | None = Field(default=None, max_length=64)
    token_name: str | None = Field(default=None, min_length=1, max_length=80)


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
    """The hooks plugin for this OTLP source as a zip: server address, a named token (an
    existing one, or a new one: earlier packages keep sending until theirs is revoked),
    content on only when the source keeps content, and the pilot list. Audited
    source.claude_plugin with the token id and name (never the token)."""
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
    tokens = request.app.state.otlp_tokens
    if body.token_id:
        owner, token = await run_in_threadpool(tokens.plain, body.token_id)
        if owner != source_id:
            raise NotFoundError("No such token for this source")
        token_id, token_name = body.token_id, None
    else:
        label = body.token_name or f"{body.platform} {clock.now():%Y-%m-%d}"
        made, token = await run_in_threadpool(tokens.create, source_id, label, user.user_id)
        token_id, token_name = made.token_id, made.name
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
            "token_id": token_id,
            "token_name": token_name,
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


async def _check_token(request: Request, config: SourceConfig, secret: str | None) -> None:
    """A Proxmox token with any privilege beyond PVEAuditor's is refused before it is
    stored (ADR-0045 A7)."""
    ingest: IngestService = request.app.state.ingest
    try:
        await run_in_threadpool(
            check_on_save, config.kind, config.proxmox, secret, ingest.api_transport
        )
    except ConnectorError as exc:
        raise SourceRejectedError(str(exc)) from None


class ApiTest(BaseModel):
    """Settings and credentials to try before an API source is saved."""

    kind: Literal["m365", "anthropic", "proxmox"]
    m365: M365Settings | None = None
    anthropic: AnthropicSettings | None = None
    proxmox: ProxmoxSettings | None = None
    credentials: ApiCredentials = ApiCredentials()


class ApiTestOut(BaseModel):
    feeds: dict[str, str]  # feed -> "ok" or why it failed
    thumbprint: str | None = None  # Microsoft 365 certificates: the value Entra shows


def _api_source(kind: Literal["m365", "anthropic", "proxmox"], body: ApiTest) -> SourceConfig:
    try:
        return SourceConfig(
            source_id="connection_test",
            format="json",
            kind=kind,
            m365=body.m365 if kind == "m365" else None,
            anthropic=body.anthropic if kind == "anthropic" else None,
            proxmox=body.proxmox if kind == "proxmox" else None,
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
    settings = config.m365 or config.anthropic or config.proxmox
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
    await _check_token(request, found[0], secret)
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
    # Push sources: "Quiet is normal for up to N days" (D260); null turns it off.
    quiet_ok_days: QuietOkDays | None = None
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
            "quiet_ok_days",
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
    if "quiet_ok_days" in body.model_fields_set:
        quiet_days = body.quiet_ok_days
        before_qd, source = await run_in_threadpool(store.set_quiet_ok_days, source_id, quiet_days)
        request.app.state.overview.forget()  # the source's condition changes now, not in 5 min
        await run_in_threadpool(
            _audit(request).audit.write,
            "source.quiet_ok_change",
            "success",
            user.user_id,
            client_ip(request),
            {"source_id": source_id, "from": before_qd, "to": quiet_days},
        )
        # The quiet watch's next check (every 30 s) applies the change: taking the mark off
        # judges a held alert by its own threshold then (D262). Nothing waits on the lake here.
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


# --- vendor alert messages (ADR-0049 0b, D231) ---------------------------------------------


def _vendor(request: Request) -> ExternalAlertSettings:
    settings: ExternalAlertSettings = request.app.state.external_alert_settings
    return settings


def _pause_out(p: Pause | None) -> AlertPauseOut | None:
    return None if p is None else AlertPauseOut(paused_since=p.paused_since, held=p.held)


class AlertNotifyIO(BaseModel):
    """Send this source's new vendor alerts to alert targets (off by default)."""

    notify: bool = False
    target_ids: list[str] = Field(default_factory=list, max_length=10)
    min_severity: Level = "high"


def _notify_out(n: Notify) -> AlertNotifyIO:
    return AlertNotifyIO(
        notify=n.notify,
        target_ids=n.target_ids,
        min_severity=n.min_severity,
    )


@router.get("/sources/{source_id}/alert-notify")
async def get_alert_notify(source_id: str, request: Request, _: AdminUser) -> AlertNotifyIO:
    """Who hears about this source's vendor alerts. The cap's pause notice goes to the
    same targets, whether or not notify is on."""
    if source_id not in await run_in_threadpool(_store(request).ids):
        raise NotFoundError("No such source")
    return _notify_out(await run_in_threadpool(_vendor(request).get, source_id))


@router.put("/sources/{source_id}/alert-notify")
async def set_alert_notify(
    source_id: str, body: AlertNotifyIO, request: Request, user: AdminUser
) -> AlertNotifyIO:
    """Audited as source.vendor_alert_change with the old and new setting."""
    n = await run_in_threadpool(
        _vendor(request).set,
        source_id,
        body.notify,
        body.target_ids,
        body.min_severity,
        user,
        client_ip(request),
    )
    return _notify_out(n)


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


class ReparseJobOut(BaseModel):
    job_id: str
    template_id: str
    state: JobState
    started_at: str
    finished_at: str | None
    rows_found: int
    rows_rewritten: int
    files_rewritten: int
    time_min: str | None  # the reparsed rows' time range, for the rule re-run over it
    time_max: str | None
    error: str | None
    # The rule re-run over the rewritten rows (ADR-0050 row 7, slice 3b); None until started.
    rules_state: RulesState | None = None
    rules_run_at: str | None = None
    rules_finished_at: str | None = None
    rules_count: int = 0  # rules that ran
    rules_matched: int = 0
    rules_items: int = 0  # alert items raised or grown
    rules_error: str | None = None


class ReparseOut(BaseModel):
    source_id: str
    template_id: str | None
    template_available: bool
    pending: int  # template_missing rows in the source's retention window
    job: ReparseJobOut | None


def _reparse_offers(request: Request) -> dict[str, str]:
    """Sources with a cleared fallback whose template loads now: {source: template}."""
    fallbacks: SourceFallbacks | None = request.app.state.ingest.fallbacks
    if fallbacks is None:
        return {}
    templates: TemplateRegistry = request.app.state.templates
    return {
        sid: tid
        for sid, tid in fallbacks.reparse_offers().items()
        if templates.get(tid) is not None
    }


def _reparse(request: Request) -> ReparseJobs:
    jobs: ReparseJobs = request.app.state.reparse
    return jobs


def _latest_jobs(
    request: Request, sources: list[SourceConfig]
) -> tuple[dict[str, ReparseJob], dict[str, list[RuleFailure]], set[str]]:
    """Each listed source's latest reparse job (one indexed read), the rules a partial
    rule re-run could not run, and the jobs whose rule re-run is offered. Metadata only:
    the lake is never read here (the start checks it)."""
    jobs = _reparse(request).latest_for([s.source_id for s in sources])
    partial = [j.job_id for j in jobs.values() if j.rules_state == "partial"]
    reruns: ReparseRules = request.app.state.reparse_rules
    failed = reruns.failures(partial) if partial else {}
    return jobs, failed, reruns.ready(list(jobs.values()))


def _job_out(job: ReparseJob | None) -> ReparseJobOut | None:
    if job is None:
        return None
    return ReparseJobOut(
        job_id=job.job_id,
        template_id=job.template_id,
        state=job.state,
        started_at=job.started_at,
        finished_at=job.finished_at,
        rows_found=job.rows_found,
        rows_rewritten=job.rows_rewritten,
        files_rewritten=job.files_rewritten,
        time_min=job.time_min,
        time_max=job.time_max,
        error=job.error,
        rules_state=job.rules_state,
        rules_run_at=job.rules_run_at,
        rules_finished_at=job.rules_finished_at,
        rules_count=job.rules_count,
        rules_matched=job.rules_matched,
        rules_items=job.rules_items,
        rules_error=job.rules_error,
    )


def _last_out(
    job: ReparseJob | None, failed: dict[str, list[RuleFailure]], ready: set[str]
) -> ReparseLastOut | None:
    if job is None:
        return None
    return ReparseLastOut(
        job_id=job.job_id,
        state=job.state,
        finished_at=job.finished_at,
        rows_rewritten=job.rows_rewritten,
        time_min=job.time_min,
        time_max=job.time_max,
        rules_state=job.rules_state,
        rules_run_at=job.rules_run_at,
        rules_finished_at=job.rules_finished_at,
        rules_count=job.rules_count,
        rules_matched=job.rules_matched,
        rules_items=job.rules_items,
        rules_error=job.rules_error,
        rules_failed=[
            ReparseRuleFailedOut(rule_id=f.rule_id, title=f.title, error=f.error)
            for f in failed.get(job.job_id, [])
        ],
        rules_ready=job.job_id in ready,
    )


@router.get("/sources/{source_id}/reparse")
async def reparse_status(source_id: str, request: Request, _: AdminUser) -> ReparseOut:
    """Rows stored without the source's template, whether it loads now, and the latest
    reparse job (ADR-0050 row 7)."""
    st = await run_in_threadpool(_reparse(request).status, source_id)
    return ReparseOut(
        source_id=st.source_id,
        template_id=st.template_id,
        template_available=st.template_available,
        pending=st.pending,
        job=_job_out(st.job),
    )


@router.post("/sources/{source_id}/reparse", status_code=status.HTTP_202_ACCEPTED)
async def start_reparse(source_id: str, request: Request, user: AdminUser) -> ReparseJobOut:
    """Start reparsing the source's template_missing rows with its template, in the
    background. Audited as source.reparse at start (with the count) and at the end."""
    job = await run_in_threadpool(
        _reparse(request).start, source_id, user.user_id, client_ip(request)
    )
    out = _job_out(job)
    assert out is not None
    return out


@router.post("/sources/{source_id}/reparse/{job_id}/rules", status_code=status.HTTP_202_ACCEPTED)
async def run_reparse_rules(
    source_id: str, job_id: str, request: Request, user: AdminUser
) -> ReparseJobOut:
    """Run the enabled rules over the rows a reparse job rewrote, on that source only, in
    the background (ADR-0050 row 7): a done job, or a stopped one once nothing is left to
    reparse (409 "Reparse the remaining N events first" until then). Matches are normal
    rule matches and raise alert items under D200, marked late; each target of a schedule
    whose scheduled run would have alerted on them (not paused, its owner may read the
    source, its threshold met) gets one late-detection message (D241). Once per job; after
    a partial run or a stop, a start runs only the rules that did not complete. Audited as
    source.reparse_rules at start and end."""
    reruns: ReparseRules = request.app.state.reparse_rules
    job = await run_in_threadpool(reruns.start, source_id, job_id, user, client_ip(request))
    out = _job_out(job)
    assert out is not None
    return out
