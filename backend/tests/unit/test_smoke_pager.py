"""scripts/smoke.py: a list with more than one page of results must show a working pager
(owner, 2026-11-13: Logs said "1 to 50 of 10000" and row 51 could not be found)."""

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("smoke", ROOT / "scripts/smoke.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pager(**change: Any) -> dict[str, Any]:
    base = {"page": 1, "pages": 200, "next": True, "disabled": False, "left": 500.0,
            "right": 560.0, "width": 60.0}  # fmt: skip
    return base | change


def _list(rows: int, total: int, pager: dict[str, Any] | None) -> dict[str, Any]:
    return {"rows": rows, "total": total, "first": "row", "pager": pager}


def _state(*lists: dict[str, Any]) -> dict[str, Any]:
    return {"view": 1280, "lists": list(lists)}


def test_a_pager_on_screen_passes() -> None:
    script = _script()
    assert script.pager_problems(_state(_list(50, 10000, _pager()))) == []
    # A list that shows all it holds needs none: 12 rows, and exactly 50.
    assert script.pager_problems(_state(_list(12, 12, None), _list(50, 50, None))) == []
    assert script.pager_problems(_state()) == []


def test_a_list_that_holds_more_than_it_shows_with_no_pager_fails() -> None:
    got = _script().pager_problems(_state(_list(50, 10000, None)))
    assert got == ["pager: a results list holds more rows than it shows and has no pager"]


def test_each_list_is_judged_with_its_own_pager() -> None:
    """One list's pager does not excuse another list that has none."""
    got = _script().pager_problems(_state(_list(50, 120, _pager(pages=3)), _list(50, 90, None)))
    assert got == ["pager: a results list holds more rows than it shows and has no pager"]


def test_a_next_button_off_the_right_edge_fails() -> None:
    got = _script().pager_problems(_state(_list(50, 10000, _pager(left=1900.0, right=1960.0))))
    assert got == ["pager: the Next button is off screen sideways"]


def test_a_dead_or_missing_next_button_fails() -> None:
    script = _script()
    assert script.pager_problems(_state(_list(50, 10000, _pager(disabled=True)))) == [
        "pager: Next is disabled before the last page"
    ]
    assert script.pager_problems(_state(_list(50, 10000, _pager(next=False, width=0.0)))) == [
        "pager: more than one page but no Next button is drawn"
    ]


def test_the_script_looks_for_what_the_results_table_draws() -> None:
    """The check is by attribute: the table must still carry those attributes."""
    script = _script()
    table = (ROOT / "frontend/src/features/search/ResultsTable.tsx").read_text()
    for attr in ("data-pager", "data-pager-next", "data-page", "data-pages", "data-total"):
        assert attr in script.PAGERS_JS or attr.replace("data-", "dataset.") in script.PAGERS_JS
        assert attr in table
