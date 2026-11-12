"""Shared test setup."""

from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import keyring
import pytest
from keyring.backends import fail


@pytest.fixture(autouse=True, scope="session")
def _parse_each_yaml_text_once() -> Iterator[None]:
    """Every app built in a test loads the same starter templates and saved-search library
    (about 50 YAML files through the pure-Python safe loader, most of `create_app`'s time).
    Within a test process, a text that parsed once returns a deep copy of that result
    instead of parsing again. The first parse of every text, and every text that fails
    (aliases, depth, bad YAML), still runs the real loader, so nothing it checks is skipped.
    """
    import copy

    from app.core import safeyaml

    real = safeyaml.load
    parsed: dict[str, Any] = {}

    def load(text: str) -> Any:
        if text not in parsed:
            result = real(text)  # raises before anything is cached
            if len(parsed) < 4096 and len(text) <= 256 * 1024:
                parsed[text] = result
            return copy.deepcopy(result)
        return copy.deepcopy(parsed[text])

    safeyaml.load = load  # type: ignore[assignment]  # same signature, restored below
    yield
    safeyaml.load = real  # type: ignore[assignment]  # restore the real loader


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


_STAND_IN = {"on": True}


@pytest.fixture(autouse=True, scope="session")
def _first_admin_stand_in() -> Iterator[None]:
    """Many older tests drive a loopback app that has no accounts and expect to act as an
    administrator without signing in (the no-sign-in mode D245 removed). For those, and only
    in tests, a loopback app with no accounts answers as the stand-in `local` administrator.
    The app has no such path any more: tests of sign-in and setup are marked `real_auth` and
    get the app as it ships (tests/integration/test_always_setup.py). Session-wide, because
    module-scoped fixtures build their app before any test runs. BACKLOG A32: move the
    older files to a real sign-in and drop this."""
    from app.api import access
    from app.auth.admin import UserAdmin
    from app.auth.users import LOCAL_USER

    signed_in = access._current_user
    assert_admin = UserAdmin._assert_admin

    def current_user(req: Any) -> Any:
        auth = req.app.state.auth
        if _STAND_IN["on"] and auth.loopback and auth.mode() == "setup":
            req.state.user = LOCAL_USER
            req.state.via = "open"
            return LOCAL_USER
        return signed_in(req)

    def admin_or_stand_in(con: Any, actor: Any) -> None:
        none_yet = con.execute("SELECT 1 FROM users LIMIT 1").fetchone() is None
        if not (_STAND_IN["on"] and actor.user_id == LOCAL_USER.user_id and none_yet):
            assert_admin(con, actor)

    patch = pytest.MonkeyPatch()
    patch.setattr(access, "_current_user", current_user)
    patch.setattr(UserAdmin, "_assert_admin", staticmethod(admin_or_stand_in))
    yield
    patch.undo()


@pytest.fixture(autouse=True)
def _real_auth_when_marked(request: pytest.FixtureRequest) -> Iterator[None]:
    _STAND_IN["on"] = request.node.get_closest_marker("real_auth") is None
    yield
    _STAND_IN["on"] = True


@pytest.fixture(autouse=True)
def _fast_password_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Argon2 with minimal cost in tests only; production keeps argon2-cffi's defaults."""
    from argon2 import PasswordHasher

    from app.auth import passwords

    monkeypatch.setattr(
        passwords, "_hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    )


@pytest.fixture(autouse=True)
def _unpinned_clock() -> Iterator[None]:
    """Every test starts and ends with the real clock."""
    from app.core import clock

    clock.pin(None)
    yield
    clock.pin(None)


@pytest.fixture
def pin_now() -> Callable[[datetime], None]:
    """Pin the read paths' "now" (`app.core.clock`) next to a test's fixed event dates, so
    windows such as "the last 30 days" give the same result on any day."""
    from app.core import clock

    return clock.pin
