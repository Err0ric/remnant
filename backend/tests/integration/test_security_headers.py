"""Security headers (CLAUDE.md security rule 9, SPEC T10) and structured request logs."""

import re
from pathlib import Path

from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from app.core.config import load_config
from app.main import create_app


def client(tmp_path: Path, host: str = "127.0.0.1") -> TestClient:
    web = tmp_path / "web"
    web.mkdir(exist_ok=True)
    (web / "index.html").write_text("<html><head><title></title></head><body></body></html>")
    config = load_config(
        Path("missing.yaml"),
        {
            "APP__PATHS__DATA_DIR": str(tmp_path / "data"),
            "APP__SERVER__STATIC_DIR": str(web),
            "APP__SERVER__HOST": host,
        },
    )
    base = "http://127.0.0.1" if host == "127.0.0.1" else "https://testserver"
    return TestClient(create_app(config), base_url=base)


def csp(res_headers: dict[str, str]) -> dict[str, str]:
    out = {}
    for part in res_headers["content-security-policy"].split(";"):
        name, _, value = part.strip().partition(" ")
        out[name] = value
    return out


def test_csp_blocks_inline_scripts_and_framing(tmp_path: Path) -> None:
    res = client(tmp_path).get("/api/health")
    policy = csp(res.headers)
    assert policy["default-src"] == "'self'"
    assert policy["script-src"] == "'self'"
    assert "unsafe-inline" not in res.headers["content-security-policy"]
    assert "unsafe-eval" not in res.headers["content-security-policy"]
    assert policy["frame-ancestors"] == "'none'"
    assert policy["object-src"] == "'none'"
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"
    assert res.headers["referrer-policy"] == "no-referrer"


def test_index_carries_the_style_nonce_from_its_own_header(tmp_path: Path) -> None:
    c = client(tmp_path)
    first, second = c.get("/"), c.get("/sources")
    for res in (first, second):
        nonce = re.search(r"'nonce-([A-Za-z0-9_-]+)'", csp(res.headers)["style-src"])
        assert nonce is not None
        assert f'<meta name="csp-nonce" content="{nonce.group(1)}">' in res.text
    assert csp(first.headers)["style-src"] != csp(second.headers)["style-src"]  # fresh per response


def test_api_responses_are_not_cached(tmp_path: Path) -> None:
    assert client(tmp_path).get("/api/meta").headers["cache-control"] == "no-store"


def test_hsts_only_when_serving_https(tmp_path: Path) -> None:
    assert "strict-transport-security" not in client(tmp_path).get("/api/health").headers
    remote = client(tmp_path, "0.0.0.0").get("/api/health")
    assert remote.headers["strict-transport-security"].startswith("max-age=")


def test_request_log_is_structured_without_query_strings(tmp_path: Path) -> None:
    c = client(tmp_path)
    with capture_logs() as logs:
        c.get("/api/meta?token=secret-value")
    entry = next(e for e in logs if e["event"] == "http.request")
    assert entry["path"] == "/api/meta"
    assert entry["status"] == 200
    assert entry["user_id"] is None
    assert "secret-value" not in str(logs)
