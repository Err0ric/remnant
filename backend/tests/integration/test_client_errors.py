"""Owner 2026-11-02: browsers report a page or panel that failed, rate-limited, with no log
content; admins see them on Health and the server log has them."""

from datetime import UTC, datetime
from typing import Any

from structlog.testing import capture_logs

from app.core import client_errors
from tests.integration.test_schedules import make_lab


def _body(**change: Any) -> dict[str, Any]:
    return {
        "kind": "panel", "error_id": "e-0a1b2c", "name": "TypeError",
        "message": "Cannot read properties of undefined (reading …)", "route": "/dashboard",
        "build": "index-Old12345",
    } | change  # fmt: skip


def test_a_report_shows_on_health_for_admins_and_in_the_log(tmp_path: Any) -> None:
    lab = make_lab(tmp_path)
    lab["app"].state.ui_build = "index-New67890"
    with capture_logs() as logs:
        res = lab["ana"].post("/api/client-errors", json=_body(), headers=lab["h"])
    assert res.status_code == 204
    line = next(x for x in logs if x["event"] == "client.error")
    assert line["error_id"] == "e-0a1b2c" and line["stale_page"] is True
    got = lab["admin"].get("/api/health-checks").json()["client_errors"]
    assert [(e["error_id"], e["kind"], e["route"], e["stale"]) for e in got] == [
        ("e-0a1b2c", "panel", "/dashboard", True)
    ]
    assert lab["ana"].get("/api/health-checks").json()["client_errors"] == []  # admins only


def test_reports_are_rate_limited_and_checked(tmp_path: Any) -> None:
    lab = make_lab(tmp_path)
    for i in range(client_errors.PER_USER_PER_MINUTE + 5):
        r = lab["ana"].post(
            "/api/client-errors", json=_body(error_id=f"e-{i:06x}"), headers=lab["h"]
        )
        assert r.status_code == 204
    assert (
        len(lab["app"].state.client_errors.recent(datetime.now(UTC)))
        == client_errors.PER_USER_PER_MINUTE
    )
    assert lab["app"].state.client_errors.dropped == 5
    bad = lab["ana"].post("/api/client-errors", json=_body(error_id="not an id"), headers=lab["h"])
    assert bad.status_code == 422
    long = lab["ana"].post("/api/client-errors", json=_body(message="x" * 500), headers=lab["h"])
    assert long.status_code == 422
