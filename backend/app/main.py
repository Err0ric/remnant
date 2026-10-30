"""FastAPI app factory and server entrypoint.

Access policy (ADR-0001): loopback with no accounts is open; a network bind with no
accounts is setup-only and prints a one-time setup link; otherwise sign-in is required.
"""

import asyncio
import resource
import socket
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import HTMLResponse, Response
from starlette.types import Scope

from app.ai.catalog import Catalog
from app.ai.rollup import AiRollup
from app.ai.usage import Usage
from app.ai.watch import AiWatch
from app.ai.watch_summary import source_classes
from app.alerts.dispatch import AlertDispatcher
from app.alerts.items import AlertItems
from app.alerts.net import Egress, configure_egress
from app.alerts.targets import TargetStore
from app.api.addresses import router as addresses_router
from app.api.ai import router as ai_router
from app.api.alert_items import router as alert_items_router
from app.api.alerts import router as alerts_router
from app.api.ask import router as ask_router
from app.api.audit import router as audit_router
from app.api.auth import router as auth_router
from app.api.dashboard_sections import router as dashboard_sections_router
from app.api.dashboards import router as dashboards_router
from app.api.enrichment import router as enrichment_router
from app.api.entities import router as entities_router
from app.api.explain import router as explain_router
from app.api.groups import router as groups_router
from app.api.handoff import router as handoff_router
from app.api.health_page import router as health_page_router
from app.api.identities import router as identities_router
from app.api.integrity import router as integrity_router
from app.api.mcp import router as mcp_router
from app.api.meta import app_version
from app.api.meta import router as meta_router
from app.api.middleware import HostOriginMiddleware, SecurityMiddleware, TrustedProxyMiddleware
from app.api.otlp import router as otlp_router
from app.api.overview import router as overview_router
from app.api.providers import router as providers_router
from app.api.query import router as query_router
from app.api.rules import router as rules_router
from app.api.schedules import router as schedules_router
from app.api.searches import router as searches_router
from app.api.sources import router as sources_router
from app.api.templates import router as templates_router
from app.api.tokens import router as tokens_router
from app.api.users import router as users_router
from app.auth.groups import GroupStore
from app.auth.oidc import HttpFactory, OidcClient
from app.auth.service import AuthService
from app.auth.tls import ensure_self_signed, resolve_tls
from app.core.branding import PRODUCT_NAME
from app.core.config import AppConfig, is_loopback_host, load_config
from app.core.errors import (
    AnswerShapeError,
    AuthRequiredError,
    CallCancelledError,
    ClassificationBlockedError,
    CloudAckRequiredError,
    ConfigError,
    ConflictError,
    CsrfError,
    FirstUserAdminError,
    ForbiddenError,
    InteractiveRequiredError,
    LastAdminError,
    LinkInvalidError,
    LoginFailedError,
    NotFoundError,
    ParamInvalidError,
    PayloadTooLargeError,
    ProviderBusyError,
    ProviderConfigError,
    ProviderError,
    ProviderUnreachableError,
    QueryBusyError,
    QueryFailedError,
    QueryMemoryError,
    QueryRejectedError,
    QueryTimeoutError,
    RateLimitedError,
    RuleRejectedError,
    SearchInvalidError,
    SetupClosedError,
    SetupInvalidError,
    SetupRequiredError,
    SourceRejectedError,
    SsoRefusedError,
    SsoRequiredError,
    TemplateInvalidError,
    UnsupportedMediaError,
)
from app.core.logging import configure_logging
from app.core.memory import budget_note, server_budget_mb
from app.core.net import parse_trusted
from app.core.threads import cap_allocator_arenas, query_threads
from app.detect.runner import RuleRunner
from app.detect.store import RuleStore
from app.engine.duckdb import QueryEngine, QueryScope, spill_dir
from app.enrich.feeds import FeedStore
from app.enrich.geoip import GeoIP
from app.enrich.intel import ThreatIntel
from app.enrich.updater import FeedUpdater
from app.ingest.integrity import IntegrityLedger
from app.ingest.listener import SyslogListeners
from app.ingest.maintenance import LakeMaintenance
from app.ingest.otlp import Spool
from app.ingest.quiet import QuietWatch
from app.ingest.sources import SourceStore
from app.ingest.watcher import IngestService
from app.llm.agent import AskAgent
from app.llm.explain import Explainer
from app.llm.gate import LLMGate
from app.llm.parser_draft import ParserDrafter, file_owners
from app.llm.prompt_files import load_prompt
from app.llm.registry import ProviderStore
from app.llm.semantic import base_vocabulary
from app.mcp.server import McpServer
from app.mcp.settings import McpSettingsStore
from app.meta.audit import AuditReader
from app.meta.db import MetaDB
from app.meta.secrets import SecretBox
from app.ops.integrity import IntegrityService
from app.search.dashboards import DashboardStore
from app.search.handoff import HandoffService
from app.search.health import HealthService
from app.search.identity import IdentityStore
from app.search.overview import OverviewService
from app.search.saved import SavedSearchStore
from app.search.schedules import ScheduleService
from app.templates.changes import record as record_template_versions
from app.templates.drafts import DraftStore
from app.templates.registry import STARTER_DIR, TemplateRegistry

