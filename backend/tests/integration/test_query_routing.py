"""Every surface that runs user or model SQL uses the locked per-query connection (T2,
ADR-0047): a new connection from `_connect`, limited to the files its views read, never a
kept page instance (`server.query_pool`, D146). The kept pool is switched on for every
query here, so a surface that asked for a page instance would get one and fail."""

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pytest

import app.engine.duckdb as engine_mod
from app.cli.client import Api, Credentials
from app.engine.duckdb import QueryEngine
from app.llm.locality import Endpoint
from app.llm.provider import ProviderResponse
from app.llm.registry import ProviderRecord, ProviderStore
from tests.integration.test_mcp import settings, tool
from tests.integration.test_schedules import make_lab, run_now, schedule

ROUTE_PROMPT = "You route a security analyst's question"
WIDE = {"start": "2000-01-01T00:00:00Z", "end": "2100-01-01T00:00:00Z"}


@dataclass
class Run:
    sql: str
    kept: bool  # ran on a kept page instance
    locked: bool  # allowed_paths only (no folder but DuckDB's spill folder), config locked


@dataclass
class Spy:
    runs: list[Run] = field(default_factory=list)
    kept: set[int] = field(default_factory=set)

    def of(self, marker: str) -> list[Run]:
        return [r for r in self.runs if marker in r.sql]


def _locked(con: duckdb.DuckDBPyConnection) -> bool:
    got = dict(
        con.execute(
            "SELECT name, value FROM duckdb_settings() WHERE name IN"
            " ('allowed_directories', 'temp_directory', 'lock_configuration',"
            " 'enable_external_access', 'autoload_known_extensions')"
        ).fetchall()
    )
    dirs = got["allowed_directories"].strip("[]").rstrip("/")
    spill = got["temp_directory"].rstrip("/")
    return (
        got["lock_configuration"] == "true"
        and got["enable_external_access"] == "false"
        and got["autoload_known_extensions"] == "false"
        and (dirs == "" or Path(dirs).resolve() == Path(spill).resolve())
    )


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> Iterator[Spy]:
    out = Spy()
    check = engine_mod._select_only
    take = QueryEngine._take_kept
    execute = QueryEngine._execute

    def select_only(con: duckdb.DuckDBPyConnection, sql: str) -> None:
        out.runs.append(Run(sql, id(con) in out.kept, _locked(con)))
        check(con, sql)

    def take_kept(self: QueryEngine) -> Any:
        kept = take(self)
        out.kept.add(id(kept[1]))
        return kept

    def pooled_execute(self: QueryEngine, *a: Any, **k: Any) -> Any:
        self.pool = True  # any query asking for a page instance gets one
        return execute(self, *a, **k)

    monkeypatch.setattr(engine_mod, "_select_only", select_only)
    monkeypatch.setattr(QueryEngine, "_take_kept", take_kept)
    monkeypatch.setattr(QueryEngine, "_execute", pooled_execute)
    yield out


@pytest.fixture
def lab(tmp_path: Path, pin_now: Callable[[datetime], None]) -> dict[str, Any]:
    pin_now(datetime(2026, 10, 20, 12, 0, tzinfo=UTC))
    out = make_lab(tmp_path)
    calls: dict[str, Any] = {"route": {"kind": "data", "query": None, "params": {}}, "sql": ""}

    class Fake:
        def __init__(self, record: ProviderRecord, endpoint: Endpoint) -> None:
            self.provider_id, self.locality = record.provider_id, endpoint.locality

        def chat(self, messages: list[Any], *_: object, **__: object) -> ProviderResponse:
            if ROUTE_PROMPT in messages[0].content:
                return ProviderResponse(text=json.dumps(calls["route"]), model="m")
            body = {"sql": calls["sql"], "explanation": "Counted.", "assumptions": []}
            return ProviderResponse(text=json.dumps(body), model="m")

    out["app"].state.gate._factory = lambda r, _s, e: Fake(r, e)
    store: ProviderStore = out["app"].state.providers
    local = store.all()[0]
    store.update(local.provider_id, None, "http://127.0.0.1:11434/v1", "m", True, None, False)
    out["calls"] = calls
    return out


def probe(name: str) -> str:
    return f"SELECT source_id, count(*) AS n FROM events WHERE raw <> 'probe-{name}' GROUP BY 1"


def assert_locked(spy: Spy, marker: str) -> None:
    runs = spy.of(f"probe-{marker}")
    assert runs, f"{marker}: the SQL never reached the engine"
    for run in runs:
        assert not run.kept, f"{marker}: ran on a kept page instance"
        assert run.locked, f"{marker}: ran on a connection that is not locked"


