"""Application configuration.

One AppConfig model, loaded from config/app.yaml plus environment overrides in
the form APP__SECTION__KEY (for example APP__SERVER__HOST=0.0.0.0). No other
module reads os.environ.
"""

import ipaddress
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from app.core.errors import ConfigError

ENV_PREFIX = "APP__"
DEFAULT_CONFIG_PATH = Path("config/app.yaml")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _split_list(value: object) -> object:
    """Env overrides arrive as one string: split on the OS path separator or commas."""
    if isinstance(value, str):
        return [p.strip() for p in re.split(rf"[,{re.escape(os.pathsep)}]", value) if p.strip()]
    return value


class ServerConfig(_Strict):
    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65535)
    static_dir: Path | None = None
    # Bring-your-own certificate. Off loopback, a self-signed one is generated when unset.
    tls_cert: Path | None = None
    tls_key: Path | None = None
    # Extra DNS names or IPs for the generated certificate (for example the VM's name).
    public_names: list[str] = Field(default_factory=list)
    # The address people open in a browser, for links in alerts (ADR-0007). When unset,
    # built from the first public name and the port, or omitted on loopback.
    public_url: str | None = Field(default=None, max_length=300, pattern=r"^https?://[^\s]+$")
    # Optional label shown in the top bar, for example "Production" or "Lab", so people can
    # tell installs apart. Shown before sign-in too, so keep it free of anything sensitive.
    environment_label: str | None = Field(default=None, max_length=24, pattern=r"^[\w .()-]+$")
    # Address-space cap for the server process in MB, so an oversized query fails instead
    # of the process being killed (D58). 0: 75% of the machine's or container's memory.
    memory_limit_mb: int = Field(default=0, ge=0, le=1_048_576)

    _split_names = field_validator("public_names", mode="before")(_split_list)
    _blank_url = field_validator("public_url", "environment_label", mode="before")(
        lambda v: v or None
    )


class AuthConfig(_Strict):
    session_hours: int = Field(default=12, ge=1, le=24 * 7)
    cli_token_days: int = Field(default=30, ge=1, le=365)
    login_max_failures: int = Field(default=5, ge=1, le=100)
    login_window_s: int = Field(default=300, ge=10, le=86400)


_MULTI_TENANT = re.compile(r"/(common|organizations|consumers|\{tenantid\})(/|$)", re.IGNORECASE)


