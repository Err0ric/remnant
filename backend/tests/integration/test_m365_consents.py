"""F66: an app consent reported by both Graph and the Management API counts once; blocked
consents are counted apart from granted ones; and an app Entra calls "Unknown" is named
from the person's sign-in just before."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.ai.consents import COUNTS_SQL, describe, rows_sql
from app.engine.duckdb import QueryScope
from app.ingest.records import DecodedLine
from app.ingest.writer import LakeWriter
from app.templates.loader import parse_template
from app.templates.runtime import TemplateNormalizer
from tests.integration.test_schedules import make_lab

STARTER = Path(__file__).resolve().parents[3] / "templates" / "starter"
START = datetime(2026, 10, 28, tzinfo=UTC)


def _row(template_id: str, test: str, source: str, **change: Any) -> dict[str, Any]:
    t = parse_template((STARTER / f"{template_id}.yaml").read_text())
    record = json.loads(next(x.input for x in t.tests if x.name == test))
    record.update(change)
    text = json.dumps(record)
    return TemplateNormalizer(t, source).normalize(
        DecodedLine(text=text, bytes_invalid=False, truncated=False)
    )


def _write(engine: Any, extra: list[dict[str, Any]]) -> None:
    rows = [
        # one blocked consent, from both feeds
        _row("m365_directory_audit", "a blocked consent (Entra writes Unknown as the app name)",
             "m365_graph"),
        _row("m365_management_activity", "the same blocked consent from the Management API",
             "m365_mgmt"),
        # one granted consent
        _row("m365_directory_audit", "a granted admin consent names its app", "m365_graph"),
        *extra,
    ]  # fmt: skip
    LakeWriter(engine._lake).write(rows)


def test_both_feeds_count_once_and_blocked_is_apart(tmp_path: Path) -> None:
    engine = make_lab(tmp_path)["app"].state.engine
    _write(engine, [])
    granted, before, blocked, latest, latest_blocked = engine.run(
        COUNTS_SQL, QueryScope(None), {"start": START}
    ).rows[0]
    assert (granted, before, blocked) == (1, 0, 1)
    assert describe(latest) == "Lab Notes App (User.Read, Mail.Read) by admin@example.com"
    # No sign-in before it and no other record of the app id: no name to give.
    assert describe(latest_blocked) == (
        "an app with no name (openid, profile, email +2) by erin@example.com"
    )


def test_an_unknown_app_is_named_from_the_sign_in_just_before(tmp_path: Path) -> None:
    engine = make_lab(tmp_path)["app"].state.engine
    signin = _row(
        "m365_signin", "successful sign-in", "m365_signin",
        userPrincipalName="erin@example.com", createdDateTime="2026-10-28T16:39:40Z",
        appDisplayName="Lab Notes Beta", appId="0a1b2c3d-0000-4000-8000-0000000000b9",
    )  # fmt: skip
    too_early = _row(
        "m365_signin", "successful sign-in", "m365_signin",
        userPrincipalName="erin@example.com", createdDateTime="2026-10-28T16:30:00Z",
        appDisplayName="Something Else", appId="0a1b2c3d-0000-4000-8000-0000000000b8",
    )  # fmt: skip
    _write(engine, [signin, too_early])
    latest_blocked = engine.run(COUNTS_SQL, QueryScope(None), {"start": START}).rows[0][4]
    assert describe(latest_blocked).startswith("Lab Notes Beta (")


def test_a_sign_in_over_a_minute_before_does_not_name_it(tmp_path: Path) -> None:
    engine = make_lab(tmp_path)["app"].state.engine
    late = _row(
        "m365_signin", "successful sign-in", "m365_signin",
        userPrincipalName="erin@example.com", createdDateTime="2026-10-28T16:38:00Z",
        appDisplayName="Something Else", appId="0a1b2c3d-0000-4000-8000-0000000000b8",
    )  # fmt: skip
    _write(engine, [late])
    latest_blocked = engine.run(COUNTS_SQL, QueryScope(None), {"start": START}).rows[0][4]
    assert describe(latest_blocked).startswith("an app with no name")


def test_the_card_rows_open_in_search_one_per_consent(tmp_path: Path) -> None:
    lab = make_lab(tmp_path)
    engine = lab["app"].state.engine
    _write(engine, [])
    blocked = engine.run(rows_sql(True, START), QueryScope(None)).rows
    assert len(blocked) == 1 and len(blocked[0][-1]) == 2  # both feeds' event ids
    granted = engine.run(rows_sql(False, START), QueryScope(None)).rows
    assert [r[2] for r in granted] == ["Lab Notes App"]
    # The same SQL passes the guard as typed in Search.
    res = lab["admin"].post("/api/query", json={"sql": rows_sql(True, START)}, headers=lab["h"])
    assert res.status_code == 200, res.text


def test_the_consent_card_counts_granted_and_shows_blocked_apart(tmp_path: Path) -> None:

    from app.ai.watch_summary import _signal_cards

    engine = make_lab(tmp_path)["app"].state.engine
    _write(engine, [])
    kinds = {"m365": ["m365_graph", "m365_mgmt"], "telemetry": []}
    now = datetime(2026, 10, 29, 12, tzinfo=UTC)
    cards, sources = _signal_cards(engine, None, kinds, START, START - timedelta(days=1), now)
    consent = cards[0]
    assert (consent.value, consent.previous, consent.blocked) == (1, 0, 1)
    assert consent.context.startswith("Latest: Lab Notes App")
    assert consent.blocked_context.startswith("Blocked: an app with no name")
    assert consent.rows_sql and consent.blocked_sql and "status_id = 2" in consent.blocked_sql
    assert sources == ["m365_graph", "m365_mgmt"]
    # A viewer who may not read the M365 sources sees it restricted, with no SQL.
    cards, _ = _signal_cards(engine, ["other"], kinds, START, START - timedelta(days=1), now)
    assert cards[0].restricted and cards[0].rows_sql is None


def test_a_sign_in_stored_before_the_app_columns_still_names_it(tmp_path: Path) -> None:
    """Owner's install: the sign-ins were parsed before m365_signin 1.1.0, so only their
    message carries the app; 12 seconds before the blocked consent."""
    engine = make_lab(tmp_path)["app"].state.engine
    old = _row(
        "m365_signin", "successful sign-in", "m365_signin",
        userPrincipalName="erin@example.com", createdDateTime="2026-10-28T16:40:00Z",
        appDisplayName="Example Ads Portal", appId="0a1b2c3d-0000-4000-8000-0000000000b7",
    )  # fmt: skip
    old["resource_name"] = None
    old["resource_uid"] = None
    _write(engine, [old])
    latest_blocked = engine.run(COUNTS_SQL, QueryScope(None), {"start": START}).rows[0][4]
    assert describe(latest_blocked).startswith("Example Ads Portal (")
