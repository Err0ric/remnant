"""Owner, 2026-11-03: AI Watch failed every hour and on every page refresh with only
"QueryFailedError" in the log, and nothing on screen. Each step now fails on its own, the
log names the engine's error and a message with no data values, and Health and the AI
Watch panel say what is failing until it works again."""

from typing import Any

import pytest
import structlog

from app.ai import watch as watch_mod
from app.api.cache import scope_key
from app.core.errors import QueryFailedError, log_detail, safe_message
from app.engine.views import permitted_sources
from tests.integration.test_ai_usage import lab  # noqa: F401  # fixture

# Fails the way real data can, with the value in DuckDB's message: a text value cast to a
# number. The value stands for a log field.
VALUE = "dana@example.com"
BAD = f"SELECT CAST(v AS INTEGER) AS n FROM (VALUES ('{VALUE}')) AS t(v)"


def test_a_failing_step_is_logged_with_its_reason_and_shown(
    lab: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, admin = lab["app"], lab["admin"]
    w = app.state.ai_watch
    monkeypatch.setattr(watch_mod, "SENSITIVE_SQL", BAD)  # the hourly review's last query
    with structlog.testing.capture_logs() as logs:
        w.tick()
    (failed,) = [e for e in logs if e["event"] == "ai_watch.step_failed"]
    assert failed["step"] == "review" and failed["error"] == "QueryFailedError"
    assert failed["engine_error"] == "ConversionException"
    assert failed["detail"].startswith("Conversion Error: Could not convert string")
    assert "[values not logged]" in failed["detail"]
    assert VALUE not in str(failed)  # no data value reaches the log
    # The other steps still ran: the new-events check advanced its cursor.
    assert not w.jobs.failing("ai_watch.events")
    # Health (admin) and the AI Watch panel say so.
    health = admin.get("/api/health-checks").json()["background_failures"]
    assert [f["job"] for f in health] == ["ai_watch.review"]
    assert health[0]["detail"].startswith("ConversionException: Conversion Error")
    status = admin.get("/api/ai/watch/status").json()["failing"]
    assert status[0]["job"] == "ai_watch.review" and status[0]["count"] == 1
    # An analyst sees that it is failing, not why.
    seen = lab["ana"].get("/api/ai/watch/status").json()["failing"]
    assert seen and seen[0]["detail"] is None
    assert lab["ana"].get("/api/health-checks").json()["background_failures"] == []


def test_check_now_runs_every_step_and_a_success_clears_the_failure(
    lab: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin, h = lab["admin"], lab["h"]
    monkeypatch.setattr(watch_mod, "SENSITIVE_SQL", BAD)
    steps = admin.post("/api/ai/watch/check", headers=h).json()
    assert [(s["step"], s["ok"]) for s in steps] == [
        ("events", True), ("agents", True), ("review", False)
    ]  # fmt: skip
    assert steps[2]["detail"].startswith("ConversionException")
    assert lab["ana"].post("/api/ai/watch/check", headers=h).status_code in (401, 403)
    monkeypatch.undo()
    steps = admin.post("/api/ai/watch/check", headers=h).json()
    assert all(s["ok"] for s in steps)
    assert admin.get("/api/ai/watch/status").json()["failing"] == []


def test_a_failing_page_refresh_is_recorded_by_view_kind(lab: dict[str, Any]) -> None:  # noqa: F811
    app = lab["app"]
    refresher = app.state.refresher
    with app.state.meta.connect() as con:
        (uid,) = con.execute("SELECT user_id FROM users WHERE username = 'ana'").fetchone()
    user = app.state.auth.users.get(uid)

    def compute(_u: Any, _a: Any) -> Any:
        raise QueryFailedError('Binder Error: Referenced column "nope" not found')

    scope = scope_key(permitted_sources(app.state.meta, user))
    refresher.watch(("ai_watch", uid, scope, 7, "UTC"), uid, scope, compute)
    with structlog.testing.capture_logs() as logs:
        refresher.tick()
    (ev,) = [e for e in logs if e["event"] == "page.refresh_failed"]
    assert ev["detail"] == 'Binder Error: Referenced column "nope" not found'
    assert [f.job for f in refresher.jobs.failing()] == ["page.ai_watch"]


@pytest.mark.parametrize(
    ("message", "logged"),
    [
        (
            "Conversion Error: Could not convert string 'dana@example.com' to INT32",
            "Conversion Error: Could not convert string [values not logged]",
        ),
        (
            'Invalid Input Error: Malformed JSON at byte 0 of input: invalid literal.  Input: "x"',
            "Invalid Input Error: Malformed JSON at byte 0 of input: invalid literal"
            " [values not logged]",
        ),
        ('Binder Error: Referenced column "session" not found', None),
        ('Catalog Error: Table with name "ai_mcp" does not exist!', None),
    ],
)
def test_messages_that_can_quote_data_are_cut(message: str, logged: str | None) -> None:
    assert safe_message(message) == (logged or message)
    exc = QueryFailedError(message)
    exc.engine_error = "SomeException"
    assert log_detail(exc)["engine_error"] == "SomeException"
