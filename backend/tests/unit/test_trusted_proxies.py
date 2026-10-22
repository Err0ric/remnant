"""Client address behind a reverse proxy (ADR-0027, D77)."""

import pytest
from pydantic import ValidationError

from app.core.config import ServerConfig
from app.core.net import Network, client_address, parse_trusted

HA_PAIR = parse_trusted(["192.0.2.10", "192.0.2.11", "192.0.2.20"])  # two nodes and a VIP
SUBNET = parse_trusted(["192.0.2.0/28", "2001:db8::/64"])


@pytest.mark.parametrize(
    ("peer", "headers", "trusted", "expected"),
    [
        # Default (empty list): the header is never read.
        ("198.51.100.5", ["198.51.100.7"], parse_trusted([]), "198.51.100.5"),
        # Untrusted peer with a spoofed header: ignored.
        ("203.0.113.9", ["198.51.100.7"], HA_PAIR, "203.0.113.9"),
        # Trusted node of the HA pair: the client from the header.
        ("192.0.2.11", ["198.51.100.7"], HA_PAIR, "198.51.100.7"),
        # A client-written entry on the left is not believed: rightmost untrusted wins.
        ("192.0.2.10", ["6.6.6.6, 198.51.100.7"], HA_PAIR, "198.51.100.7"),
        # Two trusted proxies in a chain resolve to the real client.
        ("192.0.2.10", ["198.51.100.7, 192.0.2.20"], HA_PAIR, "198.51.100.7"),
        # Several header lines are read in order, as one list.
        ("192.0.2.10", ["6.6.6.6", "198.51.100.7, 192.0.2.11"], HA_PAIR, "198.51.100.7"),
        # Every entry trusted: the leftmost.
        ("192.0.2.10", ["192.0.2.11, 192.0.2.20"], HA_PAIR, "192.0.2.11"),
        # A malformed entry stops the walk: the peer is used.
        ("192.0.2.10", ["198.51.100.7, not-an-ip"], HA_PAIR, "192.0.2.10"),
        # No header from a trusted peer: the peer.
        ("192.0.2.10", [], HA_PAIR, "192.0.2.10"),
        # CIDRs, IPv6, and an IPv4-mapped peer.
        ("192.0.2.3", ["198.51.100.7"], SUBNET, "198.51.100.7"),
        ("2001:db8::5", ["2001:db8:1::9"], SUBNET, "2001:db8:1::9"),
        ("::ffff:192.0.2.3", ["198.51.100.7"], SUBNET, "198.51.100.7"),
        # Ports are not part of the address; whitespace is ignored.
        ("192.0.2.10", ["  198.51.100.7  "], HA_PAIR, "198.51.100.7"),
    ],
)
def test_client_address(
    peer: str, headers: list[str], trusted: tuple[Network, ...], expected: str
) -> None:
    assert client_address(peer, headers, trusted) == expected


@pytest.mark.parametrize("bad", ["not-an-ip", "192.0.2.0/33", "0.0.0.0/0", "::/0"])
def test_invalid_or_catch_all_entries_refuse_to_start(bad: str) -> None:
    with pytest.raises(ValidationError, match="trusted_proxies"):
        ServerConfig(trusted_proxies=[bad])


def test_env_form_is_comma_separated() -> None:
    cfg = ServerConfig.model_validate({"trusted_proxies": "192.0.2.10, 192.0.2.11,2001:db8::/64"})
    assert cfg.trusted_proxies == ["192.0.2.10", "192.0.2.11", "2001:db8::/64"]
