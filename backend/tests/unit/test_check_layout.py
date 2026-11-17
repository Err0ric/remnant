"""scripts/check-layout.py: the page pattern's limits (ADR-0052, redesign build row 24) and
the list of pages it opens."""

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_layout", ROOT / "scripts/check-layout.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_page_inside_the_limits_passes() -> None:
    script = _script()
    assert script.limits({"rail": 10, "tabs": 5, "filled": ["Close"]}) == []
    assert script.limits({"rail": 9, "tabs": 0, "filled": []}) == []


def test_a_sixth_tab_fails() -> None:
    assert _script().limits({"rail": 9, "tabs": 6, "filled": []}) == ["6 tabs, at most 5"]


def test_a_second_filled_button_fails_and_names_both() -> None:
    got = _script().limits({"rail": 9, "tabs": 3, "filled": ["Save", "Add alias"]})
    assert got == ["2 filled buttons (Save, Add alias), at most 1"]


def test_an_eleventh_rail_entry_fails() -> None:
    assert _script().limits({"rail": 11, "tabs": 0, "filled": []}) == [
        "11 rail entries, at most 10"
    ]


def test_the_recent_region_holds_at_most_five_links_apart_from_the_pages() -> None:
    """D258: Recent is its own region under the pages; the rail's 10 counts pages only."""
    script = _script()
    assert script.limits({"rail": 10, "recent": 5, "tabs": 0, "filled": []}) == []
    assert script.limits({"rail": 9, "tabs": 0, "filled": []}) == []  # no Recent drawn
    assert script.limits({"rail": 9, "recent": 6, "tabs": 0, "filled": []}) == [
        "6 Recent links, at most 5"
    ]


def test_the_pinned_region_holds_at_most_five_links_apart_from_the_pages() -> None:
    """D259: Pinned is its own region above Recent; the rail's 10 counts pages only."""
    script = _script()
    assert script.limits({"rail": 10, "pinned": 5, "recent": 5, "tabs": 0, "filled": []}) == []
    assert script.limits({"rail": 9, "pinned": 6, "tabs": 0, "filled": []}) == [
        "6 Pinned links, at most 5"
    ]


def test_every_page_and_every_tab_is_opened_at_its_own_address() -> None:
    paths = _script().pages()
    # Tabs have paths of their own (`/<page>/<tab>`); the first tab is the page itself.
    for path in ("/alerts", "/alerts/rules", "/ai/people", "/agents/mcp", "/health/delivery",
                 "/investigate/views/mail", "/audit/integrity"):  # fmt: skip
        assert path in paths, path
    assert "/ai/services" not in paths and not any("#monitor" in p for p in paths)
    # A Record page: a person, an address, and a host.
    assert [p for p in paths if "#" in p] == [
        "/investigate/people#user=alice",
        "/investigate/people#ip=203.0.113.9",
        "/investigate/people#host=ws-0042",
    ]
    assert len(paths) == len(set(paths)) and "/setup" not in paths


def test_nothing_found_where_something_must_be_fails() -> None:
    """A renamed label must not read as zero and pass."""
    script = _script()
    assert script.limits({"rail": 0, "tabs": 0, "filled": []}) == ["no rail entries found"]
    assert script.limits({"rail": 9, "tabs": 0, "filled": []}, has_tabs=True) == [
        "no tab strip found on a page that has tabs"
    ]
    assert script.limits({"rail": 9, "tabs": 3, "filled": []}, has_tabs=True) == []


def test_the_pages_with_tabs_are_known() -> None:
    tabbed = _script().tabbed()
    assert {"/ai", "/ai/people", "/agents", "/agents/mcp", "/health", "/audit/integrity"} <= tabbed
    assert "/dashboard" not in tabbed and "/alerts" not in tabbed


def test_the_script_looks_for_the_labels_the_app_draws() -> None:
    """The counting is by label: the app's own source must still carry those labels."""
    script = _script()
    src = ROOT / "frontend" / "src" / "components" / "shell"
    assert 'nav[aria-label="Primary"]' in script.COUNT_JS
    assert 'aria-label="Primary"' in (src / "SideNav.tsx").read_text()
    # Entries by their mark, so the current page's tab rows do not count (D268).
    assert "[data-rail-entry]" in script.COUNT_JS
    assert "data-rail-entry={row.key}" in (src / "SideNav.tsx").read_text()
    assert "} tabs`}" in (src / "PageHeader.tsx").read_text()


def _head(name: str, height: float, fill: str = "rgba(0, 0, 0, 0)") -> dict[str, object]:
    return {"name": name, "height": height, "fill": fill, "card": "rgb(20, 24, 28)"}


def test_card_headers_of_one_height_and_no_fill_pass() -> None:
    script = _script()
    assert script.card_headers([]) == []
    assert script.card_headers([_head("AI Watch", 40), _head("Top services", 40.2)]) == []
    # A fill the same as the card's is no fill.
    assert script.card_headers([_head("Needs you", 40, "rgb(20, 24, 28)")]) == []


def test_a_card_header_of_another_height_fails_and_names_each() -> None:
    got = _script().card_headers([_head("AI Watch", 40), _head("Identity", 48)])
    assert got == ["card headers of 2 heights (AI Watch 40px, Identity 48px)"]


def test_a_filled_card_header_fails() -> None:
    got = _script().card_headers([_head("Inventory", 40, "rgb(30, 34, 40)")])
    assert got == ["card header of Inventory has a fill (rgb(30, 34, 40))"]


def test_the_script_finds_the_headers_the_card_draws() -> None:
    script = _script()
    card = (ROOT / "frontend" / "src" / "components" / "Card.tsx").read_text()
    assert "[data-card-header]" in script.CARDS_JS and "data-card-header" in card
    assert "[data-card]" in script.CARDS_JS and "data-card=" in card


def test_a_hand_built_card_header_fails_on_the_card_pages_only() -> None:
    script = _script()
    assert script.hand_built("/dashboard", ["Needs you"]) == [
        "card 'Needs you' has a header drawn by hand, not by Card"
    ]
    assert script.hand_built("/investigate/people#user=alice", ["What it did"]) != []
    assert script.hand_built("/agents/mcp", []) == []
    # Pages not moved to the anatomy yet are not checked by this rule.
    assert script.hand_built("/sources", ["Configured sources"]) == []
    assert script.hand_built("/ai-settings", ["AI watch"]) == []
    assert "[data-card-header]" in script.HAND_JS and "[data-card]" in script.HAND_JS
