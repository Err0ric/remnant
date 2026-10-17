"""HTTP client and credential storage for the CLI.

The CLI is an API client (CLAUDE.md rule 15): it never imports the engine,
ingest, or metadata modules and never opens the lake.
Tokens are never accepted on the command line, so they stay out of shell history.
"""

import hashlib
import json
import os
import socket
import ssl
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
import keyring
from keyring.errors import KeyringError

DEFAULT_SERVER = "http://127.0.0.1:8080"
ENV_SERVER = "REMNANT_SERVER"
ENV_TOKEN = "REMNANT_TOKEN"  # noqa: S105  # name of an env var, not a secret
KEYRING_SERVICE = "remnant-cli"


class ApiError(Exception):
    def __init__(self, status: int, detail: str, code: str | None = None) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.code = code


class UntrustedCertificateError(ApiError):
    """The server's certificate is not trusted yet (self-signed, not pinned)."""


@dataclass(frozen=True, slots=True)
class Credentials:
    server: str
    token: str | None


def config_dir() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "remnant"


def credentials_path() -> Path:
    return config_dir() / "credentials.json"


def _read_store() -> dict[str, Any]:
    path = credentials_path()
    if not path.exists():
        return {}
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _write_store(data: dict[str, Any]) -> Path:
    path = credentials_path()
    _write_private(path, json.dumps(data, indent=2))
    return path


def save_server(server: str) -> Path:
    data = _read_store()
    data["server"] = server.rstrip("/")
    return _write_store(data)


def store_token(server: str, token: str) -> str:
    """Keep the token in the OS keychain; fall back to a 0600 file on headless hosts."""
    server = server.rstrip("/")
    data = _read_store()
    try:
        keyring.set_password(KEYRING_SERVICE, server, token)
    except KeyringError:
        data.setdefault("tokens", {})[server] = token
        return f"{_write_store(data)} (mode 0600; no system keychain available)"
    if data.get("tokens", {}).pop(server, None) is not None:
        _write_store(data)
    return "the system keychain"


def load_token(server: str) -> str | None:
    server = server.rstrip("/")
    if env := os.environ.get(ENV_TOKEN):
        return env
    try:
        if token := keyring.get_password(KEYRING_SERVICE, server):
            return token
    except KeyringError:
        pass
    token = _read_store().get("tokens", {}).get(server)
    return str(token) if token else None


def delete_token(server: str) -> None:
    server = server.rstrip("/")
    try:
        keyring.delete_password(KEYRING_SERVICE, server)
    except KeyringError:
        pass
    data = _read_store()
    if data.get("tokens", {}).pop(server, None) is not None:
        _write_store(data)


def load_credentials(server_override: str | None = None) -> Credentials:
    stored = _read_store()
    server = server_override or os.environ.get(ENV_SERVER) or stored.get("server") or DEFAULT_SERVER
    server = server.rstrip("/")
    return Credentials(server=server, token=load_token(server))


# --- certificate pinning (trust on first use, confirmed against the server log) -----


def pin_path(server: str) -> Path:
    parts = urlsplit(server)
    key = hashlib.sha256(f"{parts.hostname}:{parts.port or 443}".encode()).hexdigest()[:24]
    return config_dir() / "trust" / f"{key}.pem"


def fetch_certificate(server: str) -> str:
    parts = urlsplit(server)
    if parts.hostname is None:
        raise ApiError(0, f"Not a server URL: {server}")
    return ssl.get_server_certificate((parts.hostname, parts.port or 443), timeout=10)


def fingerprint(pem: str) -> str:
    digest = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).digest()
    return ":".join(f"{b:02X}" for b in digest)


def save_pin(server: str, pem: str) -> Path:
    path = pin_path(server)
    _write_private(path, pem)
    return path


def _verify(server: str) -> ssl.SSLContext | bool:
    path = pin_path(server)
    if server.startswith("https://") and path.exists():
        return ssl.create_default_context(cafile=str(path))
    return True


ClientFactory = Callable[[Credentials], httpx.Client]


def default_client(creds: Credentials) -> httpx.Client:
    headers = {"Accept": "application/json"}
    if creds.token:
        headers["Authorization"] = f"Bearer {creds.token}"
    return httpx.Client(
        base_url=creds.server, headers=headers, timeout=60.0, verify=_verify(creds.server)
    )


