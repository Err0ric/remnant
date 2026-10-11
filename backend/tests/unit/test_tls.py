"""TLS bootstrap: HTTPS by default off loopback (ADR-0001 item 4, SPEC 3.6)."""

import stat
from pathlib import Path

import pytest
from cryptography import x509

from app.auth.tls import ensure_self_signed, resolve_tls
from app.core.config import load_config
from app.core.errors import ConfigError


def cfg(tmp_path: Path, **env: str):  # type: ignore[no-untyped-def]  # test helper
    base = {"APP__PATHS__DATA_DIR": str(tmp_path / "data")}
    return load_config(Path("missing.yaml"), base | env)


def test_loopback_serves_plain_http(tmp_path: Path) -> None:
    assert resolve_tls(cfg(tmp_path)) is None


def test_non_loopback_generates_self_signed(tmp_path: Path) -> None:
    tls = resolve_tls(cfg(tmp_path, APP__SERVER__HOST="0.0.0.0"))
    assert tls is not None
    assert tls.self_signed
    assert tls.cert.exists()
    assert stat.S_IMODE(tls.key.stat().st_mode) == 0o600
    assert len(tls.fingerprint_sha256.split(":")) == 32


def test_certificate_reused_across_restarts(tmp_path: Path) -> None:
    first = ensure_self_signed(tmp_path / "tls", ["siem.example.internal"])
    second = ensure_self_signed(tmp_path / "tls", ["siem.example.internal"])
    assert first.fingerprint_sha256 == second.fingerprint_sha256


def test_san_includes_configured_names_and_ips(tmp_path: Path) -> None:
    tls = ensure_self_signed(tmp_path / "tls", ["siem.example.internal", "192.0.2.10"])
    cert = x509.load_pem_x509_certificate(tls.cert.read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "siem.example.internal" in san.get_values_for_type(x509.DNSName)
    assert "localhost" in san.get_values_for_type(x509.DNSName)
    assert "192.0.2.10" in {str(ip) for ip in san.get_values_for_type(x509.IPAddress)}


def test_bring_your_own_certificate(tmp_path: Path) -> None:
    own = ensure_self_signed(tmp_path / "own", ["siem.example.internal"])
    tls = resolve_tls(
        cfg(
            tmp_path,
            APP__SERVER__HOST="0.0.0.0",
            APP__SERVER__TLS_CERT=str(own.cert),
            APP__SERVER__TLS_KEY=str(own.key),
        )
    )
    assert tls is not None
    assert not tls.self_signed
    assert tls.cert == own.cert
    assert not (tmp_path / "data" / "tls").exists()


def test_cert_without_key_is_an_error(tmp_path: Path) -> None:
    own = ensure_self_signed(tmp_path / "own", [])
    with pytest.raises(ConfigError, match="both"):
        resolve_tls(cfg(tmp_path, APP__SERVER__HOST="0.0.0.0", APP__SERVER__TLS_CERT=str(own.cert)))


def test_missing_cert_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        resolve_tls(
            cfg(
                tmp_path,
                APP__SERVER__HOST="0.0.0.0",
                APP__SERVER__TLS_CERT=str(tmp_path / "nope.pem"),
                APP__SERVER__TLS_KEY=str(tmp_path / "nope.key"),
            )
        )
