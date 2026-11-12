"""This server's own sign-ins and changes are searchable in Logs (handoff item 9).

A sign-in from a client address lands in the built-in `server_events` source with the user
id and status, and the address finds it through the plain search and through SQL. Never a
password, token, cookie, or query string in the stored line. The refusal detection still
counts refusals only, and Health keeps the source out of the quiet list.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.main import create_app

T0 = datetime(2026, 11, 8, 9, 0, tzinfo=UTC)
BASE = "https://siem.example.internal"
ADMIN_PW = "correct horse battery"
CLIENT_IP = "203.0.113.50"


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    config = load_config(
        Path("missing.yaml"),
        {
            "APP__PATHS__DATA_DIR": str(tmp_path / "data"),
            "APP__PATHS__ALLOWED_ROOTS": str(tmp_path),
            "APP__SERVER__HOST": "0.0.0.0",
            "APP__SERVER__PUBLIC_NAMES": "siem.example.internal",
        },
    )
    app = create_app(config)
    app.state.server_events._clock = lambda: T0
    setup = TestClient(app, base_url=BASE)
    token = app.state.auth.setup_url("siem.example.internal", 8080).split("#", 1)[1]
    res = setup.post("/api/setup", json={"token": token, "username": "admin", "password": ADMIN_PW})
    assert res.status_code == 201, res.text
    return {"app": app, "setup": setup}


def _query(c: TestClient, h: dict[str, str], sql: str, **params: Any) -> list[list[Any]]:
    window = {
        "start": (T0 - timedelta(hours=1)).isoformat(),
        "end": (T0 + timedelta(hours=1)).isoformat(),
    }
    res = c.post("/api/query", json={"sql": sql, "params": params, **window}, headers=h)
    assert res.status_code == 200, res.text
    rows: list[list[Any]] = res.json()["rows"]
    return rows


def test_a_sign_in_from_an_address_is_found_in_logs_with_the_user_and_status(
    lab: dict[str, Any],
) -> None:
    app = lab["app"]
    c = TestClient(app, base_url=BASE, client=(CLIENT_IP, 50123))
    wrong = c.post("/api/auth/login", json={"username": "admin", "password": "wrong-password-9"})
    assert wrong.status_code == 401
    signed = c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PW})
    assert signed.status_code == 200, signed.text
    h = {"X-CSRF-Token": signed.json()["csrf_token"]}
    user_id = signed.json()["user"]["user_id"]
    # A change with a query string: the record keeps the route, never the query.
    c.post("/api/searches?secret_q=hunter2", json={"name": "x"}, headers=h)
    c.get("/api/sources")  # a read: not recorded
    assert app.state.server_events.flush() >= 3
    app.state.ingest.run_once()

    compiled = c.post("/api/search/compile", json={"text": CLIENT_IP}, headers=h).json()
    found = _query(c, h, compiled["sql"], **compiled["params"])
    assert found, "the plain search finds the address"
    rows = _query(
        c,
        h,
        "SELECT message, actor_user_name, status_id, class_uid, status_detail, raw FROM events"
        " WHERE source_id = 'server_events' AND src_endpoint_ip = $ip ORDER BY time, raw",
        ip=CLIENT_IP,
    )
    by_kind: dict[str, list[list[Any]]] = {}
    for r in rows:
        by_kind.setdefault(r[0], []).append(r)
    (sign_in,) = by_kind["server.sign_in"]
    assert sign_in[1:4] == ["admin", 1, 3002]
    assert f'"user_id":"{user_id}"' in sign_in[5] and '"method":"password"' in sign_in[5]
    assert by_kind["server.refused.sign_in"][0][2] == 2
    logins = [r for r in by_kind["server.request"] if r[4] == "/api/auth/login"]
    assert sorted('"status":200' in r[5] for r in logins) == [False, True]
    assert all(r[3] == 6003 and '"duration_ms":' in r[5] for r in by_kind["server.request"])
    paths = {r[4] for r in by_kind["server.request"]}
    assert "/api/searches" in paths and "/api/sources" not in paths
    every_raw = " ".join(r[5] for r in rows)
    cookies = [v for v in c.cookies.values() if v]
    for secret in (ADMIN_PW, "wrong-password-9", "hunter2", "secret_q", "?", "csrf", "cookie"):
        assert secret not in every_raw.lower()
    assert h["X-CSRF-Token"] not in every_raw and cookies
    assert not any(v in every_raw for v in cookies)
    assert '"session":"browser"' in every_raw  # the session kind, never its token

    # The refusal detection counts the one refused sign-in, not the sign-in or requests.
    from app.search.refusals import COUNT_SQL

    counted = _query(c, h, COUNT_SQL.replace("$threshold", "1"))
    assert [(r[0], r[1]) for r in counted] == [(CLIENT_IP, 1)]

    # Health and the footer: the source has events now, and is still never called quiet.
    o = c.get("/api/overview").json()
    (mine,) = [s for s in o["sources"] if s["source_id"] == "server_events"]
    assert mine["quiet_expected"] is True and mine["condition"] != "quiet"
    assert "server_events" not in [q["source_id"] for q in o["source_summary"]["quiet"]]


def test_health_polling_reads_and_static_assets_are_not_recorded(lab: dict[str, Any]) -> None:
    app = lab["app"]
    c = lab["setup"]
    for path in ("/api/health", "/api/overview", "/assets/x.js", "/"):
        c.get(path)
    c.post("/api/otlp/v1/logs", content=b"{}", headers={"Authorization": "Bearer rmt_x"})
    app.state.server_events.flush()
    spool = Path(app.state.config.paths.data_dir) / "spool" / "server_events"
    text = "".join(p.read_text() for p in spool.glob("*.jsonl")) if spool.is_dir() else ""
    assert '"path":"/api/setup"' in text  # a change is recorded, by its route
    for read in ("/api/health", "/api/overview", "/assets", '"path":"/"', "/api/otlp"):
        assert read not in text
    assert "server.refused.otlp_token" in text  # its refusal still is


def _spooled(app: Any) -> str:
    app.state.server_events.flush()
    spool = Path(app.state.config.paths.data_dir) / "spool" / "server_events"
    return "".join(p.read_text() for p in spool.glob("*.jsonl")) if spool.is_dir() else ""


def test_a_query_a_count_and_a_dashboard_refresh_write_nothing(lab: dict[str, Any]) -> None:
    """Owner, 2026-11-10: server_events holds sign-ins, changes, exports, and denials, never
    reads, even reads sent as POST (they stay in the audit log, rule 14)."""
    app = lab["app"]
    c = TestClient(app, base_url=BASE, client=(CLIENT_IP, 50123))
    signed = c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PW})
    h = {"X-CSRF-Token": signed.json()["csrf_token"]}
    before = _spooled(app).count('"server.request"')
    _query(c, h, "SELECT message FROM events LIMIT 5")  # a search
    _query(c, h, "SELECT count(*) FROM events")  # a count
    c.post("/api/search/compile", json={"text": CLIENT_IP}, headers=h)
    c.post("/api/search/facets", json={"sql": "SELECT * FROM events"}, headers=h)
    for path in ("/api/dashboards", "/api/dashboard/sections?window=24h&part=identity"):
        c.get(path)  # a dashboard refresh
    text = _spooled(app)
    assert text.count('"server.request"') == before
    for read in ("/api/query", "/api/search/compile", "/api/search/facets", "/api/dashboard"):
        assert f'"path":"{read}' not in text
    with app.state.meta.connect() as con:  # still attributable: the audit log has the query
        assert con.execute("SELECT count(*) FROM audit_log WHERE action = 'query.run'").fetchone()[
            0
        ]


def test_a_denied_request_is_recorded_even_when_it_only_reads(lab: dict[str, Any]) -> None:
    app = lab["app"]
    c = TestClient(app, base_url=BASE, client=(CLIENT_IP, 50124))
    assert c.post("/api/query", json={"sql": "SELECT 1"}).status_code in (401, 403)
    assert c.get("/api/users").status_code in (401, 403)
    text = _spooled(app)
    assert '"path":"/api/query"' in text and '"path":"/api/users"' in text
    assert '"outcome":"failure"' in text


@pytest.mark.parametrize(
    "sql",
    [
        "ATTACH 'x.db' AS x",
        "SELECT * FROM read_csv('/etc/passwd')",
        "COPY (SELECT 1) TO 'out.csv'",
        "SELECT 1; SELECT 2",
        "SELECT getenv('HOME')",
    ],
)
def test_a_query_the_guard_blocks_is_recorded(lab: dict[str, Any], sql: str) -> None:
    """Owner, 2026-11-10: guard refusals (blocked statements and functions) are recorded,
    with the user; the answer the caller sees is unchanged."""
    app = lab["app"]
    c = TestClient(app, base_url=BASE, client=(CLIENT_IP, 50125))
    signed = c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PW})
    h = {"X-CSRF-Token": signed.json()["csrf_token"]}
    before = _spooled(app).count('"path":"/api/query"')
    res = c.post("/api/query", json={"sql": sql}, headers=h)
    assert res.status_code == 400 and res.json()["code"] == "query_rejected", res.text
    text = _spooled(app)
    assert text.count('"path":"/api/query"') == before + 1
    assert '"status":400' in text and '"username":"admin"' in text


@pytest.mark.parametrize(
    "sql", ["SELEC message FROM events", "SELECT nope FROM events", "SELECT * FROM missing"]
)
def test_a_plain_sql_mistake_is_not_recorded(lab: dict[str, Any], sql: str) -> None:
    app = lab["app"]
    c = TestClient(app, base_url=BASE, client=(CLIENT_IP, 50126))
    signed = c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PW})
    h = {"X-CSRF-Token": signed.json()["csrf_token"]}
    before = _spooled(app).count('"server.request"')
    assert c.post("/api/query", json={"sql": sql}, headers=h).status_code == 400
    assert _spooled(app).count('"server.request"') == before


def test_every_route_that_changes_something_is_recorded_or_named_read_only() -> None:
    """A new endpoint must be put on one list or the other, so changes are never dropped."""
    import tempfile

    from app.ingest.server_events import READ_ONLY, RECORDED, SKIP_PREFIXES

    d = tempfile.mkdtemp()
    app = create_app(
        load_config(
            Path("missing.yaml"), {"APP__PATHS__DATA_DIR": d, "APP__PATHS__ALLOWED_ROOTS": d}
        )
    )
    routes = {
        (m.upper(), p)
        for p, ops in app.openapi()["paths"].items()
        for m in ops
        if m.upper() not in ("GET", "HEAD", "OPTIONS") and not p.startswith(SKIP_PREFIXES)
    }
    assert not RECORDED & READ_ONLY
    assert routes - RECORDED - READ_ONLY == set(), "classify the new route in server_events.py"
    assert {r for r in RECORDED | READ_ONLY if r[0] != "GET"} - routes == set(), "stale entries"
