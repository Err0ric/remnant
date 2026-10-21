"""Changing a source's classification (Slice 5, SPEC 6.2): admin only, audited, and never
releasing events already stored under the stricter label."""

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from app.engine.duckdb import QueryScope
from tests.integration.test_schedules import make_lab


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    return make_lab(tmp_path)


def label(lab: dict[str, Any], source_id: str) -> str:
    (s,) = [x for x in lab["admin"].get("/api/sources").json() if x["source_id"] == source_id]
    return str(s["classification"])


def test_new_sources_default_to_local_only(lab: dict[str, Any]) -> None:
    assert label(lab, "lin_auth") == "local_only"


def test_admins_relabel_and_it_is_audited(lab: dict[str, Any]) -> None:
    body = {"classification": "cloud_allowed"}
    assert lab["ana"].patch("/api/sources/lin_auth", json=body).status_code == 403
    res = lab["admin"].patch("/api/sources/lin_auth", json=body, headers=lab["h"])
    assert res.status_code == 200 and res.json()["classification"] == "cloud_allowed"
    assert label(lab, "lin_auth") == "cloud_allowed"
    bad = lab["admin"].patch(
        "/api/sources/lin_auth", json={"classification": "public"}, headers=lab["h"]
    )
    assert bad.status_code == 422
    missing = lab["admin"].patch("/api/sources/nope", json=body, headers=lab["h"])
    assert missing.status_code == 404
    with sqlite3.connect(lab["db"]) as db:
        (detail,) = db.execute(
            "SELECT detail FROM audit_log WHERE action = 'source.classify'"
        ).fetchone()
    assert '"from":"local_only"' in detail and '"to":"cloud_allowed"' in detail


def test_relabelling_does_not_release_events_already_stored(lab: dict[str, Any]) -> None:
    gate = lab["app"].state.gate
    scope = QueryScope(sources=["lin_auth"])
    lab["admin"].patch(
        "/api/sources/lin_auth", json={"classification": "cloud_allowed"}, headers=lab["h"]
    )
    # The configuration now allows cloud, but the stored events say local_only.
    assert gate._local_only(scope, ["lin_auth"]) == ["lin_auth"]
    lab["admin"].patch(
        "/api/sources/win_dc", json={"classification": "local_only"}, headers=lab["h"]
    )
    assert gate._local_only(QueryScope(sources=["win_dc"]), ["win_dc"]) == ["win_dc"]
