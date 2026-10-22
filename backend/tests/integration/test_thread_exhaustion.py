"""After a burst of "can't start new thread", the server recovers on its own (trial)."""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import load_config
from app.main import create_app
from tests.integration.test_query_api import data_dir  # fixture

__all__ = ["data_dir"]

QUERY = {"sql": "SELECT count(*) AS n FROM events"}


@contextmanager
def no_new_threads() -> Iterator[None]:
    """Every Thread.start fails, as at a container's pids limit."""
    real = threading.Thread.start

    def refuse(self: threading.Thread) -> None:
        raise RuntimeError("can't start new thread")

    threading.Thread.start = refuse  # type: ignore[method-assign]  # simulated limit
    try:
        yield
    finally:
        threading.Thread.start = real  # type: ignore[method-assign]


def test_requests_work_again_after_thread_creation_recovers(data_dir: Path) -> None:
    config = load_config(Path("missing.yaml"), {"APP__PATHS__DATA_DIR": str(data_dir)})
    c = TestClient(create_app(config), base_url="http://127.0.0.1", raise_server_exceptions=False)
    with c:
        assert c.post("/api/query", json=QUERY).status_code == 200  # warm: workers exist
        with no_new_threads():
            burst = [c.post("/api/query", json=QUERY).status_code for _ in range(60)]
            assert set(burst) <= {200, 503}, burst  # busy, never a bare 500
        after = [c.post("/api/query", json=QUERY) for _ in range(5)]
        assert [r.status_code for r in after] == [200] * 5, [r.text[:200] for r in after]
        assert after[-1].json()["rows"] == [[2]]
        assert c.get("/api/health").status_code == 200


def test_too_many_queries_at_once_is_busy_with_retry_after(data_dir: Path) -> None:
    config = load_config(
        Path("missing.yaml"),
        {"APP__PATHS__DATA_DIR": str(data_dir), "APP__SERVER__MAX_CONCURRENT_QUERIES": "1"},
    )
    app = create_app(config)
    c = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)
    with c:
        engine = app.state.engine
        engine._timeout_s = 0.2
        with engine._slot(1):  # the one slot is taken
            r = c.post("/api/query", json=QUERY)
        assert r.status_code == 503 and r.json()["code"] == "busy"
        assert r.headers["Retry-After"] == "5"
        assert c.post("/api/query", json=QUERY).status_code == 200
