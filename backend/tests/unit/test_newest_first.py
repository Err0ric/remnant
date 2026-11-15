"""Logs newest day first (owner order 2026-11-14): the stepped read of a Simple search gives
exactly the whole-window answer, on lakes built to break it: ties on the sort time across
a day boundary and across folders, NULL `time` sorted by `time_observed`, a file whose
rows are on another day than its folder, a late arrival, a file without statistics, a
window whose newest days hold no match, fewer matches than the page, a hidden source, and
random lakes with a fixed seed. It stops at the newest day when the page fills there and
reads on when it must."""

import random
import uuid
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from app.core.errors import QueryTimeoutError
from app.core.schema import COLUMN_NAMES
from app.engine.duckdb import QueryEngine, QueryScope
from app.ingest.writer import rows_table
from app.search import newest
from app.search.newest import keyed_sql, newest_first
from app.search.simple import compile_search

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
MIDNIGHT = datetime(2026, 11, 14, tzinfo=UTC)


def row(source: str, at: datetime | None, observed: datetime, message: str) -> dict[str, Any]:
    r: dict[str, Any] = dict.fromkeys(COLUMN_NAMES)
    r.update(
        event_id=str(uuid.uuid4()), source_id=source, template_id="t", template_version="1",
        time=at, time_observed=observed, raw=f"line {message}", raw_bytes_invalid=False,
        parse_status="ok", classification="internal", owner_id="system", message=message,
        device_hostname="ws-01.example.internal",
    )  # fmt: skip
    return r


def put(lake: Path, source: str, day: str, rows: list[dict[str, Any]], stats: bool = True) -> Path:
    """One part file in the folder given, whatever its rows' days (the writer would file
    each row by its own day; compaction, reparse, or an old version might not)."""
    folder = lake / f"source={source}" / f"day={day}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"part-{uuid.uuid4().hex}.parquet"
    pq.write_table(rows_table(rows), path, write_statistics=stats)
    return path


def day_of(r: dict[str, Any]) -> str:
    return str((r["time"] or r["time_observed"]).date())


def file_by_day(lake: Path, rows: list[dict[str, Any]]) -> None:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault((r["source_id"], day_of(r)), []).append(r)
    for (source, day), batch in groups.items():
        put(lake, source, day, batch)


