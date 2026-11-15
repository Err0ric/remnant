"""The person page as a Record (ADR-0052, DESIGN.md 6.3): the names counted as the person,
activity per day in the viewer's time zone, and the person's Microsoft 365 lists, built and
run by the server on the caller's own view."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from app.engine.duckdb import QueryScope
from app.ingest.writer import LakeWriter
from app.search.identity import IdentityMap
from app.search.person_record import M365_LISTS, m365_sql, person_record
from tests.integration.test_around_event import _signin
from tests.integration.test_schedules import make_lab

START, END = datetime(2026, 10, 27, tzinfo=UTC), datetime(2026, 10, 30, tzinfo=UTC)
IDENT = IdentityMap(domains=["example.com"])


def _lab(tmp_path: Path) -> dict:  # type: ignore[type-arg]
    lab = make_lab(tmp_path)
    LakeWriter(lab["app"].state.engine._lake).write(
        [
            _signin("m365_signin", "2026-10-29T09:58:00Z", "Erin@example.com", 50126),
            _signin("m365_signin", "2026-10-29T09:59:00Z", "EXAMPLE\\erin"),
            _signin("m365_signin", "2026-10-29T03:00:00Z", "erin@example.com"),
            _signin("m365_signin", "2026-10-29T10:30:00Z", "bob@example.com"),
            # MFA asked: interrupted, not a failure (DESIGN.md 6.2a).
            _signin("m365_signin", "2026-10-29T11:00:00Z", "erin@example.com", 50074),
        ]
    )
    return lab


def test_names_and_activity_per_day(tmp_path: Path) -> None:
    engine = _lab(tmp_path)["app"].state.engine
    got = person_record(engine, QueryScope(None, START, END), IDENT, "erin", "UTC")
    assert got.person == "erin" and "{from}" in got.sql
    assert {"Erin@example.com", "EXAMPLE\\erin", "erin@example.com"} == set(got.forms)
    # One row per day of the window, empty days too; bob's sign-in is not counted.
    assert [(d.day, d.events, d.failed) for d in got.days] == [
        ("2026-10-27", 0, 0),
        ("2026-10-28", 0, 0),
        ("2026-10-29", 4, 1),
    ]


def test_days_are_the_viewers(tmp_path: Path) -> None:
    engine = _lab(tmp_path)["app"].state.engine
    got = person_record(engine, QueryScope(None, START, END), IDENT, "erin", "America/Los_Angeles")
    by_day = {d.day: d.events for d in got.days}
    # 03:00 UTC is the evening before in Los Angeles.
    assert by_day["2026-10-28"] == 1 and by_day["2026-10-29"] == 3
    assert sum(by_day.values()) == 4


def test_days_in_a_zone_with_a_half_hour_offset(tmp_path: Path) -> None:
    lab = _lab(tmp_path)
    engine = lab["app"].state.engine
    # 18:40 UTC is 00:10 the next day in Kolkata (UTC+5:30): an hour bucket would put it
    # on the day before.
    LakeWriter(engine._lake).write(
        [_signin("m365_signin", "2026-10-27T18:40:00Z", "erin@example.com")]
    )
    got = person_record(engine, QueryScope(None, START, END), IDENT, "erin", "Asia/Kolkata")
    by_day = {d.day: d.events for d in got.days}
    assert by_day["2026-10-28"] == 1 and by_day["2026-10-27"] == 0


def test_ai_telemetry_is_left_out_without_view_people(tmp_path: Path) -> None:
    lab = _lab(tmp_path)
    engine = lab["app"].state.engine
    row = _signin("m365_signin", "2026-10-28T09:00:00Z", "erin-ai@example.com")
    row["template_id"] = "claude_code_otel"
    row["actor_user_name"] = "erin"
    LakeWriter(engine._lake).write([row])
    scope = QueryScope(None, START, END)
    seen = person_record(engine, scope, IDENT, "erin", "UTC")
    assert sum(d.events for d in seen.days) == 5 and "claude_code_otel" not in seen.sql
    masked = person_record(engine, scope, IDENT, "erin", "UTC", ai=False)
    assert sum(d.events for d in masked.days) == 4 and "claude_code_otel" in masked.sql


def test_m365_lists_are_the_persons_only(tmp_path: Path) -> None:
    for name in M365_LISTS:
        sql = m365_sql(IDENT, "erin", name)
        assert "{from}" in sql and "{to}" in sql and "'erin'" in sql


def test_api_runs_the_lists_with_the_callers_access(tmp_path: Path) -> None:
    lab = _lab(tmp_path)
    admin = lab["admin"]
    res = admin.get("/api/people/erin/record", params={"days": 30, "tz": "UTC"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body) >= {"person", "forms", "days", "m365", "start", "end"}
    assert len(body["days"]) in (30, 31)
    # The lab has no Microsoft 365 source, so the page shows no Microsoft 365 section.
    assert body["m365"] is False and body["m365_sql"] == {}
    rows = lab["aud"].get("/api/audit/events", params={"action": "search.person_record"}).json()
    assert rows and rows[0]["username"] == "admin"
    for name in M365_LISTS:
        got = admin.get("/api/people/erin/m365", params={"name": name, "days": 30})
        assert got.status_code == 200, got.text
    bad = admin.get("/api/people/erin/m365", params={"name": "dlp", "days": 30})
    assert bad.status_code == 400
    # ana reads only the Linux source: the same call answers, with none of the rows.
    ana = lab["ana"].get("/api/people/erin/m365", params={"name": "sign_ins", "days": 30})
    assert ana.status_code == 200 and ana.json()["row_count"] == 0
    assert lab["ana"].get("/api/people/erin/record", params={"days": 30}).json()["forms"] == []


def test_the_section_follows_the_callers_own_sources(tmp_path: Path) -> None:
    lab = _lab(tmp_path)
    admin, h = lab["admin"], lab["h"]
    logs = tmp_path / "logs" / "entra"
    logs.mkdir()
    body = {
        "source_id": "entra",
        "format": "syslog",
        "path": str(logs),
        "template_id": "m365_signin",
    }
    assert admin.post("/api/sources", json=body, headers=h).status_code == 201
    got = admin.get("/api/people/erin/record", params={"days": 30}).json()
    assert got["m365"] is True and set(got["m365_sql"]) == set(M365_LISTS)
    # ana reads the Linux source only: other sources, but no Microsoft 365 one.
    assert lab["ana"].get("/api/people/erin/record", params={"days": 30}).json()["m365"] is False


def test_names_are_hidden_without_view_people(
    tmp_path: Path, pin_now: Callable[[datetime], None]
) -> None:
    """D242: without View people in AI usage the server sends no names for the Accounts
    box, only how many there are (owner, 2026-11-14)."""
    pin_now(datetime(2026, 10, 30, 12, 0, tzinfo=UTC))
    lab = _lab(tmp_path)
    # On the Linux source, so ana and bob read them too and the count is not trivially 0.
    # The API reads registered sources only, and the lab sets no domains, so plain forms.
    LakeWriter(lab["app"].state.engine._lake).write(
        [
            _signin("lin_auth", "2026-10-29T08:00:00Z", "erin"),
            _signin("lin_auth", "2026-10-29T08:01:00Z", "EXAMPLE\\erin"),
        ]
    )
    params = {"days": 7, "tz": "UTC"}
    named = lab["admin"].get("/api/people/erin/record", params=params).json()
    assert set(named["forms"]) == {"erin", "EXAMPLE\\erin"} and named["forms_hidden"] == 0
    seen = lab["ana"].get("/api/people/erin/record", params=params).json()
    assert seen["forms"] == [] and seen["forms_hidden"] == 2
    res = lab["admin"].patch(
        f"/api/users/{lab['ids']['bob']}", json={"view_ai_people": True}, headers=lab["h"]
    )
    assert res.status_code == 200, res.text
    granted = lab["bob"].get("/api/people/erin/record", params=params).json()
    assert set(granted["forms"]) == {"erin", "EXAMPLE\\erin"}
    assert granted["forms_hidden"] == 0


def test_timeline_sends_no_names_without_view_people(
    tmp_path: Path, pin_now: Callable[[datetime], None]
) -> None:
    """D242: the Timeline fold's "Seen as" and "Possibly the same person" lists are names,
    so a viewer without the permission gets the count and no list (owner, 2026-11-14)."""
    pin_now(datetime(2026, 10, 30, 12, 0, tzinfo=UTC))
    lab = _lab(tmp_path)
    LakeWriter(lab["app"].state.engine._lake).write(
        [
            _signin("lin_auth", "2026-10-29T08:00:00Z", "erin"),
            _signin("lin_auth", "2026-10-29T08:01:00Z", "EXAMPLE\\erin"),
        ]
    )
    named = lab["admin"].get("/api/people/erin/timeline", params={"days": 7}).json()
    assert set(named["forms"]) == {"erin", "EXAMPLE\\erin"} and named["forms_hidden"] == 0
    seen = lab["ana"].get("/api/people/erin/timeline", params={"days": 7}).json()
    assert seen["forms"] == [] and seen["forms_hidden"] == 2 and seen["maybe"] == []
    assert seen["rows"], "the rows themselves are identity data and stay"
