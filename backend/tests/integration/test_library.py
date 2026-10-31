"""ADR-0033 row 8: every shipped library query is valid, passes the guard, and runs on the
template fixtures for its `requires` with no error; `expect` states the answer there. A
template change that breaks a library query fails here."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.core.config import load_config
from app.engine.duckdb import QueryScope
from app.ingest.records import DecodedLine
from app.ingest.writer import LakeWriter
from app.main import create_app
from app.search.library import LIBRARY_DIR, Pack, load, load_dir
from app.search.params import bind, compile_sql
from app.templates.loader import parse_template
from app.templates.runtime import TemplateNormalizer

ROOT = Path(__file__).resolve().parents[3]
FIX = Path(__file__).parent.parent / "fixtures" / "logs"
STARTER = ROOT / "templates" / "starter"
PACKS = [load(p) for p in sorted(LIBRARY_DIR.glob("*/pack.yaml"))]
START, END = datetime(2000, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC)
CASES = [pytest.param(p, q.id, id=f"{p.id}/{q.id}") for p in PACKS for q in p.queries]


def test_the_first_packs_ship_and_all_load() -> None:
    assert {p.id for p in PACKS} >= {"m365", "linux_auth", "paloalto", "dns_ai"}
    assert len(load_dir(LIBRARY_DIR)) == len(PACKS)  # none rejected
    for p in PACKS:
        for q in p.queries:
            for t in q.requires:
                assert (STARTER / f"{t}.yaml").is_file(), f"{p.id}/{q.id} requires {t}"


@pytest.fixture(scope="module")
def engine(tmp_path_factory: pytest.TempPathFactory) -> Any:
    tmp = tmp_path_factory.mktemp("library")
    config = load_config(Path("missing.yaml"), {"APP__PATHS__DATA_DIR": str(tmp / "data")})
    app = create_app(config)
    wanted = sorted({t for p in PACKS for q in p.queries for t in q.requires})
    rows = []
    for t in wanted:
        sample = FIX / t / "sample.log"
        if not sample.is_file():
            continue
        norm = TemplateNormalizer(parse_template((STARTER / f"{t}.yaml").read_text()), t)
        for text in sample.read_text().splitlines():
            rows.append(
                norm.normalize(DecodedLine(text=text, bytes_invalid=False, truncated=False))
            )
    LakeWriter(app.state.engine._lake).write(rows)
    return app.state.engine


@pytest.mark.parametrize(("pack", "query_id"), CASES)
def test_library_query_runs_on_fixtures(engine: Any, pack: Pack, query_id: str) -> None:
    q = next(x for x in pack.queries if x.id == query_id)
    values = bind(q.params, {}, START, END, q.sql)
    res = engine.run(compile_sql(q.sql), QueryScope(None, START, END), values)
    e = q.expect
    if e is None:
        return
    if e.rows is not None:
        assert len(res.rows) == e.rows, f"{len(res.rows)} rows"
    if e.rows_at_least is not None:
        assert len(res.rows) >= e.rows_at_least, f"{len(res.rows)} rows"
    if e.first_row:
        first = dict(zip(res.columns, res.rows[0], strict=True))
        for k, v in e.first_row.items():
            assert first.get(k) == v, f"{k}: {first.get(k)!r}"


def test_library_api_offers_what_your_sources_have_and_copies(tmp_path: Path) -> None:
    from tests.integration.test_schedules import make_lab

    lab = make_lab(tmp_path)
    ana, aud = lab["ana"], lab["aud"]  # both read only the Linux group (lin_auth)
    got = ana.get("/api/library").json()
    ids = {q["id"] for p in got["packs"] for q in p["queries"]}
    assert {"ssh_logins", "ssh_failures_by_source", "parser_mix"} <= ids
    assert "m365_failed_signins_by_user" not in ids and got["hidden"] > 0
    ssh = next(q for p in got["packs"] for q in p["queries"] if q["id"] == "ssh_logins")
    assert ssh["why"] and ssh["normal"] and "{{start}}" in ssh["sql"] and ssh["my_copy"] is None

    assert aud.post("/api/library/linux_auth/ssh_logins/copy").status_code == 403
    first = ana.post("/api/library/linux_auth/ssh_logins/copy")
    assert first.status_code == 201, first.text
    assert first.json()["origin"] == {"library": "linux_auth/ssh_logins@1.0.0"}
    assert first.json()["visibility"] == "private"
    # Someone else's copy took the id: the next one gets a suffix.
    second = lab["admin"].post("/api/library/linux_auth/ssh_logins/copy", headers=lab["h"])
    assert second.json()["id"] == "ssh_logins_2"

    # A new pack version changes the SQL: the copy shows as updated, and Replace takes it.
    lib = lab["app"].state.library
    pack, q = lib.find("linux_auth", "ssh_logins")
    lib.packs[lib.packs.index(pack)] = pack.model_copy(
        update={
            "version": "1.1.0",
            "queries": [
                x.model_copy(update={"sql": x.sql + "\nLIMIT 100"}) if x.id == q.id else x
                for x in pack.queries
            ],
        }
    )
    mine = next(
        q for p in ana.get("/api/library").json()["packs"] for q in p["queries"]
        if q["id"] == "ssh_logins"
    )["my_copy"]  # fmt: skip
    assert mine["updated"] is True and mine["version"] == "1.0.0"
    res = ana.post("/api/library/linux_auth/ssh_logins/replace")
    assert res.status_code == 200 and res.json()["sql"].endswith("LIMIT 100")
    assert res.json()["origin"] == {"library": "linux_auth/ssh_logins@1.1.0"}


def test_add_a_pack_makes_searches_schedules_and_panels(tmp_path: Path) -> None:
    from app.search.library import threshold
    from tests.integration.test_schedules import make_lab

    assert threshold("above 0") == ("above", 0.0)
    assert threshold("change 200%") == ("change_pct", 200.0)
    assert threshold(None) == (None, None)
    lab = make_lab(tmp_path)
    ana = lab["ana"]
    ids = ["ssh_logins", "ssh_failures_by_source"]
    res = ana.post("/api/library/linux_auth/dashboard", json={"query_ids": ids})
    assert res.status_code == 201, res.text
    added = res.json()["added"]
    assert [a["query_id"] for a in added] == ids
    scheds = {s["schedule_id"]: s for s in ana.get("/api/schedules").json()}
    fail = scheds[added[1]["schedule_id"]]
    assert fail["threshold_kind"] == "change_pct" and fail["threshold_value"] == 200
    assert fail["shared"] is False
    board = next(
        d for d in ana.get("/api/dashboards").json()
        if d["dashboard_id"] == res.json()["dashboard_id"]
    )  # fmt: skip
    sections = {p["schedule_id"]: p["section"] for p in board["panels"]}
    assert sections[added[0]["schedule_id"]] == "Linux / SSH"
    # A second add reuses the user's copy instead of making another saved search.
    again = ana.post("/api/library/linux_auth/dashboard", json={"query_ids": ["ssh_logins"]})
    assert again.json()["added"][0]["search_id"] == added[0]["search_id"]
    bad = ana.post("/api/library/linux_auth/dashboard", json={"query_ids": ["nope"]})
    assert bad.status_code == 400
    assert (
        lab["aud"].post("/api/library/linux_auth/dashboard", json={"query_ids": ids}).status_code
        == 403
    )