class Api:
    def __init__(self, creds: Credentials, factory: ClientFactory = default_client) -> None:
        self._client = factory(creds)
        if creds.token:
            self._client.headers["Authorization"] = f"Bearer {creds.token}"

    def _call(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        content: str | None = None,
        params: dict[str, str] | None = None,
        raw: bool = False,
    ) -> Any:
        try:
            if content is not None:
                res = self._client.request(
                    method,
                    path,
                    content=content.encode(),
                    headers={"Content-Type": "application/yaml"},
                )
            else:
                res = self._client.request(method, path, json=body, params=params)
        except httpx.HTTPError as exc:
            if _is_cert_failure(exc):
                raise UntrustedCertificateError(0, "The server certificate is not trusted") from exc
            raise ApiError(0, f"Cannot reach server: {exc}") from exc
        if res.status_code >= 400:
            detail, code = res.text, None
            try:
                payload = res.json()
                detail, code = str(payload.get("detail", res.text)), payload.get("code")
            except ValueError:
                pass
            raise ApiError(res.status_code, detail, code)
        if raw:
            return res.text
        return None if res.status_code == 204 else res.json()

    def mcp(self, message: bytes, session_id: str | None) -> tuple[int, bytes, str | None]:
        """Forward one MCP JSON-RPC message (ADR-0003) as is. Returns the status, the body,
        and the session id the server named, for the stdio bridge to relay unchanged."""
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        try:
            res = self._client.post("/api/mcp", content=message, headers=headers)
        except httpx.HTTPError as exc:
            if _is_cert_failure(exc):
                raise UntrustedCertificateError(0, "The server certificate is not trusted") from exc
            raise ApiError(0, f"Cannot reach server: {exc}") from exc
        return res.status_code, res.content, res.headers.get("mcp-session-id")

    def auth_state(self) -> dict[str, Any]:
        data: dict[str, Any] = self._call("GET", "/api/auth/state")
        return data

    def login(self, username: str, password: str) -> str:
        # The token is listed under this machine's name, so it is easy to revoke later.
        body = {
            "username": username,
            "password": password,
            "client": "cli",
            "label": f"CLI on {socket.gethostname()}"[:100],
        }
        data: dict[str, Any] = self._call("POST", "/api/auth/login", body)
        return str(data["token"])

    def logout(self) -> None:
        self._call("POST", "/api/auth/logout")

    def searches(self, tag: str | None = None) -> list[dict[str, Any]]:
        data: list[dict[str, Any]] = self._call(
            "GET", "/api/searches", params={"tag": tag} if tag else None
        )
        return data

    def run_search(
        self, search_id: str, params: dict[str, str], start: str | None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"params": params}
        if start:
            body["start"] = start
        data: dict[str, Any] = self._call("POST", f"/api/searches/{quote(search_id)}/run", body)
        return data

    def export_search(self, search_id: str) -> str:
        return str(self._call("GET", f"/api/searches/{quote(search_id)}/export", raw=True))

    def import_search(self, yaml_text: str) -> dict[str, Any]:
        data: dict[str, Any] = self._call("POST", "/api/searches/import", content=yaml_text)
        return data

    def ask_providers(self) -> list[dict[str, Any]]:
        data: list[dict[str, Any]] = self._call("GET", "/api/ask/providers")
        return data

    def ask(self, question: str, **extra: Any) -> dict[str, Any]:
        body = {"question": question, **{k: v for k, v in extra.items() if v is not None}}
        data: dict[str, Any] = self._call("POST", "/api/ask", body)
        return data

    def compile_search(self, text: str) -> dict[str, Any]:
        data: dict[str, Any] = self._call("POST", "/api/search/compile", {"text": text})
        return data

    def sources(self) -> list[str]:
        """Source ids this user can read (the server filters by source groups)."""
        data: list[dict[str, Any]] = self._call("GET", "/api/sources")
        return sorted(str(s["source_id"]) for s in data)

    def query(self, sql: str, **extra: Any) -> dict[str, Any]:
        body = {"sql": sql, **{k: v for k, v in extra.items() if v is not None}}
        data: dict[str, Any] = self._call("POST", "/api/query", body)
        return data


def _is_cert_failure(exc: BaseException) -> bool:
    seen: BaseException | None = exc
    while seen is not None:
        if isinstance(seen, ssl.SSLCertVerificationError):
            return True
        seen = seen.__cause__ or seen.__context__
    return False
