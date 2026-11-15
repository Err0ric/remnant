"""A time without a zone means UTC everywhere (owner order 2026-11-14): in the scope filter,
in the day folders read, in the stepped Logs read, in the rollup day choice, and at every
API time parameter. Checked with the process time zone far from UTC both ways, around a
UTC midnight, so a naive time read as local time would skip or add a day."""

import importlib
import pkgutil
import time
import typing
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute
from pydantic import BaseModel, TypeAdapter

import app.api as api_pkg
from app.core.schema import COLUMN_NAMES
from app.core.times import UtcDateTime
from app.engine.duckdb import QueryEngine, QueryScope
from app.ingest.writer import LakeWriter
from app.search.newest import newest_first

MIDNIGHT = datetime(2026, 11, 14, tzinfo=UTC)
ZONES = ["America/Los_Angeles", "Asia/Kolkata"]


@pytest.fixture(params=ZONES)
def zone(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv("TZ", request.param)
    time.tzset()
    yield request.param
    monkeypatch.undo()
    time.tzset()


def row(at: datetime) -> dict[str, Any]:
    r: dict[str, Any] = dict.fromkeys(COLUMN_NAMES)
    r.update(
        event_id=str(uuid.uuid4()), source_id="fw", template_id="t", template_version="1",
        time=at, time_observed=at, raw=f"failed at {at:%H:%M}", raw_bytes_invalid=False,
        parse_status="ok", classification="internal", owner_id="system", message="failed",
    )  # fmt: skip
    return r


@pytest.fixture(scope="module")
def lake(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root: Path = tmp_path_factory.mktemp("naive") / "lake"
    # Either side of the UTC midnight, and a day further each way.
    offsets = [-26 * 60, -45, -15, 15, 45, 26 * 60]
    LakeWriter(root).write([row(MIDNIGHT + timedelta(minutes=m)) for m in offsets])
    return root


def naive(t: datetime) -> datetime:
    return t.replace(tzinfo=None)


WINDOWS = [
    (MIDNIGHT - timedelta(minutes=30), None),  # start 23:30
    (None, MIDNIGHT + timedelta(minutes=30)),  # end 00:30
    (MIDNIGHT - timedelta(minutes=30), MIDNIGHT + timedelta(minutes=30)),
    (MIDNIGHT + timedelta(minutes=30), MIDNIGHT + timedelta(hours=27)),
    (MIDNIGHT - timedelta(hours=27), MIDNIGHT - timedelta(minutes=30)),
]


def bare(start: datetime | None, end: datetime | None) -> QueryScope:
    return QueryScope(None, start and naive(start), end and naive(end))


@pytest.mark.parametrize(("start", "end"), WINDOWS)
def test_a_naive_window_reads_what_the_same_window_in_utc_reads(
    lake: Path, zone: str, start: datetime | None, end: datetime | None
) -> None:
    engine = QueryEngine(lake)
    sql = "SELECT time FROM events ORDER BY time"
    want = engine.run(sql, QueryScope(None, start, end)).rows
    assert engine.run(sql, bare(start, end)).rows == want
    # No day folder skipped, none read that should not be.
    dirs = engine._source_dirs(QueryScope(None))
    utc_files = engine._lake_globs(dirs, QueryScope(None, start, end), frozenset())
    assert engine._lake_globs(dirs, bare(start, end), frozenset()) == utc_files
    got = newest_first(engine, "failed", bare(start, end))
    assert got.rows == newest_first(engine, "failed", QueryScope(None, start, end)).rows
    assert len(got.rows) == len(want)


def test_a_scope_keeps_a_time_with_a_zone_as_that_instant() -> None:
    from datetime import timezone

    t = datetime(2026, 11, 14, 5, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    s = QueryScope(None, t, naive(MIDNIGHT))
    assert s.start == t and s.start.utcoffset() == timedelta(0)
    assert s.end == MIDNIGHT


def test_the_rollup_day_choice_reads_a_naive_start_as_utc(zone: str) -> None:
    from app.search.m365_rollup import _start_day

    s = bare(MIDNIGHT - timedelta(minutes=30), MIDNIGHT + timedelta(hours=5))
    assert _start_day(s.start) == "2026-11-13"


def test_the_api_time_type_reads_a_naive_time_as_utc(zone: str) -> None:
    read = TypeAdapter(UtcDateTime).validate_python
    assert read("2026-11-13T23:30:00") == datetime(2026, 11, 13, 23, 30, tzinfo=UTC)
    with_zone = read("2026-11-13T23:30:00-08:00")
    assert with_zone.utcoffset() == timedelta(hours=-8)  # a zone given is kept as given


def test_the_cli_sends_times_with_a_zone() -> None:
    from app.cli.main import _since

    since = _since("1h")
    assert since is not None and since.utcoffset() == timedelta(0)


# --- every request time is the shared type (so the next endpoint cannot regress) ----------

# Response-only or internal fields that are not times a request sends: none today.
NOT_REQUEST_TIMES: set[str] = set()


def _times(t: Any, path: str, seen: frozenset[type]) -> Iterator[tuple[str, bool]]:
    """(field path, is the shared type) for every datetime in a request annotation."""
    if t is datetime:
        yield path, False
        return
    if typing.get_origin(t) is typing.Annotated:
        base, *meta = typing.get_args(t)
        if base is datetime:
            yield path, any(m in typing.get_args(UtcDateTime)[1:] for m in meta)
            return
    if isinstance(t, type) and issubclass(t, BaseModel):
        if t in seen:
            return
        for name, f in t.model_fields.items():
            ann = f.annotation
            if f.metadata:
                ann = typing.Annotated[ann, *f.metadata]  # type: ignore[valid-type]  # rebuild
            yield from _times(ann, f"{path}.{name}", seen | {t})
        return
    for a in typing.get_args(t):
        yield from _times(a, path, seen)


def _routes() -> Iterator[tuple[str, APIRoute]]:
    for m in pkgutil.iter_modules(api_pkg.__path__):
        router = getattr(importlib.import_module(f"app.api.{m.name}"), "router", None)
        for route in getattr(router, "routes", []):
            if isinstance(route, APIRoute):
                yield m.name, route


def test_every_request_time_is_read_as_utc() -> None:
    found, wrong = [], []

    def walk(d: Any) -> Iterator[Any]:
        yield d
        for s in d.dependencies:
            yield from walk(s)

    for module, route in _routes():
        for d in walk(route.dependant):
            for p in d.query_params + d.body_params + d.path_params:
                ann = p.field_info.annotation
                if p.field_info.metadata:
                    ann = typing.Annotated[ann, *p.field_info.metadata]  # type: ignore[valid-type]
                for path, ok in _times(ann, p.name, frozenset()):
                    key = f"{module} {route.path} {path}"
                    found.append(key)
                    if not ok and key not in NOT_REQUEST_TIMES:
                        wrong.append(key)
    assert len(found) > 30  # the walk sees the time parameters
    assert wrong == [], "use app.core.times.UtcDateTime for request times"
