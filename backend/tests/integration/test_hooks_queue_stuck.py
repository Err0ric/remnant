"""Owner 2026-11-02: a hooks plugin machine is quiet whenever nobody uses Claude Code, so
silence alone is not a problem on Health. A queue that holds records and delivered nothing
for 3 days (configurable) is, and one alert item is raised.

Owner review, item 9: a machine that sends nothing at all is idle or offline (low, Health
attention); one that holds records while it still sends other telemetry is a delivery
problem (medium, Health unhealthy). The item says how many records wait (when the plugin
reports it) and when the machine was last in contact."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tests.integration.test_claude_hooks import _otlp, lab, send  # noqa: F401  # the fixture

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts" / "fixtures"))
from ai_telemetry import logs_payload

T0 = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


def _record(at: datetime, queued: int | None, seq: int) -> dict[str, Any]:
    attrs = {
        "event_name": "claude_hooks.pre_tool_use", "role": "tool_call", "session_id": "s-1",
        "install_id": "i1", "seq": str(seq), "plugin_variant": "posix", "tool_name": "Read",
        "claude_account_email": "dana@example.com",
    }  # fmt: skip
    if queued is not None:  # older plugins do not report their queue
        attrs["queued_at_send"] = str(queued)
    return {
        "timeUnixNano": str(int(at.timestamp()) * 1_000_000_000),
        "body": {"stringValue": "claude_hooks.pre_tool_use"},
        "attributes": [{"key": k, "value": {"stringValue": v}} for k, v in attrs.items()],
    }


def _machine(lab: dict[str, Any], host: str, queued: int | None, seq: int) -> None:  # noqa: F811
    assert send(lab, _otlp([_record(T0, queued, seq)], host=host)).status_code == 200


def _other_telemetry(lab: dict[str, Any], host: str, at: datetime) -> None:  # noqa: F811
    """Claude Code's own OpenTelemetry from the same machine, received at `at`."""
    event = {"user.email": "dana@example.com", "session.id": "s-9", "event.name": "user_prompt"}
    app = lab["app"]
    app.state.ingest._clock = lambda: T0  # the hooks record arrives at T0
    app.state.ingest.run_once()
    assert send(lab, logs_payload([(at, event)], host)).status_code == 200
    app.state.ingest._clock = lambda: at
    app.state.ingest.run_once()


def _items(lab: dict[str, Any]) -> dict[str, Any]:  # noqa: F811
    with lab["app"].state.meta.connect() as con:
        rows = con.execute(
            "SELECT subject, title, detail, severity, range_start FROM alert_items"
            " WHERE kind = 'gap'"
        ).fetchall()
    return {r["subject"].split("/")[-1]: dict(r) for r in rows}


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
    # Nothing else from the machine either: idle or offline, attention rather than broken.
    assert stuck["state"] == "attention"
    assert stuck["reason"].startswith("40 records waiting on the machine and nothing delivered")
    assert "no telemetry at all from the machine" in stuck["reason"]


def test_a_stuck_queue_raises_one_alert_item_per_episode(lab: dict[str, Any]) -> None:  # noqa: F811
    _machine(lab, "ws-stuck", 12, 1)
    _other_telemetry(lab, "ws-stuck", T0 + timedelta(days=3, hours=20))
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


def test_records_held_while_other_telemetry_flows_are_medium(lab: dict[str, Any]) -> None:  # noqa: F811
    _machine(lab, "ws-busy", 40, 1)
    _other_telemetry(lab, "ws-busy", T0 + timedelta(days=3, hours=20))
    busy = _agents(lab, 4)["ws-busy"]
    assert busy["state"] == "unhealthy"
    assert "still sends other telemetry" in busy["reason"]
    assert lab["app"].state.health.stuck_queues() == 1
    item = _items(lab)["ws-busy"]
    assert item["severity"] == "medium"
    assert item["title"] == "ws-busy: Claude hooks records not delivered"
    assert "Records waiting: 40" in item["detail"]
    assert "Last contact: 2026-10-20 09:00 UTC (hooks)" in item["detail"]
    assert "other telemetry 2026-10-24 05:00 UTC" in item["detail"]
    assert item["range_start"].startswith("2026-10-20T09:00")  # the hooks plugin's last


def test_an_idle_or_offline_machine_is_info_on_health_only(lab: dict[str, Any]) -> None:  # noqa: F811
    """No telemetry at all from the machine: info (D214, proposed). Health says so with
    the queue depth and the last contact; no alert item."""
    _machine(lab, "ws-away", 12, 1)
    away = _agents(lab, 4)["ws-away"]
    assert away["state"] == "attention" and away["queued"] == 12
    assert away["reason"].startswith("12 records waiting on the machine")
    assert "since 2026-10-20 09:00 UTC: it looks idle or offline" in away["reason"]
    assert away["last_seen"].startswith("2026-10-20T09:00")
    assert lab["app"].state.health.stuck_queues() == 0
    assert _items(lab) == {}


def test_no_queue_depth_reported(lab: dict[str, Any]) -> None:  # noqa: F811
    """An older plugin sends no queue figure: still sending other telemetry with no hook
    record delivered is a medium item that says the depth is not reported; with nothing
    else from the machine either there is nothing to say."""
    _machine(lab, "ws-old", None, 1)
    _other_telemetry(lab, "ws-old", T0 + timedelta(days=3, hours=20))
    _machine(lab, "ws-gone", None, 1)
    agents = _agents(lab, 4)
    assert agents["ws-old"]["state"] == "unhealthy" and agents["ws-old"]["queued"] == 0
    assert agents["ws-gone"]["state"] == "healthy"
    assert lab["app"].state.health.stuck_queues() == 1
    items = _items(lab)
    assert set(items) == {"ws-old"}
    assert items["ws-old"]["severity"] == "medium"
    assert "Records waiting: not reported by the plugin" in items["ws-old"]["detail"]
