"""A Pacific firewall read as UTC: Sources says the times look 7 hours early, and changing
the source's time zone fixes new events (trial finding)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.main import create_app

NOW = datetime(2026, 10, 22, 6, 30, tzinfo=UTC)  # 23:30 on the 21st in Los Angeles


def pan_system(local: datetime) -> str:
    """No high-resolution field: an older firewall, so only Generated Time (local, no zone)."""
    g = local.strftime("%Y/%m/%d %H:%M:%S")
    return (
        f"<14>{local:%b} {local.day:>2} {local:%H:%M:%S} pa-fw01 1,{g},012345678901,SYSTEM,general,,{g},"
        f'vsys1,general,,,,general,informational,"Something happened",1,0x0,0,0,0,0,,pa-fw01'
    )


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    logs = tmp_path / "logs" / "fw"
    logs.mkdir(parents=True)
    local_now = NOW - timedelta(hours=7)  # what the firewall's clock says, as naive text
    lines = [pan_system(local_now - timedelta(seconds=10 * i)) for i in range(60)]
    (logs / "system.log").write_text("\n".join(reversed(lines)) + "\n")
    config = load_config(
        Path("missing.yaml"),
        {
            "APP__PATHS__DATA_DIR": str(tmp_path / "data"),
            "APP__PATHS__ALLOWED_ROOTS": str(tmp_path / "logs"),
        },
    )
    app = create_app(config)
    app.state.ingest._clock = lambda: NOW
    c = TestClient(app, base_url="http://127.0.0.1")
    body = {
        "source_id": "fw",
        "format": "syslog",
        "path": str(logs),
        "template_id": "paloalto_system",
    }
    assert c.post("/api/sources", json=body).status_code == 201
    return {"app": app, "c": c, "logs": logs}


def status(lab: dict[str, Any]) -> dict[str, Any]:
    (src,) = lab["c"].get("/api/sources").json()
    st: dict[str, Any] = src["status"]
    return st


def test_seven_hours_early_is_reported_and_the_zone_can_be_changed(lab: dict[str, Any]) -> None:
    lab["app"].state.ingest.run_once()
    st = status(lab)
    assert st["time_offset_h"] == 7.0
    assert st["time_offset_text"] == "Event times look 7 hours early; check this source's time zone"
    res = lab["c"].patch("/api/sources/fw", json={"timezone": "America/Los_Angeles"})
    assert res.status_code == 200 and res.json()["timezone"] == "America/Los_Angeles"
    assert status(lab)["time_offset_h"] is None  # samples start over after the change
    assert lab["c"].patch("/api/sources/fw", json={"timezone": "Mars/Olympus"}).status_code == 400
    # New lines now land at the right time.
    later = NOW + timedelta(minutes=5)
    lab["app"].state.ingest._clock = lambda: later
    with (lab["logs"] / "system.log").open("a") as fh:
        fh.write(pan_system(later - timedelta(hours=7)) + "\n")
    lab["app"].state.ingest.run_once()
    res = lab["c"].post("/api/query", json={"sql": "SELECT max(time) FROM events"})
    assert res.json()["rows"][0][0].startswith("2026-10-22T06:35:00")
