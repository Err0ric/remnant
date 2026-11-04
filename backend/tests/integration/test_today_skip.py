"""D178: the today-so-far build carries a source over when its files have not changed
since the last build (owner, 2026-11-03: accuracy over speed). The totals must be the
same with and without the skip, and a source whose unchanged files hold rows observed
after the last cutoff is built again, never carried."""

from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq
import pytest
import structlog

from app.ai.rollup import TODAY_EVERY_S, TODAY_MARGIN_S, AiRollup
from app.engine.duckdb import TODAY_DIR, QueryScope
from tests.integration.test_schedules import make_lab
from tests.scale_lake import write_dns, write_identity

NOON = datetime.combine(datetime.now(UTC).date(), time(12), UTC)  # far from midnight


def _services(usage: Any, scope: QueryScope) -> dict[str, tuple[int, tuple[str, ...]]]:
    found, _ = usage.all_services(scope)
    return {u.service.id: (u.events, tuple(sorted(u.top_people))) for u in found}


def _lab(tmp_path: Path, upto: datetime) -> dict[str, Any]:
    """A lake with today's DNS and identity files holding rows observed up to `upto`."""
    lab = make_lab(tmp_path)
    lake = lab["app"].state.engine._lake
    write_dns(lake, per_day=3_000, days=2, end=NOON)
    write_identity(lake, days=2, end=NOON, hosts=50)
    con = duckdb.connect()
    for f in lake.glob(f"source=*/day={NOON.date().isoformat()}/*.parquet"):
        tmp = f.with_suffix(".tmp")
        con.execute(
            f"COPY (SELECT * FROM read_parquet('{f}') WHERE time_observed <= TIMESTAMPTZ"
            f" '{upto.isoformat()}') TO '{tmp}' (FORMAT parquet)"
        )
        tmp.replace(f)
    return lab


def _build(rollup: AiRollup, at: datetime) -> dict[str, Any]:
    rollup._clock = lambda: at
    with structlog.testing.capture_logs() as logs:
        assert rollup.refresh_today() > 0
    (ev,) = [e for e in logs if e["event"] == "ai_rollup.today"]
    return ev


def _parts(rollup: AiRollup, stamp: str) -> dict[str, list[dict[str, Any]]]:
    out = {}
    for f in sorted((rollup.folder / TODAY_DIR).glob(f"source=*/*-{stamp}.parquet")):
        rows = pq.read_table(f).to_pylist()
        out[f"{f.parent.name}/{f.name}"] = sorted(rows, key=repr)
    return out


def test_unchanged_sources_are_carried_with_identical_totals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    t0 = NOON - timedelta(minutes=10)  # newest row in today's files
    lab = _lab(tmp_path, t0)
    usage, rollup = lab["app"].state.ai_usage, lab["app"].state.ai_rollup
    first = t0 + timedelta(seconds=TODAY_MARGIN_S + 1)  # cutoff just after every row
    second = first + timedelta(seconds=TODAY_EVERY_S + 1)
    scope = QueryScope(None, NOON - timedelta(hours=20), second)
    rollup._clock = lambda: second
    live = _services(usage, scope)  # no build yet: all from events
    assert live and any(p for _, p in live.values())

    ev = _build(rollup, first)
    assert ev["reused"] == 0
    ev = _build(rollup, second)
    assert ev["reused"] == ev["sources"] > 0  # nothing changed: every source carried
    stamp = rollup.today_mark()["stamp"]
    carried = _parts(rollup, stamp)
    assert _services(usage, scope) == live

    # The same build without the skip writes the same rows, label included.
    monkeypatch.setattr(AiRollup, "_reuse", lambda *a, **k: False)
    mark = rollup.folder / TODAY_DIR / "_today.json"
    body = mark.read_text().replace(rollup.today_mark()["built_at"], first.isoformat())
    mark.write_text(body)  # let the same clock build again
    ev = _build(rollup, second)
    assert ev["reused"] == 0 and rollup.today_mark()["stamp"] == stamp
    assert _parts(rollup, stamp) == carried
    assert _services(usage, scope) == live


def test_rows_after_the_last_cutoff_are_built_not_carried(tmp_path: Path) -> None:
    """Files unchanged since the last build, but holding rows the last build left to be
    read live (observed after its cutoff): carrying it over would drop them."""
    lab = _lab(tmp_path, NOON)
    usage, rollup = lab["app"].state.ai_usage, lab["app"].state.ai_rollup
    first = NOON - timedelta(minutes=30)  # cutoff before the last half hour of rows
    second = NOON + timedelta(seconds=TODAY_MARGIN_S + 1)
    scope = QueryScope(None, NOON - timedelta(hours=20), second)
    rollup._clock = lambda: second
    live = _services(usage, scope)

    _build(rollup, first)
    ev = _build(rollup, second)
    assert ev["reused"] == 0
    assert _services(usage, scope) == live


def test_a_changed_file_is_built_again(tmp_path: Path) -> None:
    t0 = NOON - timedelta(minutes=10)
    lab = _lab(tmp_path, t0)
    usage, rollup = lab["app"].state.ai_usage, lab["app"].state.ai_rollup
    first = t0 + timedelta(seconds=TODAY_MARGIN_S + 1)
    second = first + timedelta(seconds=TODAY_EVERY_S + 1)
    _build(rollup, first)
    # A late file lands in one source's day: that source is built, the others carried.
    lake = lab["app"].state.engine._lake
    day = NOON.date().isoformat()
    src = sorted(lake.glob(f"source=*/day={day}"))[0]
    f = sorted(src.glob("part-*.parquet"))[0]
    con = duckdb.connect()
    con.execute(
        f"COPY (SELECT * FROM read_parquet('{f}') LIMIT 5) TO '{src / 'part-late.parquet'}'"
        " (FORMAT parquet)"
    )
    scope = QueryScope(None, NOON - timedelta(hours=20), second)
    rollup._clock = lambda: second
    ev = _build(rollup, second)
    assert ev["reused"] == ev["sources"] - 1
    built = _services(usage, scope)
    # Against a build from nothing at the same clock.
    for p in (rollup.folder / TODAY_DIR).glob("*"):
        if p.is_file():
            p.unlink()
    assert rollup.refresh_today() > 0 and rollup.today_mark()["inputs"]
    assert _services(usage, scope) == built