log = structlog.get_logger("app")

_ERROR_STATUS: dict[type[Exception], tuple[int, str]] = {
    QueryRejectedError: (400, "query_rejected"),
    QueryFailedError: (400, "query_failed"),
    QueryMemoryError: (503, "query_memory"),  # a server limit, not a bad request (F63)
    QueryTimeoutError: (408, "query_timeout"),
    SourceRejectedError: (400, "source_rejected"),
    NotFoundError: (404, "not_found"),
    ConflictError: (409, "conflict"),
    AuthRequiredError: (401, "auth_required"),
    LoginFailedError: (401, "login_failed"),
    ForbiddenError: (403, "forbidden"),
    CsrfError: (403, "csrf_failed"),
    SetupRequiredError: (403, "setup_required"),
    SetupInvalidError: (403, "setup_invalid"),
    SetupClosedError: (409, "setup_closed"),
    RateLimitedError: (429, "rate_limited"),
    LastAdminError: (409, "last_admin"),
    FirstUserAdminError: (409, "first_user_admin"),
    LinkInvalidError: (403, "link_invalid"),
    SsoRequiredError: (403, "sso_required"),
    SsoRefusedError: (400, "sso_refused"),
    InteractiveRequiredError: (403, "interactive_required"),
    ParamInvalidError: (400, "param_invalid"),
    SearchInvalidError: (400, "search_invalid"),
    TemplateInvalidError: (400, "template_invalid"),
    RuleRejectedError: (400, "rule_rejected"),
    PayloadTooLargeError: (413, "too_large"),
    UnsupportedMediaError: (415, "unsupported_media"),
    CloudAckRequiredError: (409, "cloud_ack_required"),
    ProviderError: (502, "provider_error"),
    ProviderUnreachableError: (502, "provider_error"),
    ProviderBusyError: (503, "provider_busy"),
    QueryBusyError: (503, "busy"),
    CallCancelledError: (409, "cancelled"),
    AnswerShapeError: (502, "provider_error"),
    ProviderConfigError: (400, "provider_invalid"),
    ClassificationBlockedError: (403, "classification_blocked"),
}


LAST_EVENTS_SQL = "SELECT source_id, max(time_observed) FROM events GROUP BY 1 LIMIT 10000"


def _seed_last_events(service: IngestService, engine: QueryEngine) -> None:
    """Newest stored event per source over the last 30 days, read once at start (QA F8)."""
    now = datetime.now(UTC)
    result = engine.run(
        LAST_EVENTS_SQL, QueryScope(sources=None, start=now - timedelta(days=30), end=now)
    )
    seen: dict[str, datetime] = {}
    for sid, at in result.rows:
        try:
            when = at if isinstance(at, datetime) else datetime.fromisoformat(str(at))
        except ValueError:
            continue
        seen[str(sid)] = when if when.tzinfo else when.replace(tzinfo=UTC)
    service.seed_last_events(seen)


async def _ingest_loop(service: IngestService, interval_s: float, engine: QueryEngine) -> None:
    """Poll sources forever. One bad pass is logged and retried, never fatal."""
    try:
        await asyncio.to_thread(_seed_last_events, service, engine)
    except Exception as exc:  # never fatal: Health shows "never" until the next event
        log.warning("ingest.seed_failed", error=type(exc).__name__)
    while True:
        try:
            await asyncio.to_thread(service.run_once)
        except Exception as exc:  # keep the loop alive; detail stays out of logs (no raw lines)
            log.warning("ingest.pass_failed", error=type(exc).__name__)
        await asyncio.sleep(interval_s)