@pytest.fixture(scope="module")
def lake(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root: Path = tmp_path_factory.mktemp("newest") / "lake"
    rng = random.Random(14)
    rows = []
    for d in range(10):
        for source in ("fw", "dns", "hidden"):
            for i in range(12):
                at = NOW - timedelta(days=d, minutes=rng.randrange(0, 1440))
                msg = "failed login" if i % 3 == 0 else "accepted"
                if d == 7 and i == 1:
                    msg = "rareword seen"
                # Some rows have no event time and sort by when they were observed.
                rows.append(row(source, None if i % 5 == 0 else at, at, msg))
    # Ties on the sort time at midnight: in today's folder and, misfiled, in yesterday's.
    tied = [row(s, MIDNIGHT, MIDNIGHT, "failed tie") for s in ("fw", "dns") for _ in range(3)]
    rows += tied[:4]
    put(root, "fw", "2026-11-13", tied[4:])
    file_by_day(root, rows)
    # A late arrival: an old event time, observed now, filed by its time.
    put(root, "dns", "2026-11-06", [row("dns", NOW - timedelta(days=8), NOW, "failed late")])
    # Misfiled: a file in an old folder holding the newest failed event.
    put(root, "fw", "2026-11-06", [row("fw", NOW - timedelta(minutes=1), NOW, "failed moved")])
    # A file without statistics, newest rows inside, in an older folder.
    put(root, "dns", "2026-11-09", [row("dns", NOW - timedelta(minutes=2), NOW, "failed")],
        stats=False)  # fmt: skip
    return root


TEXTS = ["", "failed", "rareword", "nothing-matches-this", "source:dns failed", "-failed"]
LIMITS = [1, 3, 10, 40, 1000]
SCOPES = [
    QueryScope(["fw", "dns"], NOW - timedelta(days=30)),  # "hidden" is not readable
    QueryScope(["fw", "dns"], NOW - timedelta(days=1)),
    QueryScope(["fw"], NOW - timedelta(days=9), NOW - timedelta(days=2)),
    QueryScope(None, None, None),
]


def whole(engine: QueryEngine, text: str, scope: QueryScope) -> tuple[list[list[Any]], bool]:
    """The whole-window read, in one query, in the same order."""
    n = engine.default_limit
    sql, params = keyed_sql(text, n + 1)
    rows = engine.run(sql, scope, params or None).rows
    return [r[:-1] for r in rows[:n]], len(rows) > n


def check(engine: QueryEngine, text: str, scope: QueryScope) -> None:
    got = newest_first(engine, text, scope)
    want, truncated = whole(engine, text, scope)
    assert got.rows == want and got.truncated == truncated
    # And a valid answer of the search as it runs without stepping: the same columns,
    # the same count, the same sort times; only rows tied on the last time may differ.
    plain = compile_search(text)
    old = engine.run(plain.sql, scope, plain.params or None)
    assert got.columns == old.columns and got.truncated == old.truncated
    assert len(got.rows) == len(old.rows)
    assert got.executed_sql == old.executed_sql
    if got.rows:
        ids = [r[-1] for r in got.rows] + [r[-1] for r in old.rows]
        keys = dict(engine.run(
            "SELECT event_id, CAST(coalesce(time, time_observed) AS VARCHAR) FROM events"
            " WHERE list_contains($ids, event_id) LIMIT 100000", scope, {"ids": ids},
        ).rows)  # fmt: skip
        assert [keys[r[-1]] for r in got.rows] == [keys[r[-1]] for r in old.rows]
        last = keys[got.rows[-1][-1]]
        assert {tuple(r) for r in got.rows if keys[r[-1]] != last} == {
            tuple(r) for r in old.rows if keys[r[-1]] != last
        }


@pytest.mark.parametrize("limit", LIMITS)
@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("text", TEXTS)
def test_the_stepped_read_is_the_whole_window_read(
    lake: Path, text: str, scope: QueryScope, limit: int
) -> None:
    check(QueryEngine(lake, default_limit=limit), text, scope)


def test_the_lake_has_what_the_cases_need(lake: Path) -> None:
    engine = QueryEngine(lake, default_limit=1000)
    res = newest_first(engine, "failed", SCOPES[0])
    msgs = [r[5] for r in res.rows]
    assert msgs[0] == "failed moved" and "failed late" in msgs and "failed tie" in msgs
    assert sum(m == "failed tie" for m in msgs) == 6
    assert all(r[2] in ("fw", "dns") for r in res.rows)  # never the hidden source
    assert any(r[0] is None for r in res.rows)  # NULL time, sorted by observed time
    hidden = newest_first(engine, "failed", QueryScope(None, NOW - timedelta(days=30)))
    assert any(r[2] == "hidden" for r in hidden.rows)


def reads(engine: QueryEngine, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    real = engine.run

    def spy(sql: str, scope: QueryScope, *a: Any, **k: Any) -> Any:
        seen.append({"files": scope.files, "timeout_s": k.get("timeout_s")})
        return real(sql, scope, *a, **k)

    monkeypatch.setattr(engine, "run", spy)
    return seen


@pytest.fixture(scope="module")
def tidy(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Ten days, every row in its own day's folder, a match every few minutes."""
    root: Path = tmp_path_factory.mktemp("tidy") / "lake"
    rows = [
        row(s, NOW - timedelta(minutes=7 * i), NOW - timedelta(minutes=7 * i),
            "rareword" if i == 1800 else "failed" if i % 2 else "accepted")
        for s in ("fw", "dns") for i in range(2000)
    ]  # fmt: skip
    file_by_day(root, rows)
    return root


def test_a_page_that_fills_in_the_newest_day_reads_only_that_day(
    tidy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = QueryEngine(tidy, default_limit=50)
    scope = QueryScope(None, NOW - timedelta(days=30))
    seen = reads(engine, monkeypatch)
    res = newest_first(engine, "failed", scope)
    assert len(res.rows) == 50 and res.truncated
    assert len(seen) == 1
    files = seen[0]["files"]
    # The newest 24 hours: today's folder and yesterday's, whose bounds are inside them.
    assert files and all("day=2026-11-14" in f or "day=2026-11-13" in f for f in files)
    assert len(files) < len(list(tidy.glob("source=*/day=*/part-*.parquet")))


def test_a_search_with_no_match_on_the_newest_day_reads_the_rest_at_once(
    tidy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = QueryEngine(tidy, default_limit=50)
    scope = QueryScope(None, NOW - timedelta(days=30))
    seen = reads(engine, monkeypatch)
    res = newest_first(engine, "rareword", scope)
    assert [r[5] for r in res.rows] == ["rareword", "rareword"] and not res.truncated
    assert len(seen) == 2  # the newest day, then the rest: each file once
    every = [f for s in seen for f in s["files"]]
    assert sorted(every) == sorted(map(str, tidy.glob("source=*/day=*/part-*.parquet")))
    # One timeout for the whole search: each step has what is left of it.
    left = [s["timeout_s"] for s in seen]
    assert left == sorted(left, reverse=True) and left[0] <= engine.timeout_s


def test_a_page_that_fills_later_reads_only_files_that_can_still_matter(
    tidy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = QueryEngine(tidy, default_limit=400)  # more than a day of matches
    seen = reads(engine, monkeypatch)
    check(engine, "failed", QueryScope(None, NOW - timedelta(days=30)))
    stepped = seen[: len(seen) - 3]  # check() then runs three whole-window reads
    assert 2 <= len(stepped) <= 3
    read = {f for s in stepped for f in s["files"]}
    assert not any("day=2026-11-05" in f for f in read)  # the oldest days are not read


def test_the_whole_search_shares_one_timeout(tidy: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = QueryEngine(tidy, default_limit=50)
    ticks = iter(range(0, 10_000, 20))
    monkeypatch.setattr(newest.time, "monotonic", lambda: float(next(ticks)))
    with pytest.raises(QueryTimeoutError):
        newest_first(engine, "rareword", QueryScope(None, NOW - timedelta(days=30)))


def test_a_listed_file_that_is_gone_falls_back_to_the_whole_window(
    tidy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = QueryEngine(tidy, default_limit=50)
    scope = QueryScope(None, NOW - timedelta(days=30))
    real = engine.newest_files
    gone = str(tidy / "source=fw" / "day=2026-11-14" / "part-gone.parquet")
    monkeypatch.setattr(engine, "newest_files", lambda *a: [*real(*a), (gone, NOW)])
    seen = reads(engine, monkeypatch)
    res = newest_first(engine, "failed", scope)
    plain = compile_search("failed")
    # The step failed, then the whole window ran as before (its own order of ties).
    assert len(seen) == 2 and seen[0]["files"] is not None and seen[1]["files"] is None
    old = engine.run(plain.sql, scope, plain.params)
    assert [r[0] for r in res.rows] == [r[0] for r in old.rows]
    assert res.columns == old.columns and res.truncated == old.truncated


def test_listed_files_never_widen_the_scope(tidy: Path) -> None:
    engine = QueryEngine(tidy)
    every = frozenset(map(str, tidy.glob("source=*/day=*/part-*.parquet")))
    scope = QueryScope(["fw"], NOW - timedelta(days=1), files=every)
    res = engine.run("SELECT source_id, min(time) FROM events GROUP BY 1", scope)
    assert [r[0] for r in res.rows] == ["fw"]
    assert datetime.fromisoformat(res.rows[0][1]) >= NOW - timedelta(days=1)


@pytest.mark.parametrize("seed", range(6))
def test_random_lakes(tmp_path: Path, seed: int) -> None:
    rng = random.Random(seed)
    words = ["failed", "accepted", "denied", "rareword"]
    rows = []
    for _ in range(rng.randrange(20, 160)):
        # Times on whole hours, so many rows tie on the sort time.
        at = NOW - timedelta(hours=rng.randrange(0, 24 * 12))
        source = rng.choice(["fw", "dns", "hidden"])
        msg = rng.choices(words, weights=[5, 5, 2, 1])[0]
        rows.append(row(source, None if rng.random() < 0.2 else at, at, msg))
    lake = tmp_path / "lake"
    for r in rows:
        day = day_of(r)
        if rng.random() < 0.1:  # misfiled
            day = str((NOW - timedelta(days=rng.randrange(0, 12))).date())
        put(lake, r["source_id"], day, [r], stats=rng.random() > 0.05)
    for _ in range(12):
        engine = QueryEngine(lake, default_limit=rng.choice([1, 2, 5, 20, 200]))
        start = rng.choice([None, NOW - timedelta(days=rng.randrange(1, 13))])
        scope = QueryScope(rng.choice([None, ["fw", "dns"], ["dns"]]), start)
        check(engine, rng.choice(["", *words, "-failed", "failed OR denied"]), scope)


@pytest.fixture(autouse=True)
def _now(pin_now: Any) -> None:
    pin_now(NOW)


@pytest.fixture(scope="module")
def years(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The review's case: 20 matches on the newest day, two files without a match 1,100 and
    1,200 days back; plus years of other days and one event dated far in the future."""
    root: Path = tmp_path_factory.mktemp("years") / "lake"
    rows = [row("fw", NOW - timedelta(minutes=30 * i), NOW, "failed") for i in range(20)]
    file_by_day(root, rows)
    for days in (1100, 1200):
        old = NOW - timedelta(days=days)
        put(root, "fw", str(old.date()), [row("fw", old, old, "accepted")])
    return root


def test_few_matches_and_files_years_old_read_to_the_end_without_a_date_error(
    years: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = QueryEngine(years)  # the real page size, 10,000 rows
    seen = reads(engine, monkeypatch)
    for scope in (QueryScope(None, None), QueryScope(None, None, NOW + timedelta(days=1))):
        seen.clear()
        res = newest_first(engine, "failed", scope)
        # No fallback: every read is a step over listed files, at most three of them.
        assert 2 <= len(seen) <= 3 and all(s["files"] is not None for s in seen)
        assert [r[:-1] for r in res.rows] == [r[:-1] for r in whole(engine, "failed", scope)[0]]
        check(engine, "", scope)


def test_a_future_dated_event_and_years_of_days(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    rows = [row("dns", NOW - timedelta(days=d), NOW - timedelta(days=d), "failed")
            for d in range(0, 3000, 37)]  # fmt: skip
    rows.append(row("dns", datetime(2099, 1, 1, tzinfo=UTC), NOW, "failed future"))
    file_by_day(lake, rows)
    for limit in (1, 5, 10_000):
        engine = QueryEngine(lake, default_limit=limit)
        for scope in (QueryScope(None, None), QueryScope(["dns"], NOW - timedelta(days=900))):
            for text in ("failed", "", "future", "no-such-word"):
                check(engine, text, scope)
    first = newest_first(QueryEngine(lake), "failed", QueryScope(None, None)).rows[0]
    assert first[5] == "failed future"


@pytest.mark.parametrize(
    "scope",
    [
        QueryScope(["fw", "dns"], datetime(2026, 11, 10, 6, 0)),  # naive start: UTC
        QueryScope(["fw", "dns"], None, datetime(2026, 11, 12, 18, 0)),  # naive end
        QueryScope(None, datetime(2026, 11, 8), datetime(2026, 11, 13, 23, 59)),  # both
        QueryScope(None, datetime(2026, 11, 10, 6, 0, tzinfo=timezone(timedelta(hours=5)))),
    ],
)
def test_naive_and_offset_bounds_read_as_the_plain_path_reads_them(
    lake: Path, scope: QueryScope
) -> None:
    for limit in (3, 1000):
        for text in ("failed", ""):
            check(QueryEngine(lake, default_limit=limit), text, scope)


def test_old_events_ingested_today_do_not_count_as_new(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lake = tmp_path / "lake"
    rows = [row("fw", NOW - timedelta(minutes=5 * i), NOW, "failed") for i in range(100)]
    # A history import: events 5 to 25 days old, all observed now.
    rows += [row("fw", NOW - timedelta(days=d, hours=1), NOW, "failed old")
             for d in range(5, 26) for _ in range(10)]  # fmt: skip
    file_by_day(lake, rows)
    engine = QueryEngine(lake, default_limit=50)
    seen = reads(engine, monkeypatch)
    scope = QueryScope(None, NOW - timedelta(days=30))
    res = newest_first(engine, "failed", scope)
    assert len(seen) == 1 and all("day=2026-11-14" in f for f in seen[0]["files"])
    assert res.rows == whole(engine, "failed", scope)[0]


def test_a_fault_in_the_stepping_falls_back_to_the_whole_window(
    tidy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = QueryEngine(tidy, default_limit=50)
    scope = QueryScope(None, NOW - timedelta(days=30))

    def broken(*a: Any) -> Any:
        raise OverflowError("date value out of range")

    monkeypatch.setattr(engine, "newest_files", broken)
    res = newest_first(engine, "failed", scope)
    plain = compile_search("failed")
    old = engine.run(plain.sql, scope, plain.params)
    assert [r[0] for r in res.rows] == [r[0] for r in old.rows] and res.truncated
