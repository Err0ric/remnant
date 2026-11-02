"""Health > Speed (owner's batch, item 5): p50 and p95 per route over 24 hours."""

from app.core.speed import WINDOW_S, SpeedLog


def test_percentiles_cache_hits_and_the_24_hour_window() -> None:
    now = [1000.0]
    log = SpeedLog()
    log._now = lambda: now[0]  # type: ignore[method-assign]  # a settable clock
    for ms in range(1, 101):  # 1 to 100 ms
        log.record("GET /api/m365/overview", float(ms), ms / 2, 0.0, "hit" if ms % 4 else "miss")
    log.record("GET /api/query", 900.0, 800.0, 50.0, None)
    (slow, page) = log.stats()
    assert slow.route == "GET /api/query" and slow.requests == 1 and slow.cached == 0
    assert (page.requests, page.p50_ms, page.p95_ms, page.max_ms) == (100, 50.0, 95.0, 100.0)
    assert (page.cache_hits, page.cached) == (75, 100)
    now[0] += WINDOW_S + 1
    assert log.stats() == []
