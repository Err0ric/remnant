"""Clean shutdown (owner, 2026-11-10): running queries are stopped and their threads have
closed their DuckDB connections before the interpreter exits. A thread still inside
`DuckDBPyConnection.close()` during interpreter finalization makes the C++ runtime abort
the process (exit 134), seen after an out-of-memory query whose sibling queries ran on."""

import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import duckdb
import pytest

from app.core.errors import QueryBusyError
from app.engine.duckdb import QueryEngine, QueryScope


def test_shutdown_stops_a_running_query_and_waits_for_its_thread(tmp_path: Path) -> None:
    engine = QueryEngine(tmp_path / "lake")
    con = duckdb.connect()
    outcome: list[str] = []

    def work() -> None:
        engine._track(con)
        try:
            con.execute("SELECT count(*) FROM range(100000000000) a").fetchall()
            outcome.append("finished")
        except duckdb.InterruptException:
            outcome.append("interrupted")
        finally:
            con.close()
            engine._untrack(con)

    t = threading.Thread(target=work, daemon=True)
    t.start()
    while not engine._running:
        time.sleep(0.01)
    started = time.monotonic()
    assert engine.shutdown(wait_s=10.0) == 0
    assert time.monotonic() - started < 10.0  # within wait_s; outcome is the check
    t.join(timeout=5.0)
    assert outcome == ["interrupted"]
    assert not engine._running


def test_no_query_starts_after_shutdown(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    lake.mkdir()
    engine = QueryEngine(lake)
    engine.shutdown(wait_s=0.1)
    con = duckdb.connect()
    assert engine._track(con) is False
    assert not engine._running
    con.close()
    with pytest.raises(QueryBusyError, match="shutting down"):
        engine.run("SELECT 1", QueryScope([], None, None))


CHILD = textwrap.dedent(
    """
    import sys
    from datetime import UTC, datetime, timedelta
    from pathlib import Path
    from tests.integration.test_ai_scale import _app
    from tests.scale_lake import write_dns

    tmp = Path(sys.argv[1])
    write_dns(tmp / "lake", per_day=50_000, days=2, end=datetime.now(UTC))
    c = _app(tmp, tmp / "lake", memory_mb=16, spill=True)
    start = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    res = c.get("/api/ai/usage", params={"start": start})
    print("DONE", res.status_code, flush=True)
    """
)


@pytest.mark.slow
@pytest.mark.skipif(sys.platform != "linux", reason="the loop is for the server platform")
def test_fifty_out_of_memory_runs_never_abort_at_exit(tmp_path: Path) -> None:
    """Each run answers 503 for an out-of-memory query with sibling queries still running,
    then exits. Before the clean shutdown about 1 run in 10 aborted at exit (exit 134 after
    DONE). A crash before DONE is DuckDB's own mid-query segfault (upstream), not this."""
    backend = Path(__file__).resolve().parents[2]
    exit_crashes, mid_query = [], 0
    for i in range(50):
        run = tmp_path / f"r{i}"
        run.mkdir()
        p = subprocess.run(  # fixed command: this interpreter and a test script
            [sys.executable, "-c", CHILD, str(run)],
            cwd=backend, capture_output=True, text=True, timeout=120, check=False,
        )  # fmt: skip
        if "DONE" not in p.stdout:
            mid_query += 1
            continue
        if p.returncode != 0:
            exit_crashes.append((i, p.returncode, p.stdout.strip()))
    assert exit_crashes == [], exit_crashes
    assert mid_query < 25, f"{mid_query} of 50 runs crashed mid-query"


def test_an_interrupt_sent_before_the_query_starts_is_not_lost(tmp_path: Path) -> None:
    """CI on #500: shutdown came between `_track` and `execute`; DuckDB clears the interrupt
    flag when a query starts, so one interrupt was lost and the query ran on. Shutdown now
    interrupts again until the query has stopped."""
    engine = QueryEngine(tmp_path / "lake")
    con = duckdb.connect()
    tracked, go = threading.Event(), threading.Event()
    outcome: list[str] = []

    def work() -> None:
        engine._track(con)
        tracked.set()
        go.wait(5)  # hold here until shutdown has sent its first interrupt
        try:
            con.execute("SELECT count(*) FROM range(100000000000) a").fetchall()
            outcome.append("finished")
        except duckdb.InterruptException:
            outcome.append("interrupted")
        finally:
            con.close()
            engine._untrack(con)

    t = threading.Thread(target=work, daemon=True)
    t.start()
    tracked.wait(5)
    threading.Timer(0.3, go.set).start()  # the query starts after the first interrupt
    assert engine.shutdown(wait_s=10.0) == 0
    t.join(timeout=5.0)
    assert outcome == ["interrupted"]
