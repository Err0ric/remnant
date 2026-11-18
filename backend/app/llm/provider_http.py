"""HTTP for provider adapters: pinned address, no redirects, capped responses.

Shared by the adapters in `llm/providers/`, which only `llm/gate.py` imports. Responses
are untrusted: read at most 64 KB (CLAUDE.md security rule 3) and parsed as JSON only.
Headers passed in (API keys) never appear in errors or logs.
"""

import json
import socket
import threading
import time
from contextvars import ContextVar
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.core.errors import (
    ModelTimeoutError,
    ProviderBusyError,
    ProviderError,
    ProviderUnreachableError,
)
from app.llm.provider import Locality

MAX_RESPONSE_BYTES = 64 * 1024
# Per-step limits without a deadline (Explain, parser drafts, reports). Under an Ask
# deadline (D270) the read has no limit of its own: the deadline alone governs it, so
# `ask.model_timeout_s` above 180 s is honoured.
CAPS = {"connect": 5.0, "read": 180.0, "write": 30.0, "pool": 5.0}
TIMED_OUT = "The model took too long to answer."

# The time (time.monotonic) by which the current model call must end (D270). Set by the
# gate around one provider request; None means only the per-step limits above apply.
CALL_DEADLINE: ContextVar[float | None] = ContextVar("llm_call_deadline", default=None)


def deadline_left() -> float | None:
    """Seconds left before the current call's deadline, or None when there is none."""
    deadline = CALL_DEADLINE.get()
    return None if deadline is None else deadline - time.monotonic()


class _TimeLeft(dict[str, float]):
    """httpcore's per-request timeouts, read as each phase starts (connect, write, the
    headers, the body): each is the time left to the one deadline, never a fresh limit."""

    def __init__(self, deadline: float) -> None:
        super().__init__()
        self._deadline = deadline

    def get(self, key: str, default: object = None) -> float:  # httpcore reads only .get
        left = max(0.001, self._deadline - time.monotonic())
        return left if key == "read" else min(CAPS.get(key, left), left)


def _cut_off_at(res: httpx.Response, deadline: float) -> threading.Timer | None:
    """Shut the connection's socket at the deadline, so a read already waiting (a reply
    that stalls or trickles after its headers) ends then, not one read timeout later."""
    stream = res.extensions.get("network_stream")
    sock = stream.get_extra_info("socket") if stream is not None else None
    if not isinstance(sock, socket.socket):
        return None

    def shut() -> None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass  # already closed

    timer = threading.Timer(max(0.0, deadline - time.monotonic()), shut)
    timer.daemon = True
    timer.start()
    return timer


class PinnedJsonClient:
    def __init__(
        self,
        base_url: str,
        headers: dict[str, str],
        locality: Locality,
        transport: httpx.BaseTransport | None = None,
        pin: str | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"Accept": "application/json", **headers}
        self._locality = locality
        self._transport = transport
        self._pin = pin

    def _client(self) -> httpx.Client:
        # A local call must reach the pinned address directly: proxy settings from the
        # environment would send it, possibly in plain text, through another host.
        return httpx.Client(
            headers=self._headers,
            timeout=httpx.Timeout(**CAPS),
            follow_redirects=False,
            transport=self._transport,
            trust_env=self._locality == "cloud",
        )

    def _target(self, path: str) -> tuple[str, dict[str, str], dict[str, Any]]:
        """URL to connect to, plus Host header and TLS name when pinned to an address."""
        url = self._base + path
        if not self._pin:
            return url, {}, {}
        parts = urlsplit(url)
        host = parts.hostname or ""
        literal = f"[{self._pin}]" if ":" in self._pin else self._pin
        netloc = f"{literal}:{parts.port}" if parts.port else literal
        extensions: dict[str, Any] = {"sni_hostname": host} if parts.scheme == "https" else {}
        name = f"[{host}]" if ":" in host else host
        host_header = f"{name}:{parts.port}" if parts.port else name
        return urlunsplit(parts._replace(netloc=netloc)), {"Host": host_header}, extensions

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        url, headers, extensions = self._target(path)
        deadline = CALL_DEADLINE.get()
        if deadline is not None:  # one deadline from here across every step (D270)
            if deadline <= time.monotonic():
                raise ModelTimeoutError(TIMED_OUT)
            extensions = {**extensions, "timeout": _TimeLeft(deadline)}
        timer: threading.Timer | None = None
        try:
            with (
                self._client() as client,
                client.stream(
                    method, url, json=body, headers=headers, extensions=extensions
                ) as res,
            ):
                if deadline is not None:
                    timer = _cut_off_at(res, deadline)
                if res.status_code in BUSY_STATUS:
                    raise ProviderBusyError(
                        f"Model server busy (HTTP {res.status_code})",
                        _retry_after(res.headers.get("retry-after")),
                    )
                if res.status_code != 200:
                    head = res.read()[:512].decode("utf-8", "replace").lower()
                    if "busy" in head:  # Ollama: "server busy, please try again"
                        raise ProviderBusyError(f"Model server busy (HTTP {res.status_code})")
                    raise ProviderError(f"Provider returned HTTP {res.status_code}")
                data = b""
                for chunk in res.iter_bytes():
                    data += chunk
                    if len(data) > MAX_RESPONSE_BYTES:
                        raise ProviderError("Provider response too large")
                    if (left := deadline_left()) is not None and left <= 0:
                        raise ModelTimeoutError(TIMED_OUT)  # a trickling reply: closed here
        except httpx.HTTPError as exc:
            late = deadline is not None and deadline - time.monotonic() <= 0.05
            if late or (deadline is not None and isinstance(exc, httpx.ReadTimeout)):
                raise ModelTimeoutError(TIMED_OUT) from exc  # the deadline governs reads
            if isinstance(exc, httpx.ConnectError):
                raise ProviderUnreachableError(
                    f"Cannot reach provider: {type(exc).__name__}"
                ) from exc
            raise ProviderError(f"Cannot reach provider: {type(exc).__name__}") from exc
        finally:
            if timer is not None:
                timer.cancel()
        try:
            return json.loads(data)
        except ValueError as exc:
            raise ProviderError("Provider returned invalid JSON") from exc


BUSY_STATUS = frozenset({429, 503})


def _retry_after(value: str | None) -> int | None:
    """Retry-After in seconds (the date form is rare from model servers and ignored)."""
    if value and value.strip().isdigit():
        return min(int(value.strip()), 600)
    return None
