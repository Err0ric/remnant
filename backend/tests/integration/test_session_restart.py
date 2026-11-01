"""A routine update restarts the service; browser sessions and CLI tokens must survive it
(owner, 2026-11-01). They live in the SQLite database as SHA-256 hashes with an absolute
expiry (`auth.session_hours`, 12 by default), so a restart signs no one out; only that
expiry, signing out, or an account change does."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import load_config
from app.main import create_app
from tests.integration.test_schedules import BASE, make_lab


def test_a_session_and_its_csrf_token_survive_a_restart(tmp_path: Path) -> None:
    lab = make_lab(tmp_path)
    before = lab["admin"]
    assert before.get("/api/health-checks").status_code == 200
    cookies = dict(before.cookies)
    # A new server process on the same data folder: the restart an update does.
    config = load_config(
        Path("missing.yaml"),
        {
            "APP__PATHS__DATA_DIR": str(tmp_path / "data"),
            "APP__SERVER__HOST": "0.0.0.0",
            "APP__SERVER__PUBLIC_NAMES": "siem.example.internal",
        },
    )
    after = TestClient(create_app(config), base_url=BASE, cookies=cookies)
    assert after.get("/api/health-checks").status_code == 200
    # Changes still work: the CSRF token is stored with the session.
    res = after.post("/api/auth/logout", headers=lab["h"])
    assert res.status_code in (200, 204), res.text
    assert after.get("/api/health-checks").status_code == 401  # and signing out still works
