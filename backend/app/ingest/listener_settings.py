"""Settings of a syslog listener source (ADR-0021 rows 1 and 4)."""

from __future__ import annotations

import ipaddress
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# The default when an admin lists no senders: the LAN, never the internet (row 4).
PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(n)
    for n in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "100.64.0.0/10",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
)

Network = ipaddress.IPv4Network | ipaddress.IPv6Network


class SyslogSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol: Literal["udp", "tcp", "tls"] = "udp"
    port: int = Field(default=5514, ge=1024, le=65535)
    # Addresses or networks allowed to send. Empty means private, loopback, and
    # link-local addresses only; `0.0.0.0/0` and `::/0` accept anyone.
    allowed_senders: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("allowed_senders")
    @classmethod
    def _networks(cls, value: list[str]) -> list[str]:
        out = []
        for item in value:
            try:
                out.append(str(ipaddress.ip_network(item.strip(), strict=False)))
            except ValueError as exc:
                raise ValueError(f"Not an address or network: {item[:60]}") from exc
        return out

    def networks(self) -> tuple[Network, ...]:
        if not self.allowed_senders:
            return PRIVATE_NETWORKS
        return tuple(ipaddress.ip_network(n) for n in self.allowed_senders)

    def allows(self, address: str) -> bool:
        try:
            ip = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError:
            return False
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        return any(ip.version == n.version and ip in n for n in self.networks())
