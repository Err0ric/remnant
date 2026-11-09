"""The Identities values bound for {{person:...}} and {{org_domains}} are not readable on
their own, on any path that fills those placeholders (T70, D219). The MCP case, and the
guess over chosen values, are in test_mcp_identities.py, the suite that missed it.

ana is an analyst in a Linux group: she may not read the claude source, where dana's two
accounts and erin's are. Before the fix, naming `$id_from`, `$id_to`, or `$id_org` in her
own SQL returned the whole alias map and the organization domains. The CLI is an API
client (CLAUDE.md rule 15): its query command goes through POST /api/query, tested here
once through the CLI itself."""

from typing import Any

import pytest
from typer.testing import CliRunner

from app.cli import main as cli
from app.search import saved
from tests.integration.test_claude_hooks import lab  # noqa: F401  # the fixture
from tests.integration.test_mcp_identities import LEAKS, _setup

LEAK = LEAKS[0]
RANGE = {"start": "2000-01-01T00:00:00Z", "end": "2100-01-01T00:00:00Z"}


def _shows_the_map(text: str) -> bool:
    return "dana@example.org" in text or '"example.com"' in text or "'example.com'" in text


def test_logs_sql(lab: dict[str, Any]) -> None:  # noqa: F811
    _setup(lab)
    for sql in LEAKS:
        res = lab["ana"].post("/api/query", json={"sql": sql, **RANGE})
        assert res.status_code == 400 and not _shows_the_map(res.text), (sql, res.text)


def test_logs_sql_guess_is_its_own_person(lab: dict[str, Any]) -> None:  # noqa: F811
    """The yes/no trick through Logs SQL: a guess at an account ana cannot read is its own
    person, and she gets no organization domain her events do not show."""
    _setup(lab)
    sql = "SELECT {{person:u}} AS p, {{org_domains}} AS d FROM (VALUES ('dana@example.org')) t(u)"
    res = lab["ana"].post("/api/query", json={"sql": sql, **RANGE})
    assert res.status_code == 200, res.text
    assert res.json()["rows"] == [["dana@example.org", [""]]]


def test_csv_export(lab: dict[str, Any]) -> None:  # noqa: F811
    _setup(lab)
    res = lab["ana"].post("/api/query/export", json={"sql": LEAK, **RANGE})
    assert res.status_code == 400 and not _shows_the_map(res.text), res.text


def test_facets(lab: dict[str, Any]) -> None:  # noqa: F811
    _setup(lab)
    sql = "SELECT *, $id_from AS a FROM events WHERE {{person:actor_user_name}} IS NOT NULL"
    body = {"sql": sql, **RANGE, "columns": ["actor_user_name"]}
    res = lab["ana"].post("/api/search/facets", json=body)
    assert res.status_code == 400 and not _shows_the_map(res.text), res.text


def test_saving_such_a_search_is_refused(lab: dict[str, Any]) -> None:  # noqa: F811
    _setup(lab)
    for body in (
        {"id": "leak", "name": "Leak", "sql": LEAK},
        # A parameter named like a bound value would have been overwritten by it.
        {"id": "leak2", "name": "Leak", "sql": "SELECT {{org_domains}} AS d, {{id_from}} AS a",
         "params": [{"name": "id_from", "type": "string", "default": "x"}]},
    ):  # fmt: skip
        res = lab["ana"].post("/api/searches", json=body)
        assert res.status_code == 400, res.text


@pytest.fixture
def old_searches(lab: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> list[str]:  # noqa: F811
    """Two of ana's searches saved before this release, when the save-time check let
    them through: each must still be refused when it runs."""
    _setup(lab)
    monkeypatch.setattr(saved, "validate_definition", lambda spec: None)
    made = []
    for sid, body in (
        ("leak", {"sql": LEAK}),
        ("leak2", {"sql": "SELECT {{org_domains}} AS d, {{id_from}} AS a",
                   "params": [{"name": "id_from", "type": "string", "default": "x"}]}),
    ):  # fmt: skip
        res = lab["ana"].post("/api/searches", json={"id": sid, "name": sid, **body})
        assert res.status_code == 201, res.text
        made.append(sid)
    monkeypatch.undo()
    return made


def test_saved_search_run(lab: dict[str, Any], old_searches: list[str]) -> None:  # noqa: F811
    for sid in old_searches:
        res = lab["ana"].post(f"/api/searches/{sid}/run", json=RANGE)
        assert res.status_code == 400 and not _shows_the_map(res.text), (sid, res.text)


def test_scheduled_run(lab: dict[str, Any], old_searches: list[str]) -> None:  # noqa: F811
    for sid in old_searches:
        made = lab["ana"].post(
            "/api/schedules",
            json={"kind": "search", "target_id": sid, "cron": "daily", "lookback_minutes": 60},
        )
        assert made.status_code == 201, made.text
        run = lab["ana"].post(f"/api/schedules/{made.json()['schedule_id']}/run")
        assert not _shows_the_map(run.text), (sid, run.text)
        if run.status_code == 200:
            assert run.json()["status"] != "ok", run.text


def test_cli_query(lab: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:  # noqa: F811
    _setup(lab)
    monkeypatch.setattr(cli, "client_factory", lambda creds: lab["ana"])
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("REMNANT_TOKEN", raising=False)
    monkeypatch.delenv("REMNANT_SERVER", raising=False)
    res = CliRunner().invoke(cli.app, ["query", "--since", "3650d", "--format", "json", LEAK])
    assert res.exit_code != 0 and not _shows_the_map(res.stdout + res.stderr), res.stdout


def test_the_admin_identities_page_is_unchanged(lab: dict[str, Any]) -> None:  # noqa: F811
    """The administrator still reads and edits the map where it lives; ana still cannot."""
    _setup(lab)
    page = lab["admin"].get("/api/identities", headers=lab["h"])
    assert page.status_code == 200 and "dana@example.org" in page.text
    assert lab["ana"].get("/api/identities").status_code == 403


INVESTIGATE = "start=2000-01-01T00:00:00Z&end=2100-01-01T00:00:00Z"


def test_investigate_pages_show_only_the_links_the_scope_shows(lab: dict[str, Any]) -> None:  # noqa: F811
    """Found in the same review: Investigate's "open in Search" SQL listed every account
    linked to a person, and the organization domains, whatever the caller could read.
    alice is in ana's Linux events; her linked address and dana's two accounts are not."""
    _setup(lab)
    lab["app"].state.identities.set_alias("alice@example.org", "alice", "admin")
    for path in (
        f"/api/entities/summary?kind=user&value=dana&{INVESTIGATE}",
        f"/api/entities/graph?kind=user&value=dana&{INVESTIGATE}",
        f"/api/entities/risk?{INVESTIGATE}",
    ):
        res = lab["ana"].get(path)
        assert res.status_code == 200, res.text
        assert not _shows_the_map(res.text) and "alice@example.org" not in res.text, path
    # The administrator reads the claude source: dana's page still lists both accounts.
    res = lab["admin"].get(
        f"/api/entities/summary?kind=user&value=dana&{INVESTIGATE}", headers=lab["h"]
    )
    assert "dana@example.org" in res.json()["search_sql"]
