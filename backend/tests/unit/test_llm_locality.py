"""Provider locality from the URL (SPEC 6.1): local only if every resolved address is private."""

import socket

import pytest

from app.llm.locality import compute_locality


def fake_resolver(mapping: dict[str, list[str]]):  # type: ignore[no-untyped-def]  # test helper
    def getaddrinfo(host: str, *_: object, **__: object) -> list[tuple[object, ...]]:
        if host not in mapping:
            raise socket.gaierror("unknown host")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in mapping[host]]

    return getaddrinfo


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://127.0.0.1:11434", "local"),
        ("http://localhost:11434", "local"),
        ("http://[::1]:11434", "local"),
        ("http://10.0.0.5:8000", "local"),
        ("http://192.168.1.20:1234", "local"),
        ("http://172.16.4.2", "local"),
        ("http://169.254.10.10", "local"),
        ("http://ollama:11434", "local"),  # compose service name on a private network
        ("https://api.openai.com/v1", "cloud"),
        ("https://unresolvable.invalid", "cloud"),  # fail closed
        ("http://mixed.example", "cloud"),  # one public address is enough to be cloud
        ("http://100.64.0.10", "cloud"),  # carrier-grade NAT is not a private LAN
    ],
)
def test_locality(url: str, expected: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        fake_resolver(
            {
                "localhost": ["127.0.0.1"],
                "ollama": ["172.18.0.3"],
                "api.openai.com": ["104.18.33.45"],
                "mixed.example": ["10.0.0.9", "8.8.8.8"],
            }
        ),
    )
    assert compute_locality(url, trusted_local_hosts=[]) == expected


def test_trusted_host_is_local_even_if_public(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket, "getaddrinfo", fake_resolver({"gpu.corp.example": ["198.51.100.20"]})
    )
    assert (
        compute_locality("https://gpu.corp.example", trusted_local_hosts=["GPU.corp.example"])
        == "local"
    )
    assert compute_locality("https://gpu.corp.example", trusted_local_hosts=[]) == "cloud"


@pytest.mark.parametrize("url", ["ftp://127.0.0.1", "file:///etc/passwd", "http://", "not a url"])
def test_bad_urls_are_cloud(url: str) -> None:
    assert compute_locality(url, trusted_local_hosts=[]) == "cloud"


@pytest.mark.parametrize(
    "ip", ["192.0.2.10", "198.51.100.7", "203.0.113.9", "0.0.0.0", "240.0.0.1", "::ffff:8.8.8.8"]
)
def test_special_but_non_lan_ranges_are_cloud(ip: str) -> None:
    host = f"[{ip}]" if ":" in ip else ip
    assert compute_locality(f"http://{host}:1", trusted_local_hosts=[]) == "cloud"


def test_ipv4_mapped_private_is_local() -> None:
    assert compute_locality("http://[::ffff:10.0.0.5]:1", trusted_local_hosts=[]) == "local"


def test_trusted_host_that_does_not_resolve_is_cloud(monkeypatch: pytest.MonkeyPatch) -> None:
    # Nothing to pin, so a later lookup could point anywhere.
    monkeypatch.setattr(socket, "getaddrinfo", fake_resolver({}))
    assert (
        compute_locality("http://gpu.corp.example", trusted_local_hosts=["gpu.corp.example"])
        == "cloud"
    )


def test_a_host_that_does_not_resolve_is_cloud_and_says_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.llm.locality import resolve_endpoint

    monkeypatch.setattr(socket, "getaddrinfo", fake_resolver({"api.openai.com": ["104.18.33.45"]}))
    missing = resolve_endpoint("http://ollama:11434/v1", [])
    assert missing.locality == "cloud" and missing.host_found is False  # still fails closed
    public = resolve_endpoint("https://api.openai.com/v1", [])
    assert public.locality == "cloud" and public.host_found is True
    literal = resolve_endpoint("http://192.168.1.50:11434/v1", [])
    assert literal.locality == "local" and literal.host_found is True
