"""Owner, 2026-11-08 (option A for #451): the person page's sign-ins, the Microsoft 365 tab
lists, and the Sources page counts are built and run by the server, on the caller's events
view, audited `query.view`. A source the caller may not read stays invisible through every
one of them, and Auditors can read them."""

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.ingest.writer import LakeWriter
from tests.integration.test_m365_consents import _row
from tests.integration.test_schedules import make_lab

# The Microsoft 365 rows below are from 2026-10-14; the person page reads the last 7 days.
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
SPAN = "&start=2026-10-01T00:00:00Z&end=2026-10-16T00:00:00Z"


@pytest.fixture
def lab(tmp_path: Path, pin_now: Callable[[datetime], None]) -> Any:
    pin_now(NOW)
    out = make_lab(tmp_path)
    admin, h = out["admin"], out["h"]
    # An Automatic source over the Windows folder, and Microsoft 365 rows in a source of
    # their own: only admin may read either. Ana, Bob, and the auditor read Linux only.
    body = {
        "source_id": "win_auto", "format": "syslog",
        "path": str(tmp_path / "logs" / "win"), "template_id": "auto",
    }  # fmt: skip
    assert admin.post("/api/sources", json=body, headers=h).status_code == 201
    out["app"].state.ingest.run_once()
    LakeWriter(out["app"].state.engine._lake).write(
        [
            _row("m365_signin", "successful sign-in", "m365_x"),
            _row("m365_signin", "risky failed sign-in", "m365_x"),
            _row("m365_management_activity", "DLP rule match", "m365_x"),
        ]
    )
    return out


def _first_column(body: dict[str, Any]) -> set[str]:
    return {str(r[0]) for r in body["rows"]}


def test_sources_page_counts_only_readable_sources(lab: dict[str, Any]) -> None:
    admin, ana = lab["admin"], lab["ana"]
    assert _first_column(admin.get("/api/sources/event-counts").json()) >= {
        "win_dc", "lin_auth", "m365_x",
    }  # fmt: skip
    assert _first_column(ana.get("/api/sources/event-counts").json()) == {"lin_auth"}
    assert _first_column(admin.get("/api/sources/parser-mix").json()) == {"win_auto"}
    assert ana.get("/api/sources/parser-mix").json()["rows"] == []


def test_m365_lists_and_person_sign_ins_hide_a_restricted_source(lab: dict[str, Any]) -> None:
    admin, ana = lab["admin"], lab["ana"]
    for path in (
        "/api/m365/list?name=dlp" + SPAN,
        "/api/m365/list?name=sign_ins" + SPAN,
        "/api/m365/list?name=sign_ins&cls=failed&mode=interactive" + SPAN,
        "/api/m365/list?name=admin" + SPAN,
        "/api/m365/list?name=mail" + SPAN,
        "/api/people/alice@example.com/signins",
    ):
        mine = admin.get(path)
        theirs = ana.get(path)
        assert mine.status_code == theirs.status_code == 200, (path, mine.text, theirs.text)
        assert theirs.json()["rows"] == [] and theirs.json()["sources"] == [], path
        if "admin" not in path and "mail" not in path:
            assert mine.json()["rows"], path  # the rows exist; only ana cannot see them
    signins = admin.get("/api/people/alice@example.com/signins").json()
    assert signins["columns"][:3] == ["time", "actor_user_name", "app"]
    assert {r[1] for r in signins["rows"]} == {"alice@example.com"}


def test_only_known_lists_run(lab: dict[str, Any]) -> None:
    """The client names a list and a filter; it never sends SQL text."""
    ana = lab["ana"]
    assert ana.get("/api/m365/list?name=drop" + SPAN).status_code == 400
    assert ana.get("/api/m365/list?name=sign_ins&cls=x&mode=all" + SPAN).status_code == 400


def test_auditors_read_them_and_every_call_is_audited(lab: dict[str, Any]) -> None:
    aud = lab["aud"]
    assert _first_column(aud.get("/api/sources/event-counts").json()) == {"lin_auth"}
    assert aud.get("/api/m365/list?name=dlp" + SPAN).status_code == 200
    with sqlite3.connect(lab["db"]) as con:
        views = {
            r[0]
            for r in con.execute(
                "SELECT json_extract(detail, '$.view') FROM audit_log"
                " WHERE action = 'query.view' AND user_id = ?",
                (lab["ids"]["aud"],),
            )
        }
    assert views == {"sources.counts", "m365.dlp"}
