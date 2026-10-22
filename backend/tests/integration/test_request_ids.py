"""Request ids, and out-of-threads as busy rather than a bare 500 (trial finding)."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import load_config
from app.main import create_app


def _client(tmp_path: Path) -> TestClient:
    app = create_app(load_config(Path("missing.yaml"), {"APP__PATHS__DATA_DIR": str(tmp_path)}))

    def boom() -> None:
        raise RuntimeError("can't start new thread")

    app.add_api_route("/api/test-no-thread", boom)
    return TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)


def test_every_response_carries_a_request_id(tmp_path: Path) -> None:
    res = _client(tmp_path).get("/api/health")
    assert len(res.headers["x-request-id"]) == 12


def test_no_free_thread_is_a_503_busy_with_the_request_id(tmp_path: Path) -> None:
    res = _client(tmp_path).get("/api/test-no-thread")
    assert res.status_code == 503 and res.headers["retry-after"] == "5"
    body = res.json()
    assert body["code"] == "busy"
    assert body["request_id"] == res.headers["x-request-id"]
    assert body["request_id"] in body["detail"]
