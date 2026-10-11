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
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from app.core.errors import ParamInvalidError

Kind = Literal["slack", "teams", "webhook"]
MAX_URL = 2_048
TEAMS_SUFFIXES = (".logic.azure.com", ".api.powerplatform.com")
_REFUSED = tuple(
    ipaddress.ip_network(n)
    for n in ("169.254.0.0/16", "fe80::/10", "fd00:ec2::254/128", "0.0.0.0/8", "::/128")
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


def _norm(ip: Address) -> Address:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
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