async def _maintenance_loop(maintenance: LakeMaintenance) -> None:
    try:  # once at start: any file whose footer does not read is moved aside
        await asyncio.to_thread(maintenance.sweep_all)
        await asyncio.to_thread(maintenance.baseline)
    except Exception as exc:  # never fatal
        log.warning("maintenance.sweep_failed", error=type(exc).__name__)
    while True:
        try:
            await asyncio.to_thread(maintenance.tick)
        except Exception as exc:  # never fatal; retried next minute
            log.warning("maintenance.failed", error=type(exc).__name__)
        await asyncio.sleep(60)


async def _enrichment_loop(updater: FeedUpdater) -> None:
    """Checks feeds every 10 minutes; each feed decides whether it is due (ADR-0023)."""
    while True:
        try:
            await asyncio.to_thread(updater.run_due)
        except Exception as exc:  # never fatal; retried next round
            log.warning("enrichment.loop_failed", error=type(exc).__name__)
        await asyncio.sleep(600)


def public_url(config: AppConfig) -> str | None:
    """Where people open the app, for links in alerts (ADR-0007); None on loopback."""
    if config.server.public_url:
        return config.server.public_url.rstrip("/")
    if config.server.public_names:
        return f"https://{config.server.public_names[0]}:{config.server.port}"
    return None


async def _schedule_loop(
    schedules: ScheduleService,
    alerts: AlertDispatcher,
    quiet: QuietWatch,
    ai_watch: AiWatch,
    health: HealthService,
) -> None:
    while True:
        try:
            await asyncio.to_thread(schedules.tick)
        except Exception as exc:  # never fatal; retried next tick
            log.warning("schedules.failed", error=type(exc).__name__)
        try:
            await asyncio.to_thread(quiet.tick)
        except Exception as exc:  # never fatal; retried next tick
            log.warning("quiet_watch.failed", error=type(exc).__name__)
        try:
            await asyncio.to_thread(ai_watch.tick)
        except Exception as exc:  # never fatal; retried next tick
            log.warning("ai_watch.failed", error=type(exc).__name__)
        try:
            await asyncio.to_thread(health.tick)
        except Exception as exc:  # never fatal; retried next tick
            log.warning("device_watch.failed", error=type(exc).__name__)
        try:
            await asyncio.to_thread(alerts.tick)
        except Exception as exc:  # never fatal; retried next tick
            log.warning("alerts.failed", error=type(exc).__name__)
        await asyncio.sleep(30)


async def _listener_loop(listeners: SyslogListeners, sources: SourceStore) -> None:
    """Keep the syslog listeners in step with the sources (ADR-0021): a new, changed,
    disabled, or deleted listener source takes effect within a few seconds."""
    while True:
        try:
            await listeners.reconcile(await asyncio.to_thread(sources.list))
        except Exception as exc:  # the loop must survive one bad pass
            log.warning("syslog_listener.reconcile_failed", error=type(exc).__name__)
        await asyncio.sleep(5)


def _lifespan(config: AppConfig) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        tasks: list[asyncio.Task[None]] = []
        if config.ingest.enabled:
            tasks.append(
                asyncio.create_task(
                    _ingest_loop(app.state.ingest, config.ingest.poll_interval_s, app.state.engine)
                )
            )
        if config.maintenance.enabled:
            tasks.append(asyncio.create_task(_maintenance_loop(app.state.maintenance)))
            tasks.append(asyncio.create_task(_enrichment_loop(app.state.feed_updater)))
        if config.schedules.enabled:
            tasks.append(
                asyncio.create_task(
                    _schedule_loop(
                        app.state.schedules,
                        app.state.alert_dispatcher,
                        app.state.quiet,
                        app.state.ai_watch,
                        app.state.health,
                    )
                )
            )
        if config.ingest.enabled:
            tasks.append(
                asyncio.create_task(_listener_loop(app.state.listeners, app.state.sources))
            )
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task
            await app.state.listeners.close()

    return lifespan


