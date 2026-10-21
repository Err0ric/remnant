"""HTTPS bootstrap (ADR-0001 item 4, SPEC 3.6).

Loopback binds serve plain HTTP. Any other bind serves HTTPS: the admin's own
certificate if configured, otherwise a self-signed one generated once in
`<data_dir>/tls/` and reused across restarts. There is no switch to serve plain
HTTP off loopback; a reverse proxy on the same host should talk to a loopback bind.
"""

import ipaddress
import os
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.core.branding import PRODUCT_NAME
from app.core.config import AppConfig, is_loopback_host
from app.core.errors import ConfigError

CERT_NAME = "server.crt"
KEY_NAME = "server.key"
VALID_DAYS = 825  # the longest validity common clients accept for a server certificate


@dataclass(frozen=True, slots=True)
class TlsFiles:
    cert: Path
    key: Path
    self_signed: bool
    fingerprint_sha256: str


def resolve_tls(config: AppConfig) -> TlsFiles | None:
    """TLS files to serve with, or None for a loopback bind (plain HTTP)."""
    server = config.server
    if is_loopback_host(server.host):
        return None
    if (server.tls_cert is None) != (server.tls_key is None):
        raise ConfigError("Set both server.tls_cert and server.tls_key, or neither")
    if server.tls_cert is not None and server.tls_key is not None:
        for path in (server.tls_cert, server.tls_key):
            if not path.is_file():
                raise ConfigError(f"TLS file not found: {path}")
        cert = x509.load_pem_x509_certificate(server.tls_cert.read_bytes())
        return TlsFiles(server.tls_cert, server.tls_key, False, _fingerprint(cert))
    return ensure_self_signed(config.paths.data_dir / "tls", server.public_names)


def ensure_self_signed(folder: Path, names: list[str]) -> TlsFiles:
    """Create a self-signed certificate once; later calls reuse it."""
    cert_path, key_path = folder / CERT_NAME, folder / KEY_NAME
    if cert_path.is_file() and key_path.is_file():
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        return TlsFiles(cert_path, key_path, True, _fingerprint(cert))

    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    key = ec.generate_private_key(ec.SECP256R1())
    dns, ips = _alt_names(names)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"{PRODUCT_NAME} self-signed")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=VALID_DAYS))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName(d) for d in dns] + [x509.IPAddress(i) for i in ips]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    key_bytes = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(key_bytes)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return TlsFiles(cert_path, key_path, True, _fingerprint(cert))


def _alt_names(
    names: list[str],
) -> tuple[list[str], list[ipaddress.IPv4Address | ipaddress.IPv6Address]]:
    dns: list[str] = []
    ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for name in ["localhost", "127.0.0.1", "::1", socket.gethostname(), *names]:
        name = name.strip()
        if not name:
            continue
        try:
            ip = ipaddress.ip_address(name)
        except ValueError:
            if name not in dns:
                dns.append(name)
        else:
            if ip not in ips:
                ips.append(ip)
    return dns, ips


def _fingerprint(cert: x509.Certificate) -> str:
    return ":".join(f"{b:02X}" for b in cert.fingerprint(hashes.SHA256()))
