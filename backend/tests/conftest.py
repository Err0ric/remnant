"""Shared test setup."""

from collections.abc import Iterator
from pathlib import Path

import keyring
import pytest
from keyring.backends import fail


@pytest.fixture(autouse=True)
def _no_real_keychain() -> Iterator[None]:
    """Tests never read or write the developer's real keychain; individual tests opt in to fakes."""
    previous = keyring.get_keyring()
    keyring.set_keyring(fail.Keyring())
    yield
    keyring.set_keyring(previous)


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Default config paths (data/, config/app.yaml) resolve inside a fresh temp folder."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def _local_test_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests talk to the app as 127.0.0.1 unless they choose a base URL.

    Loopback binds refuse foreign Host headers (DNS rebinding protection), and the
    TestClient default host "testserver" is not a local name.
    """
    from starlette import testclient

    original = testclient.TestClient.__init__

    def init(self: testclient.TestClient, *args: object, **kwargs: object) -> None:
        kwargs.setdefault("base_url", "http://127.0.0.1")
        original(self, *args, **kwargs)  # type: ignore[arg-type]  # forwarding unchanged arguments

    monkeypatch.setattr(testclient.TestClient, "__init__", init)


@pytest.fixture(autouse=True)
def _fast_password_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Argon2 with minimal cost in tests only; production keeps argon2-cffi's defaults."""
    from argon2 import PasswordHasher

    from app.auth import passwords

    monkeypatch.setattr(
        passwords, "_hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    )
