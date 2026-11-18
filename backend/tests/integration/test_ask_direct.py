"""Ask's direct lookups (owner P1 item 6, D276): a question that is only an address opens
its page with no model call; anything else, names included, goes on as before."""

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from tests.integration.test_address_page import IP, RANGE
from tests.integration.test_address_page import lab as lab  # the fixture
from tests.integration.test_ask_routing import lab as routing_lab  # noqa: F401  # its base


def ask(client: Any, question: str, h: dict[str, str] | None = None) -> dict[str, Any]:
    res = client.post("/api/ask", json={"question": question, **RANGE}, headers=h or {})
    assert res.status_code == 200, res.text
    out: dict[str, Any] = res.json()
    return out


def last_ask_route(lab: dict[str, Any]) -> dict[str, Any]:
    db = sqlite3.connect(lab["db"])
    (detail,) = db.execute(
        "SELECT detail FROM audit_log WHERE action = 'ask.request' ORDER BY audit_id DESC LIMIT 1"
    ).fetchone()
    route: dict[str, Any] = json.loads(detail)["route"]
    return route


def test_an_address_alone_opens_its_page_with_no_model_call(
    lab: dict[str, Any], pin_now: Callable[[datetime], None]
) -> None:
    pin_now(datetime(2026, 10, 11, 12, 0, tzinfo=UTC))  # a day after the fixture's events
    # The brief reads the page's own 7 days, whatever range Ask was given (here none).
    res = lab["admin"].post("/api/ask", json={"question": f"  {IP}? "}, headers=lab["h"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert lab["calls"]["seen"] == []  # the fake model was never called
    assert body["route"]["by"] == "direct" and body["ask_id"] is None and body["sql"] == ""
    (hit,) = body["lookup"]
    assert (hit["kind"], hit["value"], hit["window"]) == ("ip", IP, "the last 7 days")
    brief = {s["section"]: s for s in hit["sections"]}
    assert brief["dns"]["count_words"] == "3 names" and brief["ai"]["count_words"] == "1 AI service"
    route = last_ask_route(lab)
    assert route["by"] == "direct" and route["via"] == "direct" and route["lookup"] == ["ip"]
    assert "dns" in route["sources_read"]


def test_ipv6_is_direct_and_host_or_user_names_go_to_the_model(lab: dict[str, Any]) -> None:
    hit = ask(lab["admin"], "2001:db8::5", lab["h"])["lookup"][0]
    assert (hit["kind"], hit["range"]) == ("ip", "7d")
    assert lab["calls"]["seen"] == []
    # Names are not matched in code: nothing knows every name without a scan (D276).
    for name in ("web-01", "deploy"):
        body = ask(lab["ana"], name)
        assert body["lookup"] == [] and body["route"]["by"] != "direct", name
    assert len(lab["calls"]["seen"]) >= 2


def test_an_address_after_an_earlier_turn_is_still_direct(lab: dict[str, Any]) -> None:
    """A bare address is never a refinement: it opens its page on any turn."""
    history = [{"question": "ssh logins", "sql": "SELECT 1"}]
    res = lab["ana"].post("/api/ask", json={"question": IP, "history": history, **RANGE})
    assert res.status_code == 200, res.text
    assert res.json()["route"]["by"] == "direct" and lab["calls"]["seen"] == []


def test_the_brief_reads_the_callers_full_view_not_the_ask_filter(
    lab: dict[str, Any], pin_now: Callable[[datetime], None]
) -> None:
    pin_now(datetime(2026, 10, 11, 12, 0, tzinfo=UTC))
    # Ask filtered to lin_auth; the page reads every source the caller may read, so does
    # the brief, and the counts are the page's.
    body = {"question": IP, "sources": ["lin_auth"]}
    res = lab["admin"].post("/api/ask", json=body, headers=lab["h"])
    (hit,) = res.json()["lookup"]
    assert {s["section"]: s["count_words"] for s in hit["sections"]}["dns"] == "3 names"


def test_the_brief_never_reads_the_ask_range(
    lab: dict[str, Any], pin_now: Callable[[datetime], None]
) -> None:
    pin_now(datetime(2026, 10, 11, 12, 0, tzinfo=UTC))
    # A one-hour Ask range would find nothing; the brief still reads the page's 7 days.
    hour = {"start": "2026-10-11T11:00:00Z", "end": "2026-10-11T12:00:00Z"}
    res = lab["admin"].post("/api/ask", json={"question": IP, **hour}, headers=lab["h"])
    (hit,) = res.json()["lookup"]
    assert {s["section"]: s["count_words"] for s in hit["sections"]}["dns"] == "3 names"


def test_anything_else_still_goes_to_the_model(lab: dict[str, Any]) -> None:
    for question in (f"who is {IP}", "nobody-here-9", "10.20.2", "fe80::1%eth0"):
        body = ask(lab["ana"], question)
        assert body["lookup"] == [] and body["route"]["by"] != "direct", question
    assert len(lab["calls"]["seen"]) >= 3
    assert last_ask_route(lab)["via"] == "model"
