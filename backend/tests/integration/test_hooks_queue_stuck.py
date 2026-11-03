"""Owner 2026-11-02: a hooks plugin machine is quiet whenever nobody uses Claude Code, so
silence alone is not a problem on Health. A queue that holds records and delivered nothing
for 3 days (configurable) is: the machine is unhealthy and one alert item is raised."""

from datetime import UTC, datetime, timedelta
from typing import Any

from tests.integration.test_claude_hooks import _otlp, lab, send  # noqa: F401  # the fixture

T0 = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


def _record(at: datetime, queued: int, seq: int) -> dict[str, Any]:
    attrs = {
        "event_name": "claude_hooks.pre_tool_use", "role": "tool_call", "session_id": "s-1",
        "install_id": "i1", "seq": str(seq), "plugin_variant": "posix", "tool_name": "Read",
        "claude_account_email": "dana@example.com", "queued_at_send": str(queued),
    }  # fmt: skip
    return {
        "timeUnixNano": str(int(at.timestamp()) * 1_000_000_000),
        "body": {"stringValue": "claude_hooks.pre_tool_use"},
        "attributes": [{"key": k, "value": {"stringValue": v}} for k, v in attrs.items()],
    }


def _machine(lab: dict[str, Any], host: str, queued: int, seq: int) -> None:  # noqa: F811
    assert send(lab, _otlp([_record(T0, queued, seq)], host=host)).status_code == 200


def _agents(lab: dict[str, Any], days: float) -> dict[str, dict[str, Any]]:  # noqa: F811
    app = lab["app"]
    app.state.ingest._clock = lambda: T0
    app.state.ingest.run_once()
    app.state.health._clock = lambda: T0 + timedelta(days=days)
    got = lab["admin"].get("/api/health-checks").json()["agents"]
    return {a["machine"]: a for a in got if a["kind"] == "Claude hooks plugin"}


def test_a_quiet_machine_is_fine_and_a_stuck_queue_is_not(lab: dict[str, Any]) -> None:  # noqa: F811
    _machine(lab, "ws-idle", 0, 1)
    _machine(lab, "ws-stuck", 40, 1)
    two = _agents(lab, 2)
    assert two["ws-idle"]["state"] == "healthy" and two["ws-stuck"]["state"] == "healthy"
    four = _agents(lab, 4)
    assert four["ws-idle"]["state"] == "healthy"  # nobody used Claude Code: normal
    stuck = four["ws-stuck"]
    assert stuck["state"] == "unhealthy"
    assert stuck["reason"].startswith("40 records waiting on the machine and nothing delivered")


def test_a_stuck_queue_raises_one_alert_item_per_episode(lab: dict[str, Any]) -> None:  # noqa: F811
    _machine(lab, "ws-stuck", 12, 1)
    _agents(lab, 4)
    health = lab["app"].state.health
    assert health.stuck_queues() == 1
    health._stuck_checked = None
    assert health.stuck_queues() == 0  # same episode: no second item
    with lab["app"].state.meta.connect() as con:
        rows = con.execute(
            "SELECT title, state FROM alert_items WHERE kind = 'gap' AND subject LIKE '%ws-stuck'"
        ).fetchall()
    assert [tuple(r) for r in rows] == [("ws-stuck: Claude hooks records not delivered", "open")]
