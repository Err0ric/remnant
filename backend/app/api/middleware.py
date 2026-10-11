"""Response hardening and request logging for every route (CLAUDE.md security rule 9, SPEC T10).

A fresh nonce per response allows the editor's runtime-injected styles without
'unsafe-inline'. Scripts are 'self' only; there are no inline scripts.

Known benign report: while typing into the SQL editor, Chrome's native
contenteditable handling briefly creates a styled node that this policy refuses.
CodeMirror replaces it on the next update, so nothing visible depends on it.
"""

import ipaddress
import secrets
import time
from urllib.parse import urlsplit

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

log = structlog.get_logger("app.http")


def content_security_policy(nonce: str) -> str:
    return "; ".join(
        [
            "default-src 'self'",
            "script-src 'self'",
            f"style-src 'self' 'nonce-{nonce}'",
            "img-src 'self' data:",
            "font-src 'self'",
            "connect-src 'self'",
            "object-src 'none'",
            "base-uri 'none'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        ]
    )


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, https: bool) -> None:
        super().__init__(app)
        self._https = https

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce
        started = time.perf_counter()
        response = await call_next(request)

        headers = response.headers
        headers["Content-Security-Policy"] = content_security_policy(nonce)
        headers["X-Content-Type-Options"] = "nosniff"
        headers["X-Frame-Options"] = "DENY"
        headers["Referrer-Policy"] = "no-referrer"
        headers["Cross-Origin-Opener-Policy"] = "same-origin"
        headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), usb=()"
        if self._https:
            headers["Strict-Transport-Security"] = "max-age=31536000"
        if request.url.path.startswith("/api/"):
            headers["Cache-Control"] = "no-store"

        user = getattr(request.state, "user", None)
        log.info(
            "http.request",
            method=request.method,
            path=request.url.path,  # never the query string
            status=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
            user_id=getattr(user, "user_id", None),
            client=request.client.host if request.client else None,
        )
        return response


def _host_name(host_header: str) -> str:
    host = host_header.strip().lower()
    if host.startswith("["):  # [::1]:8080
        return host[1 : host.find("]")] if "]" in host else host
    if host.count(":") == 1:  # name:port or v4:port
        return host.split(":", 1)[0]
    return host


class HostOriginMiddleware(BaseHTTPMiddleware):
    """Blocks DNS rebinding and cross-origin writes (review finding S1).

    On a loopback bind with no accounts there is no sign-in, so a web page that rebinds
    its own domain to 127.0.0.1 could otherwise read logs. Only local host names are
    accepted there. On every bind, a write that carries an Origin must come from the
    same origin it is sent to.
    """

    def __init__(self, app: ASGIApp, loopback: bool, extra_hosts: list[str]) -> None:
        super().__init__(app)
        self._loopback = loopback
        self._extra = {h.lower() for h in extra_hosts}

    def _local(self, name: str) -> bool:
        if name == "localhost" or name in self._extra:
            return True
        try:
            return ipaddress.ip_address(name).is_loopback
        except ValueError:
            return False

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        host = request.headers.get("host", "")
        if self._loopback and not self._local(_host_name(host)):
            return JSONResponse(
                {"detail": "This server only answers to local host names", "code": "bad_host"},
                status_code=421,
            )
        origin = request.headers.get("origin")
        if origin is not None and request.method not in ("GET", "HEAD", "OPTIONS"):
            if urlsplit(origin).netloc.lower() != host.lower():
                return JSONResponse(
                    {"detail": "Cross-origin request refused", "code": "cross_origin"},
                    status_code=403,
                )
        return await call_next(request)
