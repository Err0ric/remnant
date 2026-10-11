"""Fixes from the Slice 1 independent review (2026-10-10): S1, S2, S4, S7, S8."""

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth.ratelimit import LoginLimiter
from app.core.config import load_config
from app.core.errors import LoginFailedError, RateLimitedError, SetupInvalidError
from app.main import create_app

PASSWORD = "correct horse battery"


def app_for(tmp_path: Path, host: str = "127.0.0.1"):  # type: ignore[no-untyped-def]  # test helper
    config = load_config(
        Path("missing.yaml"),
        {"APP__PATHS__DATA_DIR": str(tmp_path / "data"), "APP__SERVER__HOST": host},
    )
    return create_app(config)


# --- S1: DNS rebinding against the open local mode -----------------------------------


@pytest.mark.parametrize(
    "host", ["rebind.attacker.example", "rebind.attacker.example:8080", "192.0.2.50"]
)
def test_loopback_bind_refuses_foreign_host_headers(tmp_path: Path, host: str) -> None:
    c = TestClient(app_for(tmp_path), base_url="http://127.0.0.1")
    res = c.post("/api/query", json={"sql": "SELECT 1"}, headers={"Host": host})
    assert res.status_code == 421
    assert res.json()["code"] == "bad_host"


@pytest.mark.parametrize("host", ["localhost:8080", "127.0.0.1", "127.0.0.1:8080", "[::1]:8080"])
def test_loopback_bind_accepts_local_names(tmp_path: Path, host: str) -> None:
    c = TestClient(app_for(tmp_path), base_url="http://127.0.0.1")
    assert c.get("/api/health", headers={"Host": host}).status_code == 200


def test_cross_origin_writes_refused(tmp_path: Path) -> None:
    c = TestClient(app_for(tmp_path), base_url="http://127.0.0.1")
    bad = c.post("/api/query", json={"sql": "SELECT 1"}, headers={"Origin": "http://evil.example"})
    assert bad.status_code == 403
    assert bad.json()["code"] == "cross_origin"
    same = c.post("/api/query", json={"sql": "SELECT 1"}, headers={"Origin": "http://127.0.0.1"})
    assert same.status_code == 200


def test_network_bind_does_not_need_a_host_list(tmp_path: Path) -> None:
    # Off loopback every route needs sign-in, so a rebound name gains nothing.
    c = TestClient(app_for(tmp_path, "0.0.0.0"), base_url="https://siem.example.internal")
    assert c.get("/api/health").status_code == 200


# --- S2: rate limit holds under concurrency ------------------------------------------


def test_parallel_wrong_passwords_stop_at_the_limit(tmp_path: Path) -> None:
    app = app_for(tmp_path)
    auth = app.state.auth
    auth.users.create("jordan", PASSWORD, "analyst")
    outcomes: list[str] = []
    lock = threading.Lock()

    def attempt() -> None:
        try:
            auth.login("jordan", "wrong password!", "browser", "192.0.2.7")
            result = "ok"
        except LoginFailedError:
            result = "failed"
        except RateLimitedError:
            result = "limited"
        with lock:
            outcomes.append(result)

    with ThreadPoolExecutor(max_workers=20) as pool:
        for _ in range(40):
            pool.submit(attempt)
    assert outcomes.count("failed") <= 5
    assert outcomes.count("limited") >= 35


def test_successful_login_clears_the_counter(tmp_path: Path) -> None:
    auth = app_for(tmp_path).state.auth
    auth.users.create("jordan", PASSWORD, "analyst")
    for _ in range(3):
        with pytest.raises(LoginFailedError):
            auth.login("jordan", "wrong password!", "browser", "192.0.2.7")
    auth.login("jordan", PASSWORD, "browser", "192.0.2.7")
    for _ in range(4):
        with pytest.raises(LoginFailedError):
            auth.login("jordan", "wrong password!", "browser", "192.0.2.7")


# --- S7: setup cannot be locked out by another host -----------------------------------


def test_bad_setup_attempts_from_one_address_do_not_block_another(tmp_path: Path) -> None:
    auth = app_for(tmp_path, "0.0.0.0").state.auth
    token = auth.setup_url("siem.example.internal", 8080).split("#", 1)[1]
    for _ in range(6):
        with pytest.raises((SetupInvalidError, RateLimitedError)):
            auth.complete_setup("x" * 43, "admin", PASSWORD, "203.0.113.9")
    user, _, _ = auth.complete_setup(token, "admin", PASSWORD, "192.0.2.10")
    assert user.role == "admin"


# --- S8: limiter memory stays bounded --------------------------------------------------


def test_limiter_forgets_expired_keys() -> None:
    limiter = LoginLimiter(max_failures=5, window_s=60, max_keys=100)
    for i in range(500):
        limiter.reserve([f"user:{i}"], now=float(i))
    assert limiter.size() <= 100
    assert limiter.reserve(["user:new"], now=10_000.0) == 0
