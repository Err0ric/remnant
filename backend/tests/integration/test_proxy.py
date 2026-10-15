"""Outbound proxy and CA bundle (ADR-0018): a real CONNECT proxy and an HTTPS server whose
certificate comes from a test CA, so the proxy, its credentials, and the CA bundle are
exercised together. Nothing here leaves the machine."""

import base64
import datetime as dt
import http.server
import json
import select
import socket
import socketserver
import ssl
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

import app.alerts.net as net
from app.alerts.net import Egress, configure_egress
from app.alerts.send import post
from app.core.config import NetworkConfig
from app.ingest.connectors.anthropic import AnthropicClient
from app.ingest.connectors.base import ConnectorError

HOST = "api.anthropic.com"


def _cert(tmp: Path) -> tuple[Path, Path, Path]:
    now = dt.datetime.now(dt.UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test inspection CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(1)
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, HOST)]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(2)
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=2))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(HOST), x509.DNSName("hooks.slack.com")]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    ca_pem, crt, key_pem = tmp / "ca.pem", tmp / "leaf.pem", tmp / "leaf.key"
    ca_pem.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    crt.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    key_pem.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return ca_pem, crt, key_pem


class _Api(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # http.server's name
        body = json.dumps({"data": [], "has_more": False, "path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args: Any) -> None:
        pass


class _Proxy(socketserver.BaseRequestHandler):
    """CONNECT only; every tunnel goes to the test HTTPS server whatever the host asked."""

    seen: ClassVar[list[tuple[str, str | None]]] = []
    upstream = ("127.0.0.1", 0)

    def handle(self) -> None:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self.request.recv(4096)
            if not chunk:
                return
            data += chunk
        head = data.split(b"\r\n\r\n", 1)[0].decode()
        lines = head.split("\r\n")
        method, target, _ = lines[0].split(" ")
        auth = next(
            (
                ln.split(":", 1)[1].strip()
                for ln in lines[1:]
                if ln.lower().startswith("proxy-authorization")
            ),
            None,
        )
        type(self).seen.append((f"{method} {target}", auth))
        if method != "CONNECT":
            self.request.sendall(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            return
        up = socket.create_connection(self.upstream)
        self.request.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
        socks = [self.request, up]
        while True:
            ready, _, _ = select.select(socks, [], [], 5)
            if not ready:
                break
            for s in ready:
                buf = s.recv(65536)
                if not buf:
                    up.close()
                    return
                (up if s is self.request else self.request).sendall(buf)


@pytest.fixture
def lab(tmp_path: Path) -> Iterator[dict[str, Any]]:
    ca, crt, key = _cert(tmp_path)
    api = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Api)
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(crt, key)
    api.socket = ctx.wrap_socket(api.socket, server_side=True)
    threading.Thread(target=api.serve_forever, daemon=True).start()
    _Proxy.seen = []
    _Proxy.upstream = ("127.0.0.1", api.server_address[1])
    proxy = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Proxy)
    proxy.daemon_threads = True
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{proxy.server_address[1]}"
    yield {"ca": ca, "proxy": url}
    configure_egress(Egress())
    api.shutdown()
    proxy.shutdown()


def test_connector_goes_through_the_proxy_by_name_with_credentials_and_ca(
    lab: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_dns(host: str, port: int) -> list[Any]:
        raise AssertionError("no local DNS through the proxy")

    monkeypatch.setattr(net, "_resolve", no_dns)
    configure_egress(
        Egress(https_proxy=lab["proxy"], username="svc", password="pw", ca_bundle=str(lab["ca"]))
    )
    data = AnthropicClient("sk-ant-admin01-x").get(
        "/v1/organizations/cost_report", [("limit", "1")]
    )
    assert data["path"].startswith("/v1/organizations/cost_report")
    ((line, auth),) = _Proxy.seen
    assert line == f"CONNECT {HOST}:443"
    assert auth == "Basic " + base64.b64encode(b"svc:pw").decode()


def test_without_the_ca_bundle_an_inspecting_proxy_is_refused(lab: dict[str, Any]) -> None:
    configure_egress(Egress(https_proxy=lab["proxy"]))
    with pytest.raises(ConnectorError, match="Cannot reach"):
        AnthropicClient("sk-ant-admin01-x").get("/v1/organizations/cost_report", [])


def test_slack_alerts_use_the_proxy_and_generic_webhooks_never_do(
    lab: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_egress(Egress(https_proxy=lab["proxy"], ca_bundle=str(lab["ca"])))
    dest = net.destination("slack", "https://hooks.slack.com/services/T0/B0/x")
    assert dest.pin == ""
    assert post(dest, b"{}", {"Content-Type": "application/json"}) == 200
    assert _Proxy.seen[-1][0] == "CONNECT hooks.slack.com:443"
    # A generic webhook is checked and pinned as before, never sent to the proxy.
    monkeypatch.setattr(net, "_resolve", lambda h, p: [net.ipaddress.ip_address("10.0.0.5")])
    hook = net.destination("webhook", "http://hooks.internal.example/x")
    assert hook.pin == "10.0.0.5"


def test_proxy_config_is_validated(tmp_path: Path) -> None:
    for bad in ("http://user:pw@proxy:3128", "socks5://proxy:1080", "proxy:3128"):
        with pytest.raises(ValueError):
            NetworkConfig(https_proxy=bad)
    with pytest.raises(ValueError, match="both"):
        NetworkConfig(https_proxy="http://proxy:3128", proxy_username="svc")
    with pytest.raises(ValueError, match="not a file"):
        NetworkConfig(ca_bundle=tmp_path / "missing.pem")
    ok = NetworkConfig(https_proxy="http://proxy.corp.example:3128/")
    assert ok.https_proxy == "http://proxy.corp.example:3128"
