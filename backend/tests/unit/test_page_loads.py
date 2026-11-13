"""The page-load map's limits (handoff item 3): rows are written at once, a flood of ids
falls back to one row per request, and the headers are parsed strictly."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, get_args

import pytest

from app.meta import page_loads
from app.meta.page_loads import Declared, PageLoadAudit, declared
from app.search.dashboard import PARTS, Window


class FakeAudit:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str | None, dict[str, Any]]] = []

    def write(self, action: str, outcome: str, user_id: str | None, ip: Any, detail: Any) -> None:
        self.rows.append((action, user_id, detail))


def _loads() -> tuple[PageLoadAudit, FakeAudit, list[float]]:
    audit, now = FakeAudit(), [0.0]
    return PageLoadAudit(audit, now=lambda: now[0]), audit, now  # type: ignore[arg-type]  # duck-typed AuditLog


Pin = Callable[[datetime | None], None]
VISIT = Declared("visit-0001", frozenset({"identity", "overview"}), "7d")


def _one(loads: PageLoadAudit, visit: Declared, user: str = "u1", part: str = "identity") -> None:
    loads.record(visit, user, None, [part], "7d", ["s1"], ("dashboard.sections", {"part": part}))


def test_the_known_parts_and_windows_match_the_dashboard() -> None:
    assert page_loads.KNOWN_PARTS == {*PARTS, "overview", "ai_watch"}
    assert page_loads.WINDOWS == set(get_args(Window))


def test_every_row_is_written_by_the_call_itself() -> None:
    loads, audit, now = _loads()
    _one(loads, VISIT)
    assert [a for a, _, _ in audit.rows] == ["dashboard.view"]
    now[0] += page_loads.WINDOW_S - 1
    _one(loads, VISIT)
    loads.record(VISIT, "u1", None, ["overview"], None, ["s1"], None)
    assert len(audit.rows) == 1


FULL = Declared("visit-0001", frozenset({"identity", "attacks", "detections", "overview"}), "7d")
SECTIONS = ("identity", "attacks", "detections")
GAP = page_loads.WINDOW_S + page_loads.JITTER_S + 1  # longer than a visit stays open


def _page(loads: PageLoadAudit, *parts: str) -> None:
    """The Dashboard's requests for `parts` at 7d, scope s1."""
    for part in parts:
        loads.record(FULL, "u1", None, [part], None if part == "overview" else "7d", ["s1"], None)


def test_a_dashboard_left_open_for_two_hours_writes_one_row(pin_now: Pin) -> None:
    """The page's own timers: the Overview every 60 s, the sections every 300 s."""
    loads, audit, now = _loads()
    start = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
    pin_now(start)
    _page(loads, *SECTIONS, "overview")
    for second in range(60, 2 * 3600 + 1, 60):
        now[0] = float(second)
        pin_now(start + timedelta(seconds=second))
        _page(loads, "overview")
        if second % 300 == 0:
            _page(loads, *SECTIONS)
    assert len(audit.rows) == 1
    detail = audit.rows[0][2]
    assert detail["shown"] == ["attacks", "detections", "identity", "overview"]
    assert detail["started_at"] == "2026-11-12T09:00:00+00:00"


def test_a_gap_ends_the_visit_and_the_next_request_writes_a_new_row() -> None:
    loads, audit, now = _loads()
    _page(loads, "overview")
    now[0] += page_loads.WINDOW_S + page_loads.JITTER_S  # just within: the same visit
    _page(loads, "overview")
    assert len(audit.rows) == 1
    now[0] += GAP
    _page(loads, "overview")
    assert len(audit.rows) == 2
    assert audit.rows[1][2]["shown"] == sorted(FULL.parts)  # a new visit lists every part


def test_a_request_that_shows_something_new_writes_a_row_at_once() -> None:
    loads, audit, now = _loads()
    _page(loads, *SECTIONS, "overview")
    now[0] += 30
    loads.record(FULL, "u1", None, ["identity"], "30d", ["s1"], None)  # another window
    assert [r[2]["shown"] for r in audit.rows][1:] == [["attacks", "detections", "identity"]]
    assert audit.rows[1][2]["started_at"] == audit.rows[0][2]["started_at"]  # the same visit


def test_a_visit_past_twelve_hours_writes_a_new_row(pin_now: Pin) -> None:
    loads, audit, now = _loads()
    pin_now(datetime(2026, 11, 12, 0, 0, tzinfo=UTC))
    _page(loads, "overview")
    while now[0] + 60 < page_loads.MAX_VISIT_S:
        now[0] += 60
        _page(loads, "overview")
    assert len(audit.rows) == 1
    now[0] = page_loads.MAX_VISIT_S
    pin_now(datetime(2026, 11, 12, 12, 0, tzinfo=UTC))
    _page(loads, "overview")
    assert len(audit.rows) == 2
    assert audit.rows[1][2]["started_at"] == "2026-11-12T12:00:00+00:00"


def test_a_flood_of_ids_is_audited_row_by_row(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(page_loads, "MAX_LOADS", 1)
    loads, audit, now = _loads()
    _one(loads, VISIT)
    _one(loads, Declared("visit-0002", VISIT.parts, "7d"))  # no room: its own row at once
    assert [a for a, _, _ in audit.rows] == ["dashboard.view", "dashboard.sections"]
    now[0] += page_loads.WINDOW_S + page_loads.JITTER_S + 1  # the first visit ends: room
    _one(loads, Declared("visit-0002", VISIT.parts, "7d"))
    assert [a for a, _, _ in audit.rows][-1] == "dashboard.view"


def test_every_source_is_its_own_scope() -> None:
    loads, audit, _ = _loads()
    loads.record(VISIT, "u1", None, ["overview"], None, None, None)
    loads.record(VISIT, "u1", None, ["overview"], None, ["s1"], None)  # narrower: a new row
    assert [r[2]["sources_in_scope"] for r in audit.rows] == [None, ["s1"]]


@pytest.mark.parametrize(
    ("headers", "ok"),
    [
        ({"x-page-load": "visit-0001", "x-page-load-parts": "identity, overview"}, True),
        ({"x-page-load": "visit-0001", "x-page-load-parts": "overview"}, True),
        ({"x-page-load": "visit-0001"}, False),
        ({"x-page-load-parts": "overview"}, False),
        ({"x-page-load": "short", "x-page-load-parts": "overview"}, False),
        ({"x-page-load": "visit-0001", "x-page-load-parts": ""}, False),
        ({"x-page-load": "visit-0001", "x-page-load-parts": "overview,,identity"}, False),
        ({"x-page-load": "visit-0001", "x-page-load-parts": "admin"}, False),
        ({"x-page-load": "visit-0001", "x-page-load-parts": "overview" + ",overview" * 40}, False),
        (
            {
                "x-page-load": "visit-0001",
                "x-page-load-parts": "overview",
                "x-page-load-window": "1d",
            },
            False,
        ),
    ],
)
def test_the_headers_are_parsed_strictly(headers: dict[str, str], ok: bool) -> None:
    assert (declared(headers) is not None) is ok
