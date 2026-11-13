"""The few alert lines a summary shows are picked in the order the Dashboard's Needs you list
uses (ADR-0052 section 3.9): High alerts, then other alerts, then AI review items, newest
first within each. Review of #555: picked by severity alone, five unreviewed AI services
(Medium) pushed an older Medium rule alert out of the list."""

from types import SimpleNamespace
from typing import Any

from app.api.alert_items import in_list_order


def _line(item_id: str, severity: str | None) -> tuple[Any, int]:
    return (SimpleNamespace(item_id=item_id, severity=severity), 1)


def test_review_items_come_after_every_other_alert() -> None:
    newest_first = [
        *[_line(f"review{n}", "medium") for n in range(5)],
        _line("rule-medium", "medium"),
        _line("rule-none", None),
        _line("rule-high", "high"),
    ]
    review = {f"review{n}" for n in range(5)}
    ordered = [i.item_id for i, _ in in_list_order(newest_first, review)]
    assert ordered[:3] == ["rule-high", "rule-medium", "rule-none"]
    assert ordered[3:] == [f"review{n}" for n in range(5)]
    # So the five lines sent still hold every ordinary alert.
    assert {"rule-high", "rule-medium", "rule-none"} <= set(ordered[:5])


def test_other_alerts_stay_newest_first_whatever_their_severity() -> None:
    newest_first = [_line("none-new", None), _line("medium-old", "medium"), _line("h", "high")]
    assert [i.item_id for i, _ in in_list_order(newest_first, set())] == [
        "h",
        "none-new",
        "medium-old",
    ]


def test_a_high_review_item_is_still_a_review_item() -> None:
    newest_first = [_line("review-high", "high"), _line("rule-medium", "medium")]
    assert [i.item_id for i, _ in in_list_order(newest_first, {"review-high"})] == [
        "rule-medium",
        "review-high",
    ]
