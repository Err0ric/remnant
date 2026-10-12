"""FastAPI app factory and server entrypoint.

Access policy (ADR-0001): loopback with no accounts is open; a network bind with no
accounts is setup-only and prints a one-time setup link; otherwise sign-in is required.
"""

import asyncio
import socket
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import HTMLResponse, Response
from starlette.types import Scope

from app.alerts.dispatch import AlertDispatcher
from app.alerts.targets import TargetStore
from app.api.alerts import router as alerts_router
from app.api.ask import router as ask_router
from app.api.audit import router as audit_router
from app.api.auth import router as auth_router
from app.api.explain import router as explain_router
from app.api.groups import router as groups_router
from app.api.meta import router as meta_router
from app.api.middleware import HostOriginMiddleware, SecurityMiddleware
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
from app.auth.tls import resolve_tls
from app.core.branding import PRODUCT_NAME
from app.core.config import AppConfig, is_loopback_host, load_config
from app.core.errors import (
    AnswerShapeError,
    AuthRequiredError,
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
    ProviderConfigError,
    ProviderError,
    QueryFailedError,
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
)
from app.core.logging import configure_logging
from app.detect.runner import RuleRunner
from app.detect.store import RuleStore
from app.engine.duckdb import QueryEngine
from app.ingest.maintenance import LakeMaintenance
from app.ingest.sources import SourceStore
from app.ingest.watcher import IngestService
from app.llm.agent import AskAgent
from app.llm.explain import Explainer
from app.llm.gate import LLMGate
from app.llm.parser_draft import ParserDrafter, file_owners
from app.llm.registry import ProviderStore
from app.llm.semantic import base_vocabulary
from app.meta.audit import AuditReader
from app.meta.db import MetaDB
from app.meta.secrets import SecretBox
from app.search.overview import OverviewService
from app.search.saved import SavedSearchStore
from app.search.schedules import ScheduleService
from app.templates.drafts import DraftStore
from app.templates.registry import STARTER_DIR, TemplateRegistry

log = structlog.get_logger("app")

_ERROR_STATUS: dict[type[Exception], tuple[int, str]] = {
    QueryRejectedError: (400, "query_rejected"),
    QueryFailedError: (400, "query_failed"),
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
    CloudAckRequiredError: (409, "cloud_ack_required"),
    ProviderError: (502, "provider_error"),
    AnswerShapeError: (502, "provider_error"),
    ProviderConfigError: (400, "provider_invalid"),
    ClassificationBlockedError: (403, "classification_blocked"),
}


async def _ingest_loop(service: IngestService, interval_s: float) -> None:
    """Poll sources forever. One bad pass is logged and retried, never fatal."""
    while True:
        try:
            await asyncio.to_thread(service.run_once)
        except Exception as exc:  # keep the loop alive; detail stays out of logs (no raw lines)
            log.warning("ingest.pass_failed", error=type(exc).__name__)
        await asyncio.sleep(interval_s)


async def _maintenance_loop(maintenance: LakeMaintenance) -> None:
    while True:
        try:
            await asyncio.to_thread(maintenance.tick)
        except Exception as exc:  # never fatal; retried next minute
            log.warning("maintenance.failed", error=type(exc).__name__)
        await asyncio.sleep(60)


def public_url(config: AppConfig) -> str | None:
    """Where people open the app, for links in alerts (ADR-0007); None on loopback."""
    if config.server.public_url:
        return config.server.public_url.rstrip("/")
    if config.server.public_names:
        return f"https://{config.server.public_names[0]}:{config.server.port}"
    return None


async def _schedule_loop(schedules: ScheduleService, alerts: AlertDispatcher) -> None:
    while True:
        try:
            await asyncio.to_thread(schedules.tick)
        except Exception as exc:  # never fatal; retried next tick
            log.warning("schedules.failed", error=type(exc).__name__)
        try:
            await asyncio.to_thread(alerts.tick)
        except Exception as exc:  # never fatal; retried next tick
            log.warning("alerts.failed", error=type(exc).__name__)
        await asyncio.sleep(30)


def _lifespan(config: AppConfig) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        tasks: list[asyncio.Task[None]] = []
        if config.ingest.enabled:
            tasks.append(
                asyncio.create_task(_ingest_loop(app.state.ingest, config.ingest.poll_interval_s))
            )
        if config.maintenance.enabled:
            tasks.append(asyncio.create_task(_maintenance_loop(app.state.maintenance)))
        if config.schedules.enabled:
            tasks.append(
                asyncio.create_task(_schedule_loop(app.state.schedules, app.state.alert_dispatcher))
            )
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task

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
    app = FastAPI(
        title=PRODUCT_NAME,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=_lifespan(config),
    )
    lake_dir = config.paths.data_dir / "lake"
    meta = MetaDB(config.paths.data_dir / "meta.sqlite")
    loopback = is_loopback_host(config.server.host)
    # Inner first: the host check runs inside the security headers, so its refusals carry them.
    app.add_middleware(
        HostOriginMiddleware, loopback=loopback, extra_hosts=config.server.public_names
    )
    app.add_middleware(SecurityMiddleware, https=not loopback)
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
    app.state.engine = QueryEngine(lake_dir)
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
    app.state.sources = SourceStore(
        meta, config.paths.allowed_roots, SecretBox(config.paths.data_dir)
    )
    app.state.rules = RuleStore(meta, app.state.auth.audit, config.paths.rule_roots)
    app.state.templates = TemplateRegistry(
        config.paths.starter_templates or STARTER_DIR, config.paths.data_dir / "templates"
    )
    for problem in app.state.templates.problems:
        log.warning("template.not_loaded", file=problem.file, reason=problem.message[:300])
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
    app.state.ingest = IngestService(
        app.state.sources, meta, lake_dir, templates=app.state.templates
    )
    app.state.maintenance = LakeMaintenance(
        lake_dir,
        app.state.sources,
        orphan_retention_days=config.maintenance.orphan_retention_days,
        compaction_interval_s=config.maintenance.compaction_interval_s,
        retention_interval_s=config.maintenance.retention_interval_s,
    )
    app.include_router(meta_router, prefix="/api")
    app.include_router(auth_router, prefix="/api")
    app.include_router(query_router, prefix="/api")
    app.include_router(sources_router, prefix="/api")
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
    app.include_router(overview_router, prefix="/api")
    app.include_router(audit_router, prefix="/api")

    async def app_error(_: Request, exc: Exception) -> JSONResponse:
        code, kind = _ERROR_STATUS[type(exc)]
        headers = {}
        if isinstance(exc, RateLimitedError):
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


def run() -> None:
    import uvicorn

    configure_logging()
    try:
        config = load_config()
        tls = resolve_tls(config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

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
        print(f"  {auth.setup_url(public, config.server.port)}")
        print("The link works once and expires in 30 minutes. Restarting issues a new one.")
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
