"""A source parsed by a template, end to end: file -> template -> lake -> query (SPEC 4)."""

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.main import create_app

FIXTURE = Path(__file__).parent.parent / "fixtures" / "logs" / "linux_sshd" / "sample.log"
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    logs = tmp_path / "logs" / "bastion"
    logs.mkdir(parents=True)
    shutil.copy(FIXTURE, logs / "auth.log")
    config = load_config(
        Path("missing.yaml"),
        {
            "APP__PATHS__DATA_DIR": str(tmp_path / "data"),
            "APP__PATHS__ALLOWED_ROOTS": str(tmp_path / "logs"),
        },
    )
    app = create_app(config)
    app.state.ingest._clock = lambda: NOW
    return {"app": app, "c": TestClient(app), "logs": logs}


def add(lab: dict[str, Any], **extra: Any) -> Any:
    body = {"source_id": "linux_auth", "format": "syslog", "path": str(lab["logs"]), **extra}
    return lab["c"].post("/api/sources", json=body)


def query(lab: dict[str, Any], sql: str) -> list[list[Any]]:
    res = lab["c"].post("/api/query", json={"sql": sql})
    assert res.status_code == 200, res.text
    rows: list[list[Any]] = res.json()["rows"]
    return rows


def test_template_source_lands_ocsf_columns(lab: dict[str, Any]) -> None:
    assert add(lab, template_id="linux_sshd").status_code == 201
    assert lab["app"].state.ingest.run_once() == 66
    rows = query(
        lab,
        "SELECT template_id, class_uid, count(*) FROM events GROUP BY 1, 2 ORDER BY 2",
    )
    # The one line the template does not model keeps its envelope and gets no class.
    assert rows == [["linux_sshd", 3002, 65], ["linux_sshd", None, 1]]
    (ok,) = query(lab, "SELECT count(*) FROM events WHERE parse_status = 'ok'")[0]
    assert ok >= 63
    first = FIXTURE.read_text().splitlines()[0]
    assert query(lab, "SELECT raw FROM events ORDER BY time LIMIT 1") == [[first]]
    failed = query(
        lab,
        "SELECT count(*) FROM events WHERE class_uid = 3002 AND status_id = 2"
        " AND actor_user_name IS NOT NULL AND src_endpoint_ip IS NOT NULL",
    )
    assert failed[0][0] > 5


def test_source_time_zone_overrides_the_template(lab: dict[str, Any]) -> None:
    add(lab, template_id="linux_sshd", timezone="America/New_York")
    lab["app"].state.ingest.run_once()
    # First line is "Oct  9 20:01:06" local time; New York is UTC-4 in October.
    assert query(lab, "SELECT min(time) FROM events WHERE raw LIKE '<38>%'")[0][0].startswith(
        "2026-10-10T00:01:06"
    )


def test_unknown_template_is_refused(lab: dict[str, Any]) -> None:
    res = add(lab, template_id="no_such_template")
    assert res.status_code == 400 and "no_such_template" in res.json()["detail"]


def test_missing_template_shows_as_a_source_error_not_a_silent_fallback(
    lab: dict[str, Any],
) -> None:
    add(lab, template_id="linux_sshd")
    lab["app"].state.templates._templates.pop("linux_sshd")
    assert lab["app"].state.ingest.run_once() == 0
    (src,) = lab["c"].get("/api/sources").json()
    assert src["status"]["state"] == "error"
    assert "linux_sshd is not available" in src["status"]["error"]


def test_templates_api(lab: dict[str, Any]) -> None:
    listed = lab["c"].get("/api/templates").json()
    sshd = next(t for t in listed if t["id"] == "linux_sshd")
    assert sshd["envelope"] == "syslog" and sshd["payload_format"] == "regex"
    assert sshd["class_uid"] == 3002 and sshd["category"] == "identity"
    assert lab["c"].get("/api/templates/problems").json() == []


MIXED = Path(__file__).parent.parent / "fixtures" / "mixed"


def test_automatic_source_parses_a_mixed_stream(lab: dict[str, Any]) -> None:
    """ADR-0012: one source, many products; each line lands with its own template."""
    shutil.copy(MIXED / "sample.log", lab["logs"] / "auth.log")
    assert add(lab, template_id="auto").status_code == 201
    assert lab["app"].state.ingest.run_once() == 23
    rows = query(lab, "SELECT template_id, count(*) FROM events GROUP BY 1 ORDER BY 1")
    expected = (MIXED / "expected_templates.txt").read_text().splitlines()
    assert dict((k, v) for k, v in rows) == {t: expected.count(t) for t in set(expected)}
    users = query(
        lab,
        "SELECT count(*) FROM events WHERE template_id = 'linux_sshd' AND src_endpoint_ip IS NOT NULL",
    )
    assert users == [[2]]


def test_parser_change_applies_to_new_lines_only_and_is_audited(lab: dict[str, Any]) -> None:
    c = lab["c"]
    add(lab)  # generic
    first = lab["app"].state.ingest.run_once()
    res = c.patch("/api/sources/linux_auth", json={"template_id": "linux_sshd"})
    assert res.status_code == 200, res.text
    assert res.json()["template_id"] == "linux_sshd"
    with (lab["logs"] / "auth.log").open("a") as fh:
        fh.write(
            "<38>Oct  9 21:00:00 db-01 sshd[1]: Accepted password for eve from 10.20.2.15 port 2 ssh2\n"
        )
    assert lab["app"].state.ingest.run_once() == 1
    rows = query(lab, "SELECT template_id, count(*) FROM events GROUP BY 1 ORDER BY 1")
    assert rows == [["generic_syslog", first], ["linux_sshd", 1]]
    audit = c.get("/api/audit/events", params={"action": "source.parser_change"})
    assert audit.status_code == 200
    changes = [e for e in audit.json() if e["action"] == "source.parser_change"]
    assert changes[0]["detail"] == {"source_id": "linux_auth", "from": None, "to": "linux_sshd"}


def test_parser_change_refuses_what_does_not_fit(lab: dict[str, Any]) -> None:
    c = lab["c"]
    lab["c"].post(
        "/api/sources",
        json={"source_id": "csvs", "format": "csv", "path": str(lab["logs"])},
    )
    res = c.patch("/api/sources/csvs", json={"template_id": "auto"})
    assert res.status_code == 400 and "not CSV" in res.json()["detail"]
    res = c.patch("/api/sources/csvs", json={"template_id": "no_such_template"})
    assert res.status_code == 400
    assert c.patch("/api/sources/csvs", json={}).status_code == 422
    assert c.patch("/api/sources/csvs", json={"template_id": None}).status_code == 200
