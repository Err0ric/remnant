from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import AppConfig, load_config
from app.ingest.framer import Framer
from app.ingest.normalizer import Normalizer, SourceSpec
from app.ingest.records import decode_frame
from app.ingest.writer import LakeWriter
from app.main import create_app

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    n = Normalizer(SourceSpec(source_id="linux_auth", format="syslog"), clock=lambda: NOW)
    data = b"<38>Oct  9 20:41:12 bastion sshd[1]: Accepted publickey for jordan\n<38>Oct  9 21:00:00 bastion sshd[2]: Failed password for admin\n"
    rows = [r for f in Framer().frames([data]) if (r := n.normalize(decode_frame(f)))]
    LakeWriter(tmp_path / "lake").write(rows)
    return tmp_path


def client(data_dir: Path, **env: str) -> TestClient:
    config = load_config(Path("missing.yaml"), {"APP__PATHS__DATA_DIR": str(data_dir), **env})
    return TestClient(create_app(config))


def test_query_returns_rows(data_dir: Path) -> None:
    res = client(data_dir).post("/api/query", json={"sql": "SELECT count(*) AS n FROM events"})
    assert res.status_code == 200
    body = res.json()
    assert body["columns"] == ["n"] and body["rows"] == [[2]]
    assert body["sources"] == ["linux_auth"]
    assert body["executed_sql"].upper().endswith("LIMIT 10000")


def test_time_range_and_source_filter(data_dir: Path) -> None:
    res = client(data_dir).post(
        "/api/query",
        json={
            "sql": "SELECT message FROM events",
            "start": "2026-10-09T20:50:00Z",
            "end": "2026-10-09T23:00:00Z",
            "sources": ["linux_auth", "not_a_source"],
        },
    )
    assert res.json()["rows"] == [["Failed password for admin"]]


def test_guard_rejection_is_a_400_with_reason(data_dir: Path) -> None:
    res = client(data_dir).post("/api/query", json={"sql": "DROP TABLE events"})
    assert res.status_code == 400
    assert res.json()["code"] == "query_rejected"


def test_runtime_error_is_a_400(data_dir: Path) -> None:
    res = client(data_dir).post("/api/query", json={"sql": "SELECT no_such_column FROM events"})
    assert res.status_code == 400
    assert res.json()["code"] == "query_failed"


def test_network_bind_without_accounts_is_closed(data_dir: Path) -> None:
    c = client(data_dir, APP__SERVER__HOST="0.0.0.0")
    res = c.post("/api/query", json={"sql": "SELECT 1"})
    assert res.status_code == 403
    assert res.json()["code"] == "setup_required"


def test_default_config_is_loopback_and_open() -> None:
    assert AppConfig().server.host == "127.0.0.1"


def test_slow_query_times_out_through_the_api(tmp_path: Path) -> None:
    from app.core.config import load_config
    from app.engine.duckdb import QueryEngine
    from app.ingest.normalizer import Normalizer, SourceSpec
    from app.ingest.records import DecodedLine
    from app.ingest.writer import LakeWriter
    from app.main import create_app

    norm = Normalizer(SourceSpec(source_id="bulk", format="json"))
    rows = [
        norm.normalize(DecodedLine(text=f'{{"n": {i}}}', bytes_invalid=False, truncated=False))
        for i in range(3000)
    ]
    LakeWriter(tmp_path / "lake").write([r for r in rows if r is not None])
    app = create_app(load_config(Path("missing.yaml"), {"APP__PATHS__DATA_DIR": str(tmp_path)}))
    app.state.engine = QueryEngine(tmp_path / "lake", timeout_s=0.3)
    slow = "SELECT count(*) FROM events a, events b, events c WHERE a.raw || b.raw <> c.raw"
    res = TestClient(app).post("/api/query", json={"sql": slow})
    assert res.status_code == 408
    assert res.json()["code"] == "query_timeout"


def test_export_is_csv_escaped_and_audited(data_dir: Path) -> None:
    import csv
    import io
    import sqlite3

    c = client(data_dir)
    sql = "SELECT '=HYPERLINK(\"http://x\")' AS f, 42 AS n, message FROM events ORDER BY message"
    res = c.post("/api/query/export", json={"sql": sql})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert "attachment" in res.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(res.text)))
    assert rows[0] == ["f", "n", "message"]
    assert rows[1][0] == '\'=HYPERLINK("http://x")' and rows[1][1] == "42"
    db = sqlite3.connect(data_dir / "meta.sqlite")
    actions = [r[0] for r in db.execute("SELECT action FROM audit_log")]
    assert actions == ["query.export"]


def test_export_rejected_sql_is_audited_as_failure(data_dir: Path) -> None:
    import sqlite3

    res = client(data_dir).post("/api/query/export", json={"sql": "DROP TABLE events"})
    assert res.status_code == 400
    db = sqlite3.connect(data_dir / "meta.sqlite")
    assert db.execute("SELECT action, outcome FROM audit_log").fetchall() == [
        ("query.export", "failure")
    ]


def test_placeholders_bind_like_a_saved_search(data_dir: Path) -> None:
    """Install finding 13: {{start}}/{{end}} come from the range, other names from params."""
    sql = (
        "SELECT message FROM events WHERE time BETWEEN {{start}} AND {{end}}"
        " AND actor_process_name = {{prog}}"
    )
    c = client(data_dir)
    res = c.post(
        "/api/query",
        json={
            "sql": sql,
            "start": "2026-10-09T20:50:00Z",
            "end": "2026-10-09T23:00:00Z",
            "params": {"prog": "sshd"},
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["rows"] == [["Failed password for admin"]]
    # No range: start is the beginning of time and end is now.
    res = c.post("/api/query", json={"sql": sql, "params": {"prog": "sshd"}})
    assert len(res.json()["rows"]) == 2
    missing = c.post("/api/query", json={"sql": sql})
    assert missing.status_code == 400 and "{{prog}}" in missing.json()["detail"]
