"""CLI sign-in: keychain storage, file fallback, logout, certificate pinning helpers."""

import stat
from pathlib import Path

import keyring
import pytest
from fastapi.testclient import TestClient
from keyring.backend import KeyringBackend
from keyring.errors import NoKeyringError, PasswordDeleteError
from typer.testing import CliRunner

from app.auth.tls import ensure_self_signed
from app.cli import main as cli
from app.cli.client import (
    Credentials,
    credentials_path,
    fingerprint,
    load_credentials,
    pin_path,
    save_pin,
)
from app.core.config import load_config
from app.main import create_app

PASSWORD = "correct horse battery"
SERVER = "http://127.0.0.1:8080"


class MemoryKeyring(KeyringBackend):
    priority = 1  # type: ignore[assignment]  # keyring declares this as a classproperty

    def __init__(self) -> None:
        super().__init__()
        self.items: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.items.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.items[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if self.items.pop((service, username), None) is None:
            raise PasswordDeleteError("missing")


class NoKeyring(MemoryKeyring):
    def get_password(self, service: str, username: str) -> str | None:
        raise NoKeyringError("none")

    def set_password(self, service: str, username: str, password: str) -> None:
        raise NoKeyringError("none")

    def delete_password(self, service: str, username: str) -> None:
        raise NoKeyringError("none")


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    config = load_config(Path("missing.yaml"), {"APP__PATHS__DATA_DIR": str(tmp_path / "data")})
    app = create_app(config)
    app.state.auth.users.create("jordan", PASSWORD, "analyst")

    def factory(creds: Credentials) -> TestClient:
        client = TestClient(app)
        if creds.token:
            client.headers["Authorization"] = f"Bearer {creds.token}"
        return client

    monkeypatch.setattr(cli, "client_factory", factory)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: PASSWORD)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("REMNANT_TOKEN", raising=False)
    monkeypatch.delenv("REMNANT_SERVER", raising=False)
    return TestClient(app)


def invoke(*args: str) -> tuple[int, str, str]:
    res = CliRunner().invoke(cli.app, list(args))
    return res.exit_code, res.stdout, res.stderr


def test_login_stores_token_in_keychain(server: TestClient) -> None:
    ring = MemoryKeyring()
    keyring.set_keyring(ring)
    code, out, _ = invoke("login", "--server", SERVER, "-u", "jordan")
    assert code == 0, out
    assert "system keychain" in out
    assert ("remnant-cli", SERVER) in ring.items
    assert "tokens" not in credentials_path().read_text()
    code, out, _ = invoke("query", "SELECT 1 AS one", "-o", "csv")
    assert code == 0
    assert "one" in out


def test_login_falls_back_to_private_file(server: TestClient) -> None:
    keyring.set_keyring(NoKeyring())
    code, out, _ = invoke("login", "--server", SERVER, "-u", "jordan")
    assert code == 0
    assert "mode 0600" in out
    assert stat.S_IMODE(credentials_path().stat().st_mode) == 0o600
    assert load_credentials().token


def test_wrong_password_reports_error(server: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    keyring.set_keyring(MemoryKeyring())
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "nope nope nope")
    code, _, err = invoke("login", "--server", SERVER, "-u", "jordan")
    assert code == 1
    assert "Wrong username or password" in err


def test_logout_revokes_token(server: TestClient) -> None:
    ring = MemoryKeyring()
    keyring.set_keyring(ring)
    invoke("login", "--server", SERVER, "-u", "jordan")
    token = ring.items[("remnant-cli", SERVER)]
    code, out, _ = invoke("logout")
    assert "Signed out" in out
    assert code == 0
    assert not ring.items
    res = server.post(
        "/api/query", json={"sql": "SELECT 1"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 401


def test_query_without_login_hints_at_login(server: TestClient) -> None:
    keyring.set_keyring(MemoryKeyring())
    code, _, err = invoke("query", "SELECT 1", "--server", SERVER)
    assert code == 1
    assert "remnant login" in err


def test_pin_matches_server_log_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    tls = ensure_self_signed(tmp_path / "tls", ["siem.example.internal"])
    pem = tls.cert.read_text()
    assert fingerprint(pem) == tls.fingerprint_sha256  # what the CLI shows == what the log shows
    path = save_pin("https://siem.example.internal:8443", pem)
    assert path == pin_path("https://siem.example.internal:8443/")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert pin_path("https://other.example.internal:8443") != path
