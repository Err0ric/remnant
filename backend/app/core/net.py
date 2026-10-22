"""Client address behind trusted reverse proxies (ADR-0027, D77).

`X-Forwarded-For` is read only when the TCP peer is a listed proxy. Each proxy appends
the address it saw on the right, so the list is walked from the right, skipping
trusted proxies, and the first untrusted address is the client. Entries further left
were written by the client and are never believed.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable, Sequence

Network = ipaddress.IPv4Network | ipaddress.IPv6Network
Address = ipaddress.IPv4Address | ipaddress.IPv6Address


def parse_trusted(entries: Iterable[str]) -> tuple[Network, ...]:
    """IPs and CIDRs to networks. Raises ValueError on a bad entry or a catch-all range."""
    out: list[Network] = []
    for entry in entries:
        net = ipaddress.ip_network(entry.strip(), strict=False)
        if net.prefixlen == 0:
            raise ValueError(f"{entry} would trust every address")
        out.append(net)
    return tuple(out)


def _address(text: str) -> Address | None:
    try:
        addr = ipaddress.ip_address(text.strip())
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def _trusted(addr: Address, trusted: Sequence[Network]) -> bool:
    return any(addr.version == n.version and addr in n for n in trusted)


def client_address(peer: str, forwarded_for: Sequence[str], trusted: Sequence[Network]) -> str:
    """The client's address: the peer, or from X-Forwarded-For when the peer is trusted."""
    peer_addr = _address(peer)
    if not trusted or peer_addr is None or not _trusted(peer_addr, trusted):
        return peer
    hops = [h for line in forwarded_for for h in line.split(",") if h.strip()]
    chosen = peer
    for hop in reversed(hops):
        addr = _address(hop)
        if addr is None:
            return peer  # malformed: believe nothing from this header
        chosen = str(addr)
        if not _trusted(addr, trusted):
            return chosen
    return chosen  # every entry trusted: the leftmost
