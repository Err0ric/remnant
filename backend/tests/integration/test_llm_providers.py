"""Provider registry and admin API: keys encrypted at rest, never returned, cloud acknowledged."""

import socket
import sqlite3
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.main import create_app

ADMIN_PW = "correct horse battery"
BASE = "https://siem.example.internal"
KEY = "sk-live-very-secret-123"


@pytest.fixture(autouse=True)
def _dns(monkeypatch: pytest.MonkeyPatch) -> None:
    table = {"ollama": "172.18.0.3", "api.example-cloud.com": "104.18.33.45"}

    def getaddrinfo(host: str, *_: object, **__: object) -> list[tuple[object, ...]]:
        if host not in table:
            raise socket.gaierror("unknown")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (table[host], 0))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


def admin(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    config = load_config(
        Path("missing.yaml"),
        {"APP__PATHS__DATA_DIR": str(tmp_path / "data"), "APP__SERVER__HOST": "0.0.0.0"},
    )
    app = create_app(config)
    c = TestClient(app, base_url=BASE)
    token = app.state.auth.setup_url("siem.example.internal", 8080).split("#", 1)[1]
    csrf = c.post(
        "/api/setup", json={"token": token, "username": "admin", "password": ADMIN_PW}
    ).json()["csrf_token"]
    return c, {"X-CSRF-Token": csrf}


def test_fresh_install_has_one_disabled_local_ollama_entry(tmp_path: Path) -> None:
    c, _ = admin(tmp_path)
    providers = c.get("/api/providers").json()
    assert len(providers) == 1
    p = providers[0]
    assert p["base_url"] == "http://ollama:11434/v1"
    assert p["enabled"] is False and p["locality"] == "local"


def test_add_local_provider_with_key_stored_encrypted(tmp_path: Path) -> None:
    c, h = admin(tmp_path)
    res = c.post(
        "/api/providers",
        json={
            "name": "LM Studio",
            "base_url": "http://ollama:11434/v1",
            "model": "qwen2.5:7b",
            "api_key": KEY,
        },
        headers=h,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["has_api_key"] is True and "api_key" not in body
    assert KEY not in c.get("/api/providers").text
    db = sqlite3.connect(tmp_path / "data" / "meta.sqlite")
    assert KEY not in " ".join(str(r) for r in db.execute("SELECT * FROM llm_providers"))
    assert KEY not in " ".join(str(r) for r in db.execute("SELECT detail FROM audit_log"))
    key_file = tmp_path / "data" / ".key"
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600


def test_cloud_provider_requires_acknowledgment(tmp_path: Path) -> None:
    c, h = admin(tmp_path)
    body = {"name": "Cloud", "base_url": "https://api.example-cloud.com/v1", "model": "gpt-x"}
    res = c.post("/api/providers", json=body, headers=h)
    assert res.status_code == 409 and res.json()["code"] == "cloud_ack_required"
    ok = c.post("/api/providers", json={**body, "acknowledge_cloud": True}, headers=h)
    assert ok.status_code == 201 and ok.json()["locality"] == "cloud"


def test_cloud_provider_over_plain_http_is_refused(tmp_path: Path) -> None:
    c, h = admin(tmp_path)
    body = {"name": "Cloud", "base_url": "http://api.example-cloud.com/v1", "model": "gpt-x"}
    res = c.post("/api/providers", json={**body, "acknowledge_cloud": True}, headers=h)
    assert res.status_code == 400 and res.json()["code"] == "provider_invalid"
    local = c.post(
        "/api/providers", json={**body, "name": "Box", "base_url": "http://ollama:1/v1"}, headers=h
    )
    assert local.status_code == 201  # plain http stays fine on the local network


@pytest.mark.parametrize(
    "url",
    [
        "ftp://ollama/v1",
        "http://user:pass@ollama:11434/v1",
        "http://ollama:11434/v1?x=1",
        "javascript:alert(1)",
        "http://" + "a" * 600,
    ],
)
def test_bad_base_urls_rejected(tmp_path: Path, url: str) -> None:
    c, h = admin(tmp_path)
    res = c.post("/api/providers", json={"name": "x", "base_url": url, "model": "m"}, headers=h)
    assert res.status_code == 422


def test_update_and_clear_key_and_delete(tmp_path: Path) -> None:
    c, h = admin(tmp_path)
    pid = c.post(
        "/api/providers",
        json={"name": "Box", "base_url": "http://ollama:11434/v1", "model": "m", "api_key": KEY},
        headers=h,
    ).json()["provider_id"]
    res = c.patch(f"/api/providers/{pid}", json={"enabled": True, "clear_api_key": True}, headers=h)
    assert res.status_code == 200
    assert res.json()["enabled"] is True and res.json()["has_api_key"] is False
    assert c.delete(f"/api/providers/{pid}", headers=h).status_code == 204
    assert all(p["provider_id"] != pid for p in c.get("/api/providers").json())


def test_switching_url_to_cloud_also_needs_acknowledgment(tmp_path: Path) -> None:
    c, h = admin(tmp_path)
    pid = c.get("/api/providers").json()[0]["provider_id"]
    res = c.patch(
        f"/api/providers/{pid}", json={"base_url": "https://api.example-cloud.com/v1"}, headers=h
    )
    assert res.status_code == 409


def test_enabling_requires_a_model(tmp_path: Path) -> None:
    c, h = admin(tmp_path)
    pid = c.get("/api/providers").json()[0]["provider_id"]
    res = c.patch(f"/api/providers/{pid}", json={"enabled": True}, headers=h)
    assert res.status_code == 400


def test_non_admins_cannot_manage_providers(tmp_path: Path) -> None:
    c, h = admin(tmp_path)
    inv = c.post("/api/users", json={"username": "ana", "role": "analyst"}, headers=h).json()
    c.post(
        "/api/account/password",
        json={"token": inv["invite_token"], "password": "another long passphrase"},
    )
    a = TestClient(c.app, base_url=BASE)
    tok = a.post(
        "/api/auth/login",
        json={"username": "ana", "password": "another long passphrase", "client": "cli"},
    ).json()["token"]
    bearer = {"Authorization": f"Bearer {tok}"}
    assert a.get("/api/providers", headers=bearer).status_code == 403
    assert (
        a.post(
            "/api/providers",
            json={"name": "x", "base_url": "http://ollama:1/v1", "model": "m"},
            headers=bearer,
        ).status_code
        == 403
    )


def test_anthropic_providers_are_always_cloud(tmp_path: Path) -> None:
    c, h = admin(tmp_path)
    body = {
        "name": "Claude",
        "kind": "anthropic",
        "base_url": "https://api.example-cloud.com/v1",
        "model": "claude-test",
        "api_key": KEY,
    }
    assert c.post("/api/providers", json=body, headers=h).status_code == 409  # needs the ack
    res = c.post("/api/providers", json={**body, "acknowledge_cloud": True}, headers=h)
    assert res.status_code == 201, res.text
    assert res.json()["kind"] == "anthropic" and res.json()["locality"] == "cloud"
    assert KEY not in res.text
    # Even at a private address (a gateway on the LAN), it is still a cloud service, so it
    # needs https and the acknowledgment like any cloud provider.
    lan = {**body, "name": "Claude via gateway", "base_url": "http://ollama:8080/v1"}
    refused = c.post("/api/providers", json={**lan, "acknowledge_cloud": True}, headers=h)
    assert refused.status_code == 400 and "https" in refused.json()["detail"]
    lan_tls = {**lan, "base_url": "https://ollama:8443/v1", "acknowledge_cloud": True}
    ok = c.post("/api/providers", json=lan_tls, headers=h)
    assert ok.status_code == 201 and ok.json()["locality"] == "cloud"
    assert c.post("/api/providers", json={**body, "kind": "other"}, headers=h).status_code == 422


def test_redaction_is_off_by_default_and_turning_it_on_is_audited(tmp_path: Path) -> None:
    c, h = admin(tmp_path)
    body = {"name": "Cloud", "base_url": "https://api.example-cloud.com/v1", "model": "m"}
    p = c.post("/api/providers", json={**body, "acknowledge_cloud": True}, headers=h).json()
    assert p["redact"] is False
    res = c.patch(f"/api/providers/{p['provider_id']}", json={"redact": True}, headers=h)
    assert res.status_code == 200 and res.json()["redact"] is True
    with sqlite3.connect(tmp_path / "data" / "meta.sqlite") as db:
        (detail,) = db.execute(
            "SELECT detail FROM audit_log WHERE action = 'provider.update'"
        ).fetchone()
    assert '"redact":true' in detail


def test_thinking_can_be_turned_off_and_back_to_the_model_default(tmp_path: Path) -> None:
    c, h = admin(tmp_path)
    pid = c.get("/api/providers").json()[0]["provider_id"]
    assert c.get("/api/providers").json()[0]["reasoning"] is None
    res = c.patch(f"/api/providers/{pid}", json={"reasoning": "none"}, headers=h)
    assert res.status_code == 200 and res.json()["reasoning"] == "none"
    res = c.patch(f"/api/providers/{pid}", json={"reasoning": "default"}, headers=h)
    assert res.json()["reasoning"] is None
    bad = c.patch(f"/api/providers/{pid}", json={"reasoning": "max"}, headers=h)
    assert bad.status_code == 422
