"""F64: Settings > Single sign-on shows the setup without the secret, and can test it."""

from pathlib import Path
from typing import Any

from tests.integration.test_schedules import make_lab


def test_sso_page_when_off(tmp_path: Path) -> None:
    lab: dict[str, Any] = make_lab(tmp_path)
    res = lab["admin"].get("/api/settings/sso")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "off" and body["bound"] == []
    assert any(e["name"] == "APP__SSO__CLIENT_SECRET" for e in body["env"])
    test = lab["admin"].post("/api/settings/sso/test", headers=lab["h"]).json()
    assert test == {"ok": False, "message": "Single sign-on is off on this server"}
    assert lab["ana"].get("/api/settings/sso").status_code == 403
