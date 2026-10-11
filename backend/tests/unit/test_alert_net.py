"""Alert destination address rules (ADR-0007 row 4)."""

import socket
from typing import Any

import pytest

from app.alerts.net import Destination, check_smtp_host, check_url
from app.core.errors import ParamInvalidError


def fake_dns(monkeypatch: pytest.MonkeyPatch, table: dict[str, list[str]]) -> None:
    def getaddrinfo(host: str, port: Any, *a: Any, **k: Any) -> list[Any]:
        if host not in table:
            raise socket.gaierror("no such host")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in table[host]]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


DNS = {
    "hooks.slack.com": ["198.51.100.10"],
    "prod-01.westus.logic.azure.com": ["198.51.100.20"],
    "default1234.ab.environment.api.powerplatform.com": ["198.51.100.21"],
    "ntfy.lan": ["192.168.1.50"],
    "relay.example.net": ["203.0.113.30"],
    "mixed.example.net": ["192.168.1.9", "203.0.113.31"],
    "meta.example.net": ["169.254.169.254"],
    "evil.hooks.slack.com.example.net": ["203.0.113.32"],
}


@pytest.mark.parametrize(
    ("kind", "url", "pin"),
    [
        ("slack", "https://hooks.slack.com/services/T0/B0/XYZ", "198.51.100.10"),
        (
            "teams",
            "https://prod-01.westus.logic.azure.com:443/workflows/abc/triggers/manual/paths/invoke?sig=x",
            "198.51.100.20",
        ),
        (
            "teams",
            "https://default1234.ab.environment.api.powerplatform.com/powerautomate/automations/direct/workflows/x",
            "198.51.100.21",
        ),
        ("webhook", "http://ntfy.lan/alerts", "192.168.1.50"),
        ("webhook", "http://127.0.0.1:8085/hook", "127.0.0.1"),
        ("webhook", "https://relay.example.net/hook", "203.0.113.30"),
    ],
)
def test_allowed_destinations_are_pinned(
    monkeypatch: pytest.MonkeyPatch, kind: str, url: str, pin: str
) -> None:
    fake_dns(monkeypatch, DNS)
    d = check_url(kind, url)  # type: ignore[arg-type]  # literal from the table
    assert isinstance(d, Destination) and d.pin == pin


@pytest.mark.parametrize(
    ("kind", "url", "reason"),
    [
        ("slack", "http://hooks.slack.com/services/x", "https"),
        ("slack", "https://evil.hooks.slack.com.example.net/x", "hooks.slack.com"),
        ("teams", "https://outlook.office.com/webhook/x", "Workflows"),
        ("webhook", "http://relay.example.net/hook", "https"),  # public needs TLS
        ("webhook", "http://mixed.example.net/hook", "https"),  # any public address counts
        ("webhook", "https://meta.example.net/latest", "not allowed"),
        ("webhook", "http://169.254.169.254/latest/meta-data", "not allowed"),
        ("webhook", "http://[fd00:ec2::254]/", "not allowed"),
        ("webhook", "http://[fe80::1]/", "not allowed"),
        ("webhook", "http://0.0.0.0/", "not allowed"),
        ("webhook", "https://user:pw@relay.example.net/", "credentials"),
        ("webhook", "ftp://relay.example.net/", "http"),
        ("webhook", "https://nowhere.invalid/", "resolve"),
        ("webhook", "https:///nohost", "host"),
        ("webhook", "https://relay.example.net/" + "a" * 3000, "long"),
    ],
)
def test_refused_destinations(
    monkeypatch: pytest.MonkeyPatch, kind: str, url: str, reason: str
) -> None:
    fake_dns(monkeypatch, DNS)
    with pytest.raises(ParamInvalidError, match=reason):
        check_url(kind, url)  # type: ignore[arg-type]  # literal from the table


def test_smtp_needs_tls_except_on_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_dns(monkeypatch, {**DNS, "smtp.example.net": ["203.0.113.40"], "localhost": ["127.0.0.1"]})
    assert check_smtp_host("smtp.example.net", 587, "starttls").pin == "203.0.113.40"
    assert check_smtp_host("localhost", 25, "none").pin == "127.0.0.1"
    with pytest.raises(ParamInvalidError, match="TLS"):
        check_smtp_host("smtp.example.net", 25, "none")
    with pytest.raises(ParamInvalidError, match="not allowed"):
        check_smtp_host("meta.example.net", 587, "starttls")
