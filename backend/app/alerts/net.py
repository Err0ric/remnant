"""Where alerts may be sent (ADR-0007 row 4).

Every destination is checked when it is saved and again before each send, and the
connection goes to the address the check approved (`pin`), so a DNS answer that changes
in between cannot move an alert somewhere else.

| Kind | Rule |
|---|---|
| slack | `https`, host `hooks.slack.com` |
| teams | `https`, a Workflows host (`*.logic.azure.com`, `*.api.powerplatform.com`) |
| webhook | `https` unless every address is private or loopback, where `http` is allowed |
| all | no credentials in the URL; link-local, metadata, unspecified, multicast refused |
"""

import ipaddress
import socket
import ssl
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

import httpx

from app.core.errors import ParamInvalidError

Kind = Literal["slack", "teams", "webhook"]
MAX_URL = 2_048
TEAMS_SUFFIXES = (".logic.azure.com", ".api.powerplatform.com")
_REFUSED = tuple(
    ipaddress.ip_network(n)
    for n in (
        "169.254.0.0/16",
        "fe80::/10",
        "fd00:ec2::254/128",
        "0.0.0.0/8",
        "::/128",
        "100.100.100.200/32",  # Alibaba Cloud instance metadata
    )
)
_PRIVATE = tuple(
    ipaddress.ip_network(n)
    for n in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128", "fc00::/7")
)

Address = ipaddress.IPv4Address | ipaddress.IPv6Address


@dataclass(frozen=True, slots=True)
class Destination:
    url: str
    scheme: str
    host: str
    port: int
    pin: str  # the approved address to connect to
    private: bool  # every address is private or loopback


_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _norm(ip: Address) -> Address:
    """The IPv4 address behind IPv4-mapped, NAT64, and 6to4 forms, so the rules below
    cannot be sidestepped by writing a refused IPv4 address as IPv6."""
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return ip.ipv4_mapped
        if ip in _NAT64:
            return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        if ip.sixtofour is not None:
            return ip.sixtofour
    return ip


def _in(ip: Address, nets: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]) -> bool:
    return any(ip in n for n in nets if n.version == ip.version)


def _resolve(host: str, port: int) -> list[Address]:
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        addresses = [literal]
    else:
        try:
            infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        except (OSError, UnicodeError) as exc:
            raise ParamInvalidError(f"Cannot resolve {host}") from exc
        addresses = []
        for info in infos:
            try:
                addresses.append(ipaddress.ip_address(str(info[4][0]).split("%", 1)[0]))
            except ValueError as exc:
                raise ParamInvalidError(f"Cannot resolve {host}") from exc
        if not addresses:
            raise ParamInvalidError(f"Cannot resolve {host}")
    addresses = [_norm(a) for a in addresses]
    for a in addresses:
        if _in(a, _REFUSED) or a.is_multicast or a.is_unspecified:
            raise ParamInvalidError(f"Address {a} is not allowed as a destination")
    return sorted(addresses, key=lambda a: (a.version, int(a)))


def check_url(kind: Kind, url: str) -> Destination:
    if len(url) > MAX_URL:
        raise ParamInvalidError("The URL is too long")
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError as exc:
        raise ParamInvalidError("The URL is not valid") from exc
    if parts.scheme not in ("http", "https"):
        raise ParamInvalidError(
            "The URL must start with https:// (or http:// for a private address)"
        )
    if parts.username is not None or parts.password is not None:
        raise ParamInvalidError("Put no credentials in the URL")
    host = (parts.hostname or "").lower()
    if not host:
        raise ParamInvalidError("The URL has no host")
    if kind == "slack" and host != "hooks.slack.com":
        raise ParamInvalidError("A Slack webhook URL must be on hooks.slack.com")
    if kind == "teams" and not host.endswith(TEAMS_SUFFIXES):
        raise ParamInvalidError(
            "A Teams URL must be a Workflows webhook (Power Automate); connector URLs were retired"
        )
    if kind in ("slack", "teams") and parts.scheme != "https":
        raise ParamInvalidError("This URL must use https")
    port = port or (443 if parts.scheme == "https" else 80)
    addresses = _resolve(host, port)
    private = all(_in(a, _PRIVATE) for a in addresses)
    if parts.scheme == "http" and not private:
        raise ParamInvalidError("Public addresses need https; http is only for private addresses")
    return Destination(url.strip(), parts.scheme, host, port, str(addresses[0]), private)


def check_smtp_host(
    host: str, port: int, security: Literal["starttls", "tls", "none"]
) -> Destination:
    host = host.strip().lower()
    if not host or len(host) > 253:
        raise ParamInvalidError("Give the SMTP server's host name")
    addresses = _resolve(host, port)
    loopback = all(a.is_loopback for a in addresses)
    if security == "none" and not loopback:
        raise ParamInvalidError(
            "SMTP needs TLS (STARTTLS or implicit) unless the relay is on this host"
        )
    return Destination(f"smtp://{host}:{port}", "smtp", host, port, str(addresses[0]), loopback)


# --- outbound proxy and CA bundle (ADR-0018) -----------------------------------------


@dataclass(frozen=True, slots=True)
class Egress:
    """Outbound settings from `network` config (ADR-0018). The proxy is used only by the
    fixed-host API connectors and Teams or Slack alerts; the CA bundle by both, proxied
    or not."""

    https_proxy: str | None = None
    username: str | None = None
    password: str | None = None
    ca_bundle: str | None = None

    def verify(self) -> ssl.SSLContext | bool:
        if not self.ca_bundle:
            return True
        ctx = ssl.create_default_context()
        ctx.load_verify_locations(cafile=self.ca_bundle)
        return ctx

    def proxy(self) -> httpx.Proxy | None:
        if not self.https_proxy:
            return None
        auth = (self.username, self.password) if self.username and self.password else None
        return httpx.Proxy(self.https_proxy, auth=auth)


_egress = Egress()


def configure_egress(egress: Egress) -> None:
    """Set once at start-up (and by tests)."""
    global _egress  # process-wide outbound settings, set at start-up
    _egress = egress


def egress() -> Egress:
    return _egress


def check_proxied(kind: Kind, url: str) -> Destination:
    """The checks of check_url that need no DNS, for a request sent through the proxy:
    https only, no credentials, and the kind's host rule. The proxy resolves the name."""
    if len(url) > MAX_URL:
        raise ParamInvalidError("The URL is too long")
    try:
        parts = urlsplit(url.strip())
        port = parts.port or 443
    except ValueError as exc:
        raise ParamInvalidError("The URL is not valid") from exc
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        raise ParamInvalidError("Through the proxy, the URL must start with https://")
    if parts.username is not None or parts.password is not None:
        raise ParamInvalidError("Put no credentials in the URL")
    if kind == "slack" and host != "hooks.slack.com":
        raise ParamInvalidError("A Slack webhook URL must be on hooks.slack.com")
    if kind == "teams" and not host.endswith(TEAMS_SUFFIXES):
        raise ParamInvalidError(
            "A Teams URL must be a Workflows webhook (Power Automate); connector URLs were retired"
        )
    if kind == "webhook":
        raise ParamInvalidError("Generic webhooks are sent directly, not through the proxy")
    return Destination(url.strip(), "https", host, port, "", False)


def destination(kind: Kind, url: str) -> Destination:
    """Where an alert goes: through the proxy for Teams and Slack when one is set (no
    pin), else checked and pinned as usual."""
    if kind in ("teams", "slack") and _egress.https_proxy:
        return check_proxied(kind, url)
    return check_url(kind, url)
