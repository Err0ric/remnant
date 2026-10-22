"""The shipped example saved searches import, pass the guard, and answer on fixture data."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.main import create_app

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "examples" / "saved-searches"
FIX = Path(__file__).parent.parent / "fixtures" / "logs"
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
RANGE = {"start": "2026-10-09T00:00:00Z", "end": "2026-10-10T00:00:00Z"}


def _pan_dhcp(t: str, ip: str, mac: str, host: str) -> str:
    return (
        f"<14>Oct  9 {t} pa-fw01 1,2026/10/09 {t},012345678901,SYSTEM,dhcp,,2026/10/09 {t},vsys1,"
        f'lease-start,,,,general,informational,"DHCP lease started ip {ip} --> mac {mac} - '
        f'hostname {host}, interface ethernet1/2",,,,,,,,pa-fw01'
    )


def _dns(t: str, client: str, name: str) -> str:
    return (
        f"<30>Oct  9 {t} ns1 named[812]: client {client}#53212 ({name}): "
        f"query: {name} IN A +E(0)K (10.20.0.53)"
    )


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Any:
    tmp = tmp_path_factory.mktemp("examples")
    logs = tmp / "logs"
    for sub in ("dns", "fw", "gp", "ssh"):
        (logs / sub).mkdir(parents=True)
    # 10.20.1.5 was LAPTOP-A until 12:00, then the address went to LAPTOP-B.
    (logs / "fw" / "system.log").write_text(
        "\n".join(
            [
                _pan_dhcp("08:00:00", "10.20.1.5", "00:00:5e:00:53:0a", "LAPTOP-A"),
                _pan_dhcp("12:00:00", "10.20.1.5", "00:00:5e:00:53:0b", "LAPTOP-B"),
                *(FIX / "paloalto_system" / "sample.log").read_text().splitlines(),
            ]
        )
        + "\n"
    )
    (logs / "dns" / "q.log").write_text(
        "\n".join(
            [
                _dns("09:00:00", "10.20.1.5", "chatgpt.com"),
                _dns("09:30:00", "10.20.1.5", "api.openai.com"),
                _dns("13:00:00", "10.20.1.5", "claude.ai"),
                _dns("13:05:00", "10.20.1.6", "bzr.openai.com"),  # an ad tag, not use
                _dns("13:10:00", "10.20.1.6", "www.example.com"),
            ]
        )
        + "\n"
    )
    (logs / "gp" / "gp.log").write_text((FIX / "paloalto_globalprotect" / "sample.log").read_text())
    (logs / "ssh" / "auth.log").write_text((FIX / "linux_sshd" / "sample.log").read_text())
    config = load_config(
        Path("missing.yaml"),
        {"APP__PATHS__DATA_DIR": str(tmp / "data"), "APP__PATHS__ALLOWED_ROOTS": str(logs)},
    )
    app = create_app(config)
    app.state.ingest._clock = lambda: NOW
    c = TestClient(app, base_url="http://127.0.0.1")
    for sid, tid, sub in (
        ("dns", "dns_bind", "dns"),
        ("fw", "paloalto_system", "fw"),
        ("gp", "paloalto_globalprotect", "gp"),
        ("ssh", "linux_sshd", "ssh"),
    ):
        body = {"source_id": sid, "format": "syslog", "path": str(logs / sub), "template_id": tid}
        assert c.post("/api/sources", json=body).status_code == 201
    app.state.ingest.run_once()
    for path in sorted(EXAMPLES.glob("*.yaml")):
        res = c.post("/api/searches/import", content=path.read_bytes())
        assert res.status_code == 201, (path.name, res.text)
    return c


def run(client: TestClient, search_id: str, **params: Any) -> dict[str, Any]:
    res = client.post(f"/api/searches/{search_id}/run", json={**RANGE, "params": params})
    assert res.status_code == 200, res.text
    body: dict[str, Any] = res.json()
    return body


def rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(zip(body["columns"], r, strict=True)) for r in body["rows"]]


def test_every_example_is_tagged_and_documented(client: TestClient) -> None:
    doc = (ROOT / "docs" / "searching.md").read_text()
    for path in EXAMPLES.glob("*.yaml"):
        assert path.stem in doc, f"{path.stem} is not in docs/searching.md"


def test_ai_services_from_dns(client: TestClient) -> None:
    got = {r["service"]: r for r in rows(run(client, "ai_services_dns"))}
    assert set(got) == {"ChatGPT", "OpenAI API", "Claude"}  # the ad tag is not use
    assert got["ChatGPT"]["queries"] == 1 and got["ChatGPT"]["clients"] == 1


def test_ai_services_by_device_follow_the_lease_at_the_time(client: TestClient) -> None:
    got = {(r["device"], r["service"]) for r in rows(run(client, "ai_services_by_device"))}
    assert got == {("LAPTOP-A", "ChatGPT"), ("LAPTOP-A", "OpenAI API"), ("LAPTOP-B", "Claude")}


def test_who_had_an_address(client: TestClient) -> None:
    dhcp = [r for r in rows(run(client, "who_had_ip", ip="10.20.1.5")) if r["kind"] == "DHCP lease"]
    assert [r["device"] for r in dhcp] == ["LAPTOP-B", "LAPTOP-A"]
    vpn = rows(run(client, "who_had_ip", ip="10.30.0.5"))
    assert vpn and all(r["kind"] == "VPN tunnel" and r["person"] for r in vpn)


@pytest.mark.parametrize("search_id", ["parser_mix", "ssh_logins", "firewall_maintenance"])
def test_summaries_return_rows(client: TestClient, search_id: str) -> None:
    assert run(client, search_id)["rows"], search_id
