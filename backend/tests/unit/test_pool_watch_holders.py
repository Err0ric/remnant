"""pool.wait names the jobs holding the pool when a wait crosses 2 s (owner, 2026-11-03;
D198), even when they have all finished by the time a thread starts the waiting job."""

import time

from structlog.testing import capture_logs

from app.core import pool_watch


def test_holders_are_taken_when_the_wait_crosses_the_threshold() -> None:
    handed = time.monotonic() - (pool_watch.WAIT_WARN_S + 1)
    run = pool_watch._watched(lambda: "done", handed, 10_001)
    with pool_watch._lock:
        pool_watch._running[10_002] = ("pages.busy_page", handed)
    pool_watch.check(time.monotonic())
    with pool_watch._lock:  # the holder finishes before the waiting job starts
        pool_watch._running.pop(10_002)
    with capture_logs() as logs:
        assert run() == "done"
    [line] = [x for x in logs if x["event"] == "pool.wait"]
    assert line["job"].endswith("<lambda>") and line["waited_s"] > pool_watch.WAIT_WARN_S
    assert [name for name, _ in line["holders"]] == ["pages.busy_page"]
    assert line["holders"][0][1] >= pool_watch.WAIT_WARN_S
    assert 10_001 not in pool_watch._waiting and 10_001 not in pool_watch._running


def test_a_short_wait_takes_no_snapshot_and_logs_nothing() -> None:
    run = pool_watch._watched(lambda: 1, time.monotonic(), 10_003)
    pool_watch.check(time.monotonic())
    assert pool_watch._waiting[10_003][1] is None
    with capture_logs() as logs:
        run()
    assert not [x for x in logs if x["event"] == "pool.wait"]