class SpaStaticFiles(StaticFiles):
    """Serve the web UI; unknown paths (like /setup) get index.html so the app can route them.

    /api/* never falls back, so a missing endpoint stays a 404 instead of an HTML page.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        if path in ("", ".", "index.html"):
            return self._index(scope)
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or path == "api" or path.startswith("api/"):
                raise
            return self._index(scope)

    def _index(self, scope: Scope) -> Response:
        """index.html with this response's CSP style nonce, for runtime-injected editor styles."""
        assert self.directory is not None
        html = (Path(self.directory) / "index.html").read_text(encoding="utf-8")
        nonce = scope.get("state", {}).get("csp_nonce", "")
        html = html.replace("<head>", f'<head><meta name="csp-nonce" content="{nonce}">', 1)
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


def sso_redirect_uri(config: AppConfig) -> str:
    """Where the identity provider sends the browser back (ADR-0013)."""
    base = public_url(config)
    if base is None:
        if not is_loopback_host(config.server.host):
            raise ConfigError(
                "Single sign-on needs the address people open: set APP__SERVER__PUBLIC_URL"
                " or APP__SERVER__PUBLIC_NAMES"
            )
        base = f"http://localhost:{config.server.port}"
    return f"{base}/api/auth/sso/callback"


def create_app(config: AppConfig | None = None, sso_http: HttpFactory | None = None) -> FastAPI:
    """`sso_http` replaces the HTTP client used to reach the identity provider (tests)."""
    config = config or AppConfig()
    configure_logging()  # idempotent; logs go to stderr as JSON, never stdout
    net = config.network
    configure_egress(
        Egress(
            https_proxy=net.https_proxy,
            username=net.proxy_username,
            password=net.proxy_password.get_secret_value() if net.proxy_password else None,
            ca_bundle=str(net.ca_bundle) if net.ca_bundle else None,
        )
    )
    app = FastAPI(
        title=PRODUCT_NAME,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=_lifespan(config),
    )
    lake_dir = config.paths.data_dir / "lake"
    app.state.lake_dir = lake_dir
    meta = MetaDB(config.paths.data_dir / "meta.sqlite")
    loopback = is_loopback_host(config.server.host)
    # Inner first: the host check runs inside the security headers, so its refusals carry them.
    app.add_middleware(
        HostOriginMiddleware, loopback=loopback, extra_hosts=config.server.public_names
    )
    app.add_middleware(SecurityMiddleware, https=not loopback)
    # Outermost: everything inside sees the resolved client address (ADR-0027).
    app.add_middleware(TrustedProxyMiddleware, trusted=parse_trusted(config.server.trusted_proxies))
    app.state.config = config
    app.state.meta = meta
    oidc = None
    if config.sso.enabled:
        oidc = OidcClient(
            config.sso,
            sso_redirect_uri(config),
            lambda: app.state.auth.clock(),
            **({"http": sso_http} if sso_http else {}),
        )
    app.state.auth = AuthService(config, meta, oidc)
    app.state.providers = ProviderStore(
        meta, SecretBox(config.paths.data_dir), lambda: app.state.auth.clock()
    )
    app.state.searches = SavedSearchStore(meta, lambda: app.state.auth.clock())
    app.state.groups = GroupStore(meta, app.state.auth.audit, lambda: app.state.auth.clock())
    budget = server_budget_mb(config.server.memory_limit_mb)
    qt = query_threads(config.server.query_threads, config.server.max_concurrent_queries)
    app.state.feeds = FeedStore(meta, config.paths.data_dir)
    app.state.engine = QueryEngine(
        lake_dir,
        rollup_dir=config.paths.data_dir / "rollup" / "ai",
        intel_file=app.state.feeds.intel_file,
        # A share of the budget per query, so every allowed query fits with one share left
        # for ingest and the server itself (D80).
        memory_mb=max(256, budget // (qt.at_once + 1)) if budget else None,
        threads=qt.per_query,
        max_concurrent=qt.at_once,
        temp_dir=spill_dir(config.paths.data_dir),
    )
    app.state.gate = LLMGate(
        meta,
        app.state.providers,
        app.state.engine,
        config.llm,
        lambda: app.state.auth.clock(),
        redaction_key=SecretBox(config.paths.data_dir).install_key,
    )
    app.state.explainer = Explainer(app.state.gate, app.state.engine)
    app.state.ask = AskAgent(app.state.gate, app.state.engine, base_vocabulary())
    load_prompt(config.llm.ask_prompt)  # a missing prompt file stops start-up, not an Ask
    app.state.ask.prompt = config.llm.ask_prompt
    app.state.sources = SourceStore(
        meta,
        config.paths.allowed_roots,
        SecretBox(config.paths.data_dir),
        spool_root=config.paths.data_dir / "spool",
    )
    app.state.otlp_spool = Spool(config.paths.data_dir / "spool")
    app.state.sources.web_port = config.server.port
    app.state.mcp_settings = McpSettingsStore(meta)
    app.state.mcp = McpServer(app.state.engine, meta, app.state.auth.audit, app_version())
    app.state.listeners = SyslogListeners(
        config.paths.data_dir / "spool",
        config.server.host,
        lambda: _listener_tls(config),
    )
    app.state.rules = RuleStore(meta, app.state.auth.audit, config.paths.rule_roots)
    app.state.templates = TemplateRegistry(
        config.paths.starter_templates or STARTER_DIR, config.paths.data_dir / "templates"
    )
    for problem in app.state.templates.problems:
        log.warning("template.not_loaded", file=problem.file, reason=problem.message[:300])
    # The day each template version is first loaded: where a changed mapping starts (F66).
    record_template_versions(meta, app.state.templates.all(), datetime.now(UTC))
    app.state.alert_targets = TargetStore(
        meta, SecretBox(config.paths.data_dir), lambda: app.state.auth.clock()
    )
    app.state.public_url = public_url(config)
    app.state.alert_dispatcher = AlertDispatcher(
        meta, app.state.alert_targets, lambda: app.state.auth.clock()
    )
    app.state.rule_runner = RuleRunner(
        meta,
        app.state.engine,
        app.state.sources,
        app.state.templates,
        app.state.rules,
        app.state.auth.audit,
    )
    app.state.dashboards = DashboardStore(meta, lambda: app.state.auth.clock())
    app.state.alert_items = AlertItems(
        meta, app.state.auth.audit, clock=lambda: app.state.auth.clock()
    )
    app.state.schedules = ScheduleService(
        meta,
        config.schedules,
        app.state.auth.users,
        lambda: app.state.auth.mode() == "open",
        app.state.searches,
        app.state.rules,
        app.state.rule_runner,
        app.state.engine,
        app.state.auth.audit,
        dispatcher=app.state.alert_dispatcher,
        link=app.state.public_url,
        items=app.state.alert_items,
    )
    app.state.quiet = QuietWatch(
        meta,
        received=lambda: {sid: st.last_event_at for sid, st in app.state.ingest.status().items()},
        source_ids=lambda: {s.source_id for s in app.state.sources.list()},
        dispatcher=app.state.alert_dispatcher,
        audit=app.state.auth.audit,
        link=app.state.public_url,
        clock=lambda: app.state.auth.clock(),
        items=app.state.alert_items,
    )
    app.state.health = HealthService(
        meta,
        app.state.engine,
        otlp_sources=lambda: [s.source_id for s in app.state.sources.list() if s.kind == "otlp"],
        dispatcher=app.state.alert_dispatcher,
        audit=app.state.auth.audit,
        link=app.state.public_url,
        clock=lambda: app.state.auth.clock(),
    )
    app.state.ai_catalog = Catalog(meta)
    app.state.identities = IdentityStore(meta)
    app.state.ai_rollup = AiRollup(
        app.state.engine,
        app.state.ai_catalog,
        lake_dir,
        config.paths.data_dir / "rollup" / "ai",
        clock=lambda: app.state.auth.clock(),
    )
    app.state.ai_usage = Usage(app.state.engine, app.state.ai_catalog, app.state.ai_rollup)
    app.state.ai_watch = AiWatch(
        meta,
        app.state.engine,
        app.state.ai_catalog,
        app.state.alert_dispatcher,
        app.state.auth.audit,
        app.state.public_url,
        clock=lambda: app.state.auth.clock(),
        items=app.state.alert_items,
        agent_sources=lambda: source_classes(
            [(s.source_id, s.kind or "file", s.template_id) for s in app.state.sources.list()]
        )["telemetry"],
        usage=app.state.ai_usage,
    )
    app.state.audit_reader = AuditReader(meta)
    app.state.overview = OverviewService(
        meta,
        app.state.engine,
        app.state.sources,
        lambda: app.state.ingest,
        app.state.schedules,
        app.state.rule_runner,
        app.state.alert_targets,
        app.state.alert_dispatcher,
        lambda: app.state.auth.clock(),
    )
    app.state.drafts = DraftStore(
        meta,
        app.state.templates,
        config.paths.allowed_roots,
        lambda tid: [s.source_id for s in app.state.sources.list() if s.template_id == tid],
        lambda: app.state.auth.clock(),
    )
    app.state.drafter = ParserDrafter(
        app.state.gate,
        app.state.drafts,
        file_owners(app.state.sources.list, config.paths.allowed_roots),
    )
    app.state.handoff = HandoffService(
        app.state.engine,
        app.state.alert_targets,
        app.state.alert_dispatcher,
        app.state.auth.audit,
        app.state.public_url,
    )
    app.state.integrity = IntegrityLedger(meta, lake_dir)
    app.state.geoip = GeoIP(app.state.feeds)
    app.state.intel = ThreatIntel(app.state.feeds.intel_file)
    box = SecretBox(config.paths.data_dir)

    def feed_key(feed_id: str) -> str | None:
        sealed = app.state.feeds.sealed_key(feed_id)
        return box.decrypt(sealed) if sealed else None

    app.state.feed_updater = FeedUpdater(
        app.state.feeds,
        app.state.auth.audit,
        key=feed_key,
        intel_every_s=int(config.maintenance.intel_check_s),
    )
    app.state.ingest = IngestService(
        app.state.sources,
        meta,
        lake_dir,
        templates=app.state.templates,
        events=app.state.integrity,
    )
    app.state.ingest.listener_errors = lambda: {
        sid: st.error for sid, st in app.state.listeners.status().items() if st.error
    }
    app.state.maintenance = LakeMaintenance(
        lake_dir,
        app.state.sources,
        orphan_retention_days=config.maintenance.orphan_retention_days,
        compaction_interval_s=config.maintenance.compaction_interval_s,
        retention_interval_s=config.maintenance.retention_interval_s,
        integrity=app.state.integrity,
        integrity_interval_s=config.maintenance.integrity_interval_s,
    )
    app.state.maintenance.after_compaction = app.state.ai_rollup.run
    app.state.maintenance.each_tick = app.state.ai_rollup.recheck
    app.state.integrity_service = IntegrityService(
        meta,
        app.state.integrity,
        app.state.auth.audit,
        SecretBox(config.paths.data_dir).install_key,
        dispatcher=app.state.alert_dispatcher,
        link=app.state.public_url,
    )
    app.state.maintenance.on_verified = app.state.integrity_service.seal
    app.include_router(meta_router, prefix="/api")
    app.include_router(alert_items_router, prefix="/api")
    app.include_router(auth_router, prefix="/api")
    app.include_router(query_router, prefix="/api")
    app.include_router(sources_router, prefix="/api")
    app.include_router(otlp_router, prefix="/api")
    app.include_router(ai_router, prefix="/api")
    app.include_router(mcp_router, prefix="/api")
    app.include_router(entities_router, prefix="/api")
    app.include_router(enrichment_router, prefix="/api")
    app.include_router(identities_router, prefix="/api")
    app.include_router(users_router, prefix="/api")
    app.include_router(groups_router, prefix="/api")
    app.include_router(tokens_router, prefix="/api")
    app.include_router(searches_router, prefix="/api")
    app.include_router(providers_router, prefix="/api")
    app.include_router(ask_router, prefix="/api")
    app.include_router(templates_router, prefix="/api")
    app.include_router(rules_router, prefix="/api")
    app.include_router(explain_router, prefix="/api")
    app.include_router(alerts_router, prefix="/api")
    app.include_router(schedules_router, prefix="/api")
    app.include_router(dashboards_router, prefix="/api")
    app.include_router(dashboard_sections_router, prefix="/api")
    app.include_router(overview_router, prefix="/api")
    app.include_router(health_page_router, prefix="/api")
    app.include_router(handoff_router, prefix="/api")
    app.include_router(integrity_router, prefix="/api")
    app.include_router(addresses_router, prefix="/api")
    app.include_router(audit_router, prefix="/api")

    async def app_error(request: Request, exc: Exception) -> JSONResponse:
        code, kind = _ERROR_STATUS[type(exc)]
        headers = {}
        if isinstance(exc, QueryMemoryError):
            log.warning(
                "query.memory",
                request_id=getattr(request.state, "request_id", None),
                query=exc.query,
                path=request.url.path,
            )
        if (
            isinstance(exc, RateLimitedError | ProviderBusyError | QueryBusyError)
            and exc.retry_after_s
        ):
            headers["Retry-After"] = str(exc.retry_after_s)
        return JSONResponse(
            status_code=code, content={"detail": str(exc), "code": kind}, headers=headers
        )

    for exc_type in _ERROR_STATUS:
        app.add_exception_handler(exc_type, app_error)

    static_dir = config.server.static_dir
    if static_dir is not None and static_dir.is_dir():
        app.mount("/", SpaStaticFiles(directory=static_dir, html=True), name="web")
    return app


def _listener_tls(config: AppConfig) -> tuple[Path, Path] | None:
    """The web interface's certificate for TLS syslog (ADR-0021 row 6); on a loopback bind,
    the generated self-signed one."""
    tls = resolve_tls(config) or ensure_self_signed(
        config.paths.data_dir / "tls", config.server.public_names
    )
    return tls.cert, tls.key


def run() -> None:
    import uvicorn

    from app.launch import message_for, unreadable

    configure_logging()
    try:
        config = load_config()
        tls = resolve_tls(config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    static = config.server.static_dir
    bad = unreadable([static]) if static is not None else []
    if bad:  # F50: one plain line, not a 403 on every page
        print(message_for(bad[0]), file=sys.stderr, flush=True)
        raise SystemExit(78)

    budget = server_budget_mb(config.server.memory_limit_mb)
    qt = query_threads(config.server.query_threads, config.server.max_concurrent_queries)
    if budget is not None:
        note = budget_note(config.server.memory_limit_mb)
        print(f"Memory budget: {budget} MB ({note})")
    arenas = cap_allocator_arenas()  # fewer reserved arenas, whatever enforces memory (D79)
    if budget is not None and config.server.address_space_cap and sys.platform.startswith("linux"):
        # Opt-in (D80): thread stacks get room on top so a burst can still start threads.
        cap = budget + qt.headroom_mb
        resource.setrlimit(resource.RLIMIT_AS, (cap << 20, cap << 20))
        print(f"Address-space cap: {cap} MB (budget plus {qt.headroom_mb} MB for threads)")
    print(
        f"Queries: {qt.per_query} threads each, {qt.at_once} at once"
        f" (up to about {qt.peak} threads for queries at peak); malloc arenas: {arenas}"
    )
    proxies = config.server.trusted_proxies
    print(
        f"Trusted proxies: {', '.join(proxies)}"
        if proxies
        else "Trusted proxies: none (forwarded headers ignored)"
    )
    scheme = "https" if tls else "http"
    print(f"{PRODUCT_NAME} listening on {scheme}://{config.server.host}:{config.server.port}")
    if tls is not None and tls.self_signed:
        print(f"Self-signed certificate: {tls.cert}")
        print(f"Verify in your browser: SHA-256 {tls.fingerprint_sha256}", flush=True)

    app = create_app(config)
    auth: AuthService = app.state.auth
    if auth.mode() == "setup":
        public = (
            config.server.public_names[0] if config.server.public_names else socket.gethostname()
        )
        print("")
        print("No administrator account exists yet. Open this one-time link to create it:")
        print(f"  {auth.setup_url(public, config.server.port, config.server.public_url)}")
        print("The link works once and expires in 30 minutes. Restarting issues a new one.")
        if not config.server.public_url:
            print(
                "Behind a reverse proxy? Set APP_PUBLIC_URL (systemd: APP__SERVER__PUBLIC_URL)"
                " to the address people open, then restart, so this link goes through it."
            )
        print("", flush=True)  # reach the log now, even when stdout is a pipe

    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
        proxy_headers=False,
        server_header=False,
        access_log=False,  # SecurityMiddleware writes a structured line per request
        ssl_certfile=str(tls.cert) if tls else None,
        ssl_keyfile=str(tls.key) if tls else None,
    )


if __name__ == "__main__":
    run()
