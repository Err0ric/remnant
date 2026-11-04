"""`{{person:col}}` and `{{org_domains}}` in library SQL (ADR-0042 amendment 2026-11-04,
D205): people, not accounts, from Identities as it is when the query runs, with the
caller's own view; an account with no link stays its own person."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.ingest.records import DecodedLine
from app.ingest.writer import LakeWriter
from app.main import create_app
from app.search.ask_drill import drill_sql
from app.search.ask_summary import headline
from app.search.library import LIBRARY_DIR, load
from app.templates.loader import parse_template
from app.templates.runtime import TemplateNormalizer

ROOT = Path(__file__).resolve().parents[3]
Q = next(
    q for q in load(LIBRARY_DIR / "ai_agents" / "pack.yaml").queries
    if q.id == "agents_claude_code_users"
)  # fmt: skip
RANGE = {"start": "2026-10-01T00:00:00Z", "end": "2026-11-01T00:00:00Z"}


def _hook(t: str, session: str, host: str | None, **attr: str) -> str:
    resource = {"service_name": "claude-hooks", **({"host_name": host} if host else {})}
    return json.dumps({
        "signal": "log", "time": t, "service": "claude-hooks",
        "event": "claude_hooks.session_start",
        "attr": {"event_name": "claude_hooks.session_start", "session_id": session, **attr},
        "body": "claude_hooks.session_start", "resource": resource,
    })  # fmt: skip


LINES = [
    _hook("2026-10-20T10:00:00Z", "s1", "ws-alpha", claude_account_email="dana@example.com"),
    _hook("2026-10-25T10:00:00Z", "s2", "ws-alpha", claude_account_email="dana@example.org"),
    _hook("2026-10-21T09:00:00Z", "s3", "ws-zulu", claude_account_email="erin@example.com"),
    _hook("2026-10-19T09:00:00Z", "s4", "ws-bravo"),  # a session with no account or user
    _hook("2026-10-22T08:00:00Z", "doctor-1", None, test_record="true", plugin_variant="doctor"),
]


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    config = load_config(Path("missing.yaml"), {"APP__PATHS__DATA_DIR": str(tmp_path / "d")})
    app = create_app(config)
    spec = parse_template((ROOT / "templates" / "starter" / "claude_hooks.yaml").read_text())
    norm = TemplateNormalizer(spec, "claude_hooks")
    rows = [
        norm.normalize(DecodedLine(text=x, bytes_invalid=False, truncated=False)) for x in LINES
    ]
    LakeWriter(app.state.engine._lake).write(rows)
    app.state.identities.set_domains(["example.com"], "admin")
    return {"app": app, "c": TestClient(app)}


def _run(lab: dict[str, Any], sql: str = Q.sql, **params: Any) -> tuple[list[str], list[Any]]:
    res = lab["c"].post("/api/query", json={"sql": sql, **RANGE, "params": params})
    assert res.status_code == 200, res.text
    body = res.json()
    return body["columns"], body["rows"]


def test_unlinked_accounts_stay_their_own_person(lab: dict[str, Any]) -> None:
    cols, rows = _run(lab)
    by = {r[0]: dict(zip(cols, r, strict=True)) for r in rows}
    # dana@example.com is the organization's, so it is dana; the personal address has no
    # link, so it is its own person (never guessed from the name).
    assert set(by) == {"dana", "dana@example.org", "erin", "(no account reported)"}
    assert by["dana"]["accounts"] == "dana@example.com (work)"
    assert by["dana@example.org"]["accounts"] == "dana@example.org (personal)"
    assert by["(no account reported)"]["accounts"] == "(no account reported)"
    assert headline(cols, rows, False, Q.answer) == (
        "3 people, 3 accounts; most recent: dana@example.org on ws-alpha"
    )


def test_a_link_an_admin_made_groups_the_accounts_at_run_time(lab: dict[str, Any]) -> None:
    lab["app"].state.identities.set_alias("dana@example.org", "dana", "admin")
    cols, rows = _run(lab)
    by = {r[0]: dict(zip(cols, r, strict=True)) for r in rows}
    assert set(by) == {"dana", "erin", "(no account reported)"}
    assert by["dana"]["accounts"] == "dana@example.com (work), dana@example.org (personal)"
    assert by["dana"]["sessions"] == 2 and by["dana"]["machines"] == "ws-alpha"
    assert headline(cols, rows, False, Q.answer) == (
        "2 people, 3 accounts; most recent: dana on ws-alpha"
    )
    # Removing the link undoes it on the next run; nothing stored changed.
    lab["app"].state.identities.set_alias("dana@example.org", None, "admin")
    assert {r[0] for r in _run(lab)[1]} >= {"dana", "dana@example.org"}


def test_the_client_cannot_supply_the_identities_values(lab: dict[str, Any]) -> None:
    before = _run(lab)
    after = _run(lab, id_from="dana@example.org", id_to="erin", id_org="example.org")
    assert after == before


def test_show_events_for_a_person_resolves_the_same_way(lab: dict[str, Any]) -> None:
    lab["app"].state.identities.set_alias("dana@example.org", "dana", "admin")
    sql = drill_sql(Q.sql, ["person"], {"person": "dana"}, {})
    assert "{{person:actor_user_name}}" in sql and "{{org_domains}}" not in sql
    cols, rows = _run(lab, sql)
    assert len(rows) == 2
    assert {r[cols.index("actor_user_name")] for r in rows} == {
        "dana@example.com", "dana@example.org"
    }  # fmt: skip
