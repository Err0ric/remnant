from pathlib import Path

import pytest

from app.core.config import (
    AppConfig,
    is_loopback_host,
    load_config,
)
from app.core.errors import ConfigError


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.53", "localhost", "::1", "[::1]"])
def test_loopback_hosts(host: str) -> None:
    assert is_loopback_host(host)


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10", "10.0.0.5", "example.com"])
def test_non_loopback_hosts(host: str) -> None:
    assert not is_loopback_host(host)


def test_default_config_binds_localhost() -> None:
    assert AppConfig().server.host == "127.0.0.1"


def test_no_insecure_switch_exists() -> None:
    # Security rule 7: there is no flag that opens a network bind without accounts.
    with pytest.raises(ConfigError):
        load_config(Path("missing.yaml"), {"APP__AUTH__API_TOKEN": "x"})


def test_yaml_then_env_override(tmp_path: Path) -> None:
    cfg = tmp_path / "app.yaml"
    cfg.write_text("server:\n  host: 127.0.0.1\n  port: 9000\n", encoding="utf-8")
    config = load_config(cfg, {"APP__SERVER__PORT": "9100"})
    assert config.server.port == 9100


def test_unknown_keys_rejected(tmp_path: Path) -> None:
    cfg = tmp_path / "app.yaml"
    cfg.write_text("server:\n  insecure: true\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(cfg, {})
