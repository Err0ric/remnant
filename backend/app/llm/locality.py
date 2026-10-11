"""Is a provider URL local or cloud? (SPEC 6.1)

Local only when every address the host resolves to is loopback, link-local, or private
(RFC 1918, IPv6 unique local), or the host is on the admin's trusted list and resolves.
Anything else, including lookup failures and odd schemes, is cloud: the classification gate then
blocks local-only data from it. Computed at call time, never cached.
"""

import ipaddress
import socket
from dataclasses import dataclass, replace
from typing import Literal
from urllib.parse import urlsplit

# Explicit, not ipaddress.is_private: that also covers documentation, reserved, and
# other special ranges that are not a LAN. Carrier-grade NAT (100.64/10) is excluded.
_LOCAL_NETWORKS = tuple(
    ipaddress.ip_network(n)
    for n in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
)


def _private(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return any(ip in net for net in _LOCAL_NETWORKS if net.version == ip.version)


@dataclass(frozen=True, slots=True)
class Endpoint:
    """Where a provider call may connect. `pin` is the address the locality decision was
    made on; the adapter connects to it instead of resolving the name again, so a DNS
    answer that changes between the check and the connection cannot redirect local-only
    data to a public host (DNS rebinding)."""

    locality: Literal["local", "cloud"]
    pin: str | None = None
    # False when the host name did not resolve: shown to the admin as the reason it counts
    # as cloud (for example the compose Ollama service is not running). Never changes the
    # locality itself.
    host_found: bool = True


# Provider kinds that are cloud services whatever their URL resolves to (SPEC 6.1).
ALWAYS_CLOUD_KINDS = frozenset({"anthropic"})


def provider_endpoint(kind: str, url: str, trusted_local_hosts: list[str]) -> Endpoint:
    """The endpoint for a configured provider: its URL's locality, except that kinds which
    are always cloud stay cloud even behind a local address."""
    endpoint = resolve_endpoint(url, trusted_local_hosts)
    if kind in ALWAYS_CLOUD_KINDS and endpoint.locality != "cloud":
        return replace(endpoint, locality="cloud")
    return endpoint


def compute_locality(url: str, trusted_local_hosts: list[str]) -> Literal["local", "cloud"]:
    return resolve_endpoint(url, trusted_local_hosts).locality


def resolve_endpoint(url: str, trusted_local_hosts: list[str]) -> Endpoint:
    cloud = Endpoint("cloud")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return cloud
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host:
        return cloud
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        return Endpoint("local") if _private(literal) else cloud
    trusted = host in {h.lower() for h in trusted_local_hosts}
    try:
        infos = socket.getaddrinfo(host, port or 443, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError):
        # No address to pin, so nothing proves the connection stays local.
        return Endpoint("cloud", host_found=False)
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        try:
            addresses.append(ipaddress.ip_address(str(info[4][0]).split("%", 1)[0]))
        except ValueError:
            return cloud
    if not addresses:
        return Endpoint("cloud", host_found=False)
    pin = str(sorted(addresses, key=lambda a: (a.version, int(a)))[0])
    if trusted:
        return Endpoint("local", pin)
    if all(_private(a) for a in addresses):
        return Endpoint("local", pin)
    return cloud
