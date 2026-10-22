"""HTTP for provider adapters: pinned address, no redirects, capped responses.

Shared by the adapters in `llm/providers/`, which only `llm/gate.py` imports. Responses
are untrusted: read at most 64 KB (CLAUDE.md security rule 3) and parsed as JSON only.
Headers passed in (API keys) never appear in errors or logs.
"""

import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.core.errors import ProviderBusyError, ProviderError, ProviderUnreachableError
from app.llm.provider import Locality

MAX_RESPONSE_BYTES = 64 * 1024
TIMEOUT = httpx.Timeout(connect=5.0, read=180.0, write=30.0, pool=5.0)


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
            timeout=TIMEOUT,
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
        try:
            with (
                self._client() as client,
                client.stream(
                    method, url, json=body, headers=headers, extensions=extensions
                ) as res,
            ):
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
        except httpx.ConnectError as exc:
            raise ProviderUnreachableError(f"Cannot reach provider: {type(exc).__name__}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Cannot reach provider: {type(exc).__name__}") from exc
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