class SsoConfig(_Strict):
    """Optional OpenID Connect sign-in (ADR-0013). Off unless `enabled` is true."""

    # Validation errors must never echo the client secret back into a log.
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    enabled: bool = False
    # One tenant's issuer, e.g. https://login.microsoftonline.com/<tenant-id>/v2.0
    issuer: str | None = Field(default=None, max_length=300)
    client_id: str | None = Field(default=None, max_length=200)
    client_secret: SecretStr | None = None
    label: str = Field(default="Microsoft", min_length=1, max_length=40)
    # Group object ids; when set, the ID token's groups claim must contain one of them.
    required_groups: list[str] = Field(default_factory=list)
    # Scopes beyond "openid profile", e.g. "groups" for Authelia, Keycloak, or Authentik.
    extra_scopes: list[str] = Field(default_factory=list, max_length=10)
    # How the client secret reaches the token endpoint. "auto" uses HTTP Basic unless the
    # provider's discovery document offers only client_secret_post.
    token_auth_method: Literal["auto", "client_secret_basic", "client_secret_post"] = "auto"  # noqa: S105  # a method name
    # With SSO on, who may still sign in with a password ("admins" is the break-glass path).
    password_login: Literal["admins", "everyone"] = "admins"  # noqa: S105  # a policy name, not a secret

    _split_groups = field_validator("required_groups", "extra_scopes", mode="before")(_split_list)

    @field_validator("extra_scopes")
    @classmethod
    def _scope_names(cls, value: list[str]) -> list[str]:
        for scope in value:
            if not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,64}", scope):
                raise ValueError(f"not a scope name: {scope!r}")
        return value

    # Compose passes unset variables as empty strings.
    _blank = field_validator("issuer", "client_id", "client_secret", mode="before")(
        lambda v: v or None
    )

    @model_validator(mode="after")
    def _complete(self) -> "SsoConfig":
        if not self.enabled:
            return self
        missing = [
            name
            for name, value in (
                ("issuer", self.issuer),
                ("client_id", self.client_id),
                ("client_secret", self.client_secret),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"SSO is enabled but {', '.join(missing)} is not set")
        issuer = str(self.issuer)
        if not issuer.startswith("https://"):
            raise ValueError("the SSO issuer must be an https:// URL")
        if _MULTI_TENANT.search(issuer):
            raise ValueError(
                "the SSO issuer must name one tenant (use the tenant id, not common,"
                " organizations, or consumers)"
            )
        return self


class PathsConfig(_Strict):
    data_dir: Path = Path("data")
    allowed_roots: list[Path] = Field(default_factory=list)
    # Folders Sigma rules may be imported from (ADR-0006); separate from log folders so a
    # rule set is never watched as logs.
    rule_roots: list[Path] = Field(default_factory=list)
    # Shipped parser templates; None means the copy next to the code (repo or image).
    starter_templates: Path | None = None

    _split_roots = field_validator("allowed_roots", "rule_roots", mode="before")(_split_list)


class IngestConfig(_Strict):
    enabled: bool = True
    poll_interval_s: float = Field(default=2.0, ge=0.2, le=3600)


class LLMConfig(_Strict):
    # Hosts treated as local even if they resolve to public addresses (SPEC 6.1).
    trusted_local_hosts: list[str] = Field(default_factory=list)
    # Store full prompt and response bodies in llm_calls (SPEC 6.4). Hashes are always kept.
    store_bodies: bool = False
    # Ask prompt version (a file in llm/prompts). Change only after the Ask accuracy suite
    # (backend/evals/nl_queries) shows the new version at least as good on your model.
    ask_prompt: str = Field(default="ask.v4", pattern=r"^ask\.v[0-9]+$")

    _split_hosts = field_validator("trusted_local_hosts", mode="before")(_split_list)


class MaintenanceConfig(_Strict):
    enabled: bool = True
    compaction_interval_s: float = Field(default=3600, ge=60)
    retention_interval_s: float = Field(default=86400, ge=60)
    # Retention for data whose source was removed from the configuration.
    orphan_retention_days: int = Field(default=30, ge=1, le=3650)
    # Full log integrity verification (ADR-0022): re-hashes every lake file.
    integrity_interval_s: float = Field(default=86400, ge=300)
    # Threat intel list checks when automatic updates are on (ADR-0023 row 3).
    intel_check_s: float = Field(default=14400, ge=3600)


class SchedulesConfig(_Strict):
    """Scheduled searches and rules (SPEC 5.5)."""

    enabled: bool = True
    # Wall-clock zone for cron times; IANA name such as America/Los_Angeles.
    timezone: str = "UTC"
    keep_runs: int = Field(default=30, ge=1, le=1000)
    sample_rows: int = Field(default=500, ge=1, le=5000)
    # Each run's range ends this long before its fire time, so events that arrive a little
    # late (relays, batching, file polling) are still inside some run's range.
    lag_seconds: int = Field(default=120, ge=0, le=3600)

    @field_validator("timezone")
    @classmethod
    def _zone(cls, value: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown time zone {value!r}") from exc
        return value


class NetworkConfig(_Strict):
    """Outbound proxy for the fixed-host API connectors and Teams or Slack alerts, and an
    extra CA bundle for outbound TLS (ADR-0018). Credentials come from the environment."""

    https_proxy: str | None = Field(default=None, max_length=300)
    proxy_username: str | None = Field(default=None, max_length=200)
    proxy_password: SecretStr | None = None
    ca_bundle: Path | None = None

    _blank = field_validator(
        "https_proxy", "proxy_username", "proxy_password", "ca_bundle", mode="before"
    )(lambda v: v or None)

    @field_validator("https_proxy")
    @classmethod
    def _proxy_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        m = re.fullmatch(
            r"(https?)://([^/@\s:]+|\[[0-9A-Fa-f:]+\])(?::(\d{1,5}))?/?", value.strip()
        )
        if not m:
            raise ValueError(
                "https_proxy must be http://host:port or https://host:port, with no user name"
                " or password in it (set proxy_username and proxy_password instead)"
            )
        return value.strip().rstrip("/")

    @model_validator(mode="after")
    def _pair(self) -> "NetworkConfig":
        if (self.proxy_username is None) != (self.proxy_password is None):
            raise ValueError("set both proxy_username and proxy_password, or neither")
        if self.proxy_username and not self.https_proxy:
            raise ValueError("proxy_username is set but https_proxy is not")
        if self.ca_bundle is not None and not self.ca_bundle.is_file():
            raise ValueError(f"ca_bundle {self.ca_bundle} is not a file")
        return self


class AppConfig(_Strict):
    server: ServerConfig = Field(default_factory=ServerConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    sso: SsoConfig = Field(default_factory=SsoConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    ingest: IngestConfig = Field(default_factory=IngestConfig)
    maintenance: MaintenanceConfig = Field(default_factory=MaintenanceConfig)
    schedules: SchedulesConfig = Field(default_factory=SchedulesConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)


def _env_overrides(environ: Mapping[str, str]) -> dict[str, Any]:
    tree: dict[str, Any] = {}
    for key, value in environ.items():
        if not key.startswith(ENV_PREFIX):
            continue
        parts = [p.lower() for p in key[len(ENV_PREFIX) :].split("__") if p]
        if not parts:
            continue
        node = tree
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                raise ConfigError(f"Environment override {key} conflicts with another override")
        node[parts[-1]] = value
    return tree


def _merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: Path | None = None, environ: Mapping[str, str] | None = None) -> AppConfig:
    """Load config from YAML (if present) and apply APP__ env overrides."""
    path = path or DEFAULT_CONFIG_PATH
    environ = os.environ if environ is None else environ
    data: dict[str, Any] = {}
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ConfigError(f"{path} must contain a mapping at the top level")
        data = loaded
    data = _merge(data, _env_overrides(environ))
    try:
        return AppConfig.model_validate(data)
    except ValueError as exc:
        raise ConfigError(f"Invalid configuration: {exc}") from exc


def is_loopback_host(host: str) -> bool:
    """True only for loopback addresses. 0.0.0.0 and :: are wildcards, not loopback."""
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False
