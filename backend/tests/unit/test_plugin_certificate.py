"""Owner 2026-11-02: a plugin package carries this server's self-signed certificate by
default only when people reach the server directly; behind a reverse proxy, or when the
public address is not a name on that certificate, it is off, with the reason shown."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.api.plugins import cert_names, certificate
from app.auth.tls import ensure_self_signed
from app.core.config import load_config


def _request(tmp_path: Path, public_url: str | None, proxies: str = "") -> Any:
    env = {
        "APP__SERVER__HOST": "0.0.0.0",  # a non-loopback bind, as served
        "APP__SERVER__PUBLIC_NAMES": "siem.internal",
        "APP__PATHS__DATA_DIR": str(tmp_path),
    }
    if proxies:
        env["APP__SERVER__TRUSTED_PROXIES"] = proxies
    config = load_config(environ=env)
    ensure_self_signed(tmp_path / "tls", ["siem.internal"])
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(config=config, public_url=public_url))
    )


def test_direct_access_to_its_own_certificate_includes_it(tmp_path: Path) -> None:
    c = certificate(_request(tmp_path, "https://siem.internal:8080"))
    assert c.self_signed and c.include_by_default and "siem.internal" in c.names
    assert c.reason.startswith("On:")


def test_behind_a_reverse_proxy_it_is_off(tmp_path: Path) -> None:
    c = certificate(_request(tmp_path, "https://siem.internal", proxies="10.0.0.5"))
    assert c.self_signed and not c.include_by_default and c.behind_proxy
    assert "reverse proxy" in c.reason


def test_a_public_name_not_on_the_certificate_is_off(tmp_path: Path) -> None:
    c = certificate(_request(tmp_path, "https://logs.example.com"))
    assert not c.include_by_default and "logs.example.com" in c.reason


def test_names_come_from_the_certificate(tmp_path: Path) -> None:
    files = ensure_self_signed(tmp_path / "tls", ["siem.internal", "192.0.2.10"])
    assert "siem.internal" in cert_names(files.cert.read_bytes())
