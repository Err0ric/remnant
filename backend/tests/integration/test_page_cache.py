"""D133: Dashboard sections load one part at a time and are kept 60 s per caller's sources
and window; a cached answer is still audited, and is never served to another scope."""

from pathlib import Path

from app.api.cache import PageCache
from tests.integration.test_dashboards import audit
from tests.integration.test_schedules import make_lab


def test_cache_expires_and_keeps_scopes_apart() -> None:
    c = PageCache(ttl_s=0.05)
    c.put(("x", ("a",)), 1)
    assert c.get(("x", ("a",))) == 1
    assert c.get(("x", ("b",))) is None
    import time

    time.sleep(0.06)
    assert c.get(("x", ("a",))) is None


def test_sections_by_part_cached_and_audited(tmp_path: Path) -> None:
    lab = make_lab(tmp_path)
    ana = lab["ana"]
    first = ana.get("/api/dashboard/sections", params={"window": "7d", "part": "attacks"})
    assert first.status_code == 200
    body = first.json()
    assert body["identity"] is None and body["detections"] is None
    again = ana.get("/api/dashboard/sections", params={"window": "7d", "part": "attacks"})
    assert again.json() == body
    rows = audit(lab, "dashboard.sections")
    assert [r.get("cached", False) for r in rows[-2:]] == [False, True]
    # The administrator reads more sources: a separate answer, not ana's.
    admin = lab["admin"].get("/api/dashboard/sections", params={"window": "7d", "part": "attacks"})
    assert audit(lab, "dashboard.sections")[-1].get("cached", False) is False
    assert admin.status_code == 200