def test_logs_sql_query_endpoint(lab: dict[str, Any], spy: Spy) -> None:
    res = lab["ana"].post("/api/query", json={"sql": probe("logs"), **WIDE})
    assert res.status_code == 200, res.text
    assert_locked(spy, "logs")


def test_cli_query(lab: dict[str, Any], spy: Spy) -> None:
    api = Api(
        Credentials(server="https://siem.example.internal", token=None), lambda _c: lab["ana"]
    )
    out = api.query(probe("cli"), **WIDE)
    assert out["rows"]
    assert_locked(spy, "cli")


def test_export(lab: dict[str, Any], spy: Spy) -> None:
    res = lab["ana"].post("/api/query/export", json={"sql": probe("export"), **WIDE})
    assert res.status_code == 200, res.text
    assert_locked(spy, "export")


def _saved(lab: dict[str, Any], name: str) -> str:
    body = {
        "id": f"probe_{name}",
        "name": f"Probe {name}",
        "sql": probe(name).replace(
            "GROUP BY 1", "AND time BETWEEN {{start}} AND {{end}} GROUP BY 1"
        ),
        "visibility": "private",
    }
    res = lab["ana"].post("/api/searches", json=body)
    assert res.status_code == 201, res.text
    return str(body["id"])


def test_saved_search_run(lab: dict[str, Any], spy: Spy) -> None:
    sid = _saved(lab, "saved")
    res = lab["ana"].post(f"/api/searches/{sid}/run", json=WIDE)
    assert res.status_code == 200, res.text
    assert_locked(spy, "saved")


def test_schedule_run(lab: dict[str, Any], spy: Spy) -> None:
    sid = _saved(lab, "schedule")
    made = schedule(lab["ana"], target_id=sid)
    assert made.status_code == 201, made.text
    res = run_now(lab, lab["ana"], made.json()["schedule_id"])
    assert res.status_code == 200, res.text
    assert_locked(spy, "schedule")


def test_ask_auto_run_and_its_self_check(lab: dict[str, Any], spy: Spy) -> None:
    lab["calls"]["sql"] = probe("ask")
    body = lab["ana"].post("/api/ask", json={"question": "events per source"}).json()
    assert body["auto_run"] is True, body
    res = lab["ana"].post(f"/api/ask/{body['ask_id']}/run")
    assert res.status_code == 200, res.text
    assert len(spy.of("probe-ask")) >= 2  # the self-check preview and the run
    assert_locked(spy, "ask")


def test_show_events(lab: dict[str, Any], spy: Spy) -> None:
    lab["calls"]["route"] = {"kind": "data", "query": "linux_auth/ssh_logins", "params": {}}
    ana = lab["ana"]
    body = ana.post("/api/ask", json={"question": "SSH logins for alice@example.com"}).json()
    run = ana.post(f"/api/ask/{body['ask_id']}/run").json()
    cols, first = run["columns"], run["rows"][0]
    values = {k: first[cols.index(k)] for k in run["drill_keys"]}
    before = len(spy.runs)
    drill = ana.post(f"/api/ask/{body['ask_id']}/drill", json={"values": values})
    assert drill.status_code == 200, drill.text
    assert len(spy.runs) == before  # Show events builds SQL; Logs runs it
    # A marker in the drill's own WHERE, so its run can be told apart; it matches every row.
    sql = re.sub(r"\bWHERE\s", "WHERE raw <> 'probe-show' AND ", drill.json()["sql"], count=1)
    res = ana.post("/api/query", json={"sql": sql, **WIDE})
    assert res.status_code == 200, res.text
    assert res.json()["rows"]
    assert_locked(spy, "show")


def test_mcp_run_query(lab: dict[str, Any], spy: Spy) -> None:
    settings(lab, enabled=True, local=True)
    is_error, out = tool(lab["ana"], "run_query", {"sql": probe("mcp")})
    assert not is_error, out
    assert_locked(spy, "mcp")


def test_page_sql_still_takes_a_kept_instance(lab: dict[str, Any], spy: Spy) -> None:
    """The spy is live: the app's own page SQL (`page=True`) does get a kept instance."""
    engine: QueryEngine = lab["app"].state.engine
    from app.engine.duckdb import QueryScope

    engine.run(probe("page"), QueryScope(sources=["lin_auth"]), page=True)
    (run,) = spy.of("probe-page")
    assert run.kept and not run.locked
