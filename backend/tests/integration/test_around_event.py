"""ADR-0038 section 8: Around this event: same person or device within 5 minutes, every
source the caller may read, at most 50 rows, newest last, with a Likely cause hint."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.ingest.writer import LakeWriter
from app.search.around import around
from tests.integration.test_m365_consents import _row
from tests.integration.test_schedules import make_lab

T = datetime(2026, 10, 29, 10, tzinfo=UTC)


def _signin(source: str, when: str, user: str, code: int = 0, **more: Any) -> dict[str, Any]:
    return _row(
        "m365_signin", "successful sign-in", source, createdDateTime=when,
        userPrincipalName=user, status={"errorCode": code, "failureReason": f"code {code}"},
        **more,
    )  # fmt: skip


def test_around_joins_person_and_points_at_the_likely_cause(tmp_path: Path) -> None:
    lab = make_lab(tmp_path)
    engine = lab["app"].state.engine
    event = _signin("entra2", "2026-10-29T10:00:00Z", "alice@example.com")
    rows = [
        event,
        _signin("m365_signin", "2026-10-29T09:58:00Z", "alice@example.com", 50126),
        _signin("m365_signin", "2026-10-29T10:01:00Z", "bob@example.com",
                deviceDetail={"displayName": "WS-0099"}, ipAddress="198.51.100.9"),
        _signin("m365_signin", "2026-10-29T10:20:00Z", "alice@example.com"),
    ]  # fmt: skip
    LakeWriter(engine._lake).write(rows)
    out = around(engine, None, event["event_id"], T)
    times = [r[0] for r in out.rows]
    assert times == sorted(times) and len(out.rows) == 2  # bob and 10:20 are out
    assert out.likely_cause is not None and out.likely_cause != event["event_id"]
    assert "{from}" in out.sql and "alice@example.com" in out.sql
    # A caller who cannot read the event's source is told it is not there.
    res = lab["ana"].get(f"/api/events/{event['event_id']}/around", params={"at": T.isoformat()})
    assert res.status_code == 404
    ok = lab["admin"].get(f"/api/events/{event['event_id']}/around", params={"at": T.isoformat()})
    assert ok.status_code == 200 and ok.json()["likely_cause"] == out.likely_cause
