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
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

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

    _split_names = field_validator("public_names", mode="before")(_split_list)


class AuthConfig(_Strict):
    session_hours: int = Field(default=12, ge=1, le=24 * 7)
    cli_token_days: int = Field(default=30, ge=1, le=365)
    login_max_failures: int = Field(default=5, ge=1, le=100)
    login_window_s: int = Field(default=300, ge=10, le=86400)


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

    _split_hosts = field_validator("trusted_local_hosts", mode="before")(_split_list)


class MaintenanceConfig(_Strict):
    enabled: bool = True
    compaction_interval_s: float = Field(default=3600, ge=60)
    retention_interval_s: float = Field(default=86400, ge=60)
    # Retention for data whose source was removed from the configuration.
    orphan_retention_days: int = Field(default=30, ge=1, le=3650)


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


class AppConfig(_Strict):
    server: ServerConfig = Field(default_factory=ServerConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    ingest: IngestConfig = Field(default_factory=IngestConfig)
    maintenance: MaintenanceConfig = Field(default_factory=MaintenanceConfig)
    schedules: SchedulesConfig = Field(default_factory=SchedulesConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)


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
