"""D157: documentation ranges are not public unless the demo setting is on."""

import ipaddress
from collections.abc import Iterator

import pytest

from app.core.config import load_config
from app.enrich import geoip


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    yield
    geoip.place_documentation_ranges(False)


@pytest.mark.parametrize("addr", ["192.0.2.10", "198.51.100.7", "203.0.113.59", "2001:db8::7"])
def test_documentation_ranges_are_placed_only_when_turned_on(addr: str) -> None:
    ip = ipaddress.ip_address(addr)
    assert not geoip.is_public(ip)
    geoip.place_documentation_ranges(True)
    assert geoip.is_public(ip)


def test_private_addresses_stay_private_with_the_setting_on() -> None:
    geoip.place_documentation_ranges(True)
    for addr in ("10.20.1.5", "192.168.1.1", "127.0.0.1", "fd00::1"):
        assert not geoip.is_public(ipaddress.ip_address(addr))
    assert geoip.is_public(ipaddress.ip_address("8.8.8.8"))


def test_the_setting_defaults_off_and_reads_from_the_environment() -> None:
    assert load_config(environ={}).enrichment.place_documentation_ranges is False
    env = {"APP__ENRICHMENT__PLACE_DOCUMENTATION_RANGES": "true"}
    assert load_config(environ=env).enrichment.place_documentation_ranges is True
