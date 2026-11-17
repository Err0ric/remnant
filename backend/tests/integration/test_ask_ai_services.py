"""Fix list 2026-11-16, items 20, 21, and S7: Ask's "Which AI services are people using?"
counts AI services the way AI usage does, from every source that can show one (not DNS
only), on the caller's own view; an answer without event ids says what was counted; and
"Sources read" names only the sources whose files the query read."""

import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest

from app.core import clock
from app.core.schema import COLUMN_NAMES
from app.ingest.writer import LakeWriter
from tests.integration.test_ask_routing import lab as lab  # the fixture

QUESTION = "Which AI services are people using?"


def row(source: str, template: str, at: datetime, **change: Any) -> dict[str, Any]:
    r: dict[str, Any] = dict.fromkeys(COLUMN_NAMES)
    r.update(
        event_id=str(uuid.uuid4()), source_id=source, template_id=template,
        template_version="1.0.0", time=at, time_observed=at, raw=f"line {at}",
        raw_bytes_invalid=False, parse_status="ok", classification="internal",
        owner_id="system", message="m", unmapped="{}",
    )  # fmt: skip
    r.update(change)
    return r


@pytest.fixture
def ai_lab(lab: dict[str, Any]) -> dict[str, Any]:
    """One AI service per source kind, each only in that kind: Claude in DNS, ChatGPT on
    the proxy, Microsoft Copilot in a firewall URL log, Gemini in Microsoft 365, and
    Perplexity in a source the analyst may not read."""
    now = clock.now()  # pinned by the lab
    at = now - timedelta(hours=2)
    rows = [
        row("dns", "dns_bind", at, class_uid=4003, message="claude.ai.", src_endpoint_ip="10.20.1.5"),
        row("dns", "dns_bind", at, class_uid=4003, message="www.example.com", src_endpoint_ip="10.20.1.5"),
        row("proxy", "cef_generic", at, class_uid=4002, dst_endpoint_hostname="chatgpt.com",
            src_endpoint_hostname="ws-0042", actor_user_name="alice"),
        row("proxy", "cef_generic", at, class_uid=4002, dst_endpoint_hostname="chatgpt.com",
            src_endpoint_hostname="ws-0043", actor_user_name="bob"),
        row("fw", "paloalto_threat", at, class_uid=4001, src_endpoint_ip="10.20.1.6",
            unmapped='{"url": "copilot.microsoft.com/chat?x=1"}'),
        row("m365", "m365_management_activity", at, class_uid=6003, actor_user_name="carol",
            unmapped='{"hostname": "gemini.google.com"}'),
        row("secret", "cef_generic", at, class_uid=4002, dst_endpoint_hostname="perplexity.ai",
            actor_user_name="mallory"),
        # Two services an admin may add under one name (item 4 of the review).
        row("proxy", "cef_generic", at, class_uid=4002, dst_endpoint_hostname="chat-a.example.com",
            actor_user_name="grace"),
        row("proxy", "cef_generic", at, class_uid=4002, dst_endpoint_hostname="chat-b.example.com",
            actor_user_name="heidi"),
    ]  # fmt: skip
    LakeWriter(lab["app"].state.engine._lake).write(rows)
    # The lake's own sources, granted as an admin's group change would (the API takes
    # only configured sources; these were written straight to the lake).
    with lab["app"].state.meta.connect() as con:
        for sid in ("dns", "proxy", "fw", "m365"):  # not "secret"
            con.execute(
                "INSERT INTO group_sources (group_id, source_id) VALUES (?, ?)", (lab["gid"], sid)
            )
    lab["window"] = {"start": (now - timedelta(hours=24)).isoformat(), "end": now.isoformat()}
    return lab


def asked(
    client: Any, window: dict[str, str], question: str = QUESTION, h: Any = None
) -> dict[str, Any]:
    res = client.post("/api/ask", json={"question": question, "tz": "UTC", **window}, headers=h)
    assert res.status_code == 200, res.text
    body: dict[str, Any] = res.json()
    run = client.post(f"/api/ask/{body['ask_id']}/run", headers=h)
    assert run.status_code == 200, run.text
    out: dict[str, Any] = {"ask": body, **run.json()}
    return out


def by_service(run: dict[str, Any]) -> dict[str, tuple[int, int, int]]:
    cols = run["columns"]
    rows = [dict(zip(cols, r, strict=True)) for r in run["rows"]]
    return {r["service"]: (r["events"], r["people"], r["machines"]) for r in rows}


def by_id(run: dict[str, Any]) -> dict[str, tuple[str, int, int, int]]:
    cols = run["columns"]
    rows = [dict(zip(cols, r, strict=True)) for r in run["rows"]]
    return {r["service_id"]: (r["service"], r["events"], r["people"], r["machines"]) for r in rows}


def usage(client: Any, window: dict[str, str]) -> dict[str, tuple[str, int, int, int]]:
    res = client.get("/api/ai/usage", params=window)
    assert res.status_code == 200, res.text
    return {
        u["service"]["id"]: (u["service"]["name"], u["events"], u["people"], u["machines"])
        for u in res.json()["services"]
    }


def add_service(lab: dict[str, Any], sid: str, name: str, *domains: str) -> None:
    body = {"id": sid, "name": name, "vendor": "Example", "kind": "chat", "domains": domains}
    res = lab["admin"].post("/api/ai/services", json=body, headers=lab["h"])
    assert res.status_code == 201, res.text


@pytest.mark.parametrize("who", ["admin", "ana"])
def test_the_library_answer_is_the_ai_usage_services_list(ai_lab: dict[str, Any], who: str) -> None:
    add_service(ai_lab, "team_chat_a", "Team chat", "chat-a.example.com")
    add_service(ai_lab, "team_chat_b", "Team chat", "chat-b.example.com")
    client = ai_lab[who]
    run = asked(client, ai_lab["window"], h=ai_lab["h"] if who == "admin" else None)
    assert run["ask"]["route"]["library"]["ref"] == "ai_services/ai_services_in_use"
    assert run["ask"]["route"]["by"] == "library"  # no model call
    got = by_service(run)
    # Every source kind, not DNS only; the analyst never sees the source they cannot read.
    want = {"Claude", "ChatGPT", "Microsoft Copilot", "Gemini", "Team chat"}
    assert set(got) == (want | {"Perplexity"} if who == "admin" else want)
    assert got["ChatGPT"] == (2, 2, 2)
    # By id, as the page lists them: two services with one name stay two rows.
    ids = by_id(run)
    assert {"team_chat_a", "team_chat_b"} <= set(ids)
    assert ids == usage(client, ai_lab["window"])


def test_a_service_seen_only_on_the_proxy_or_firewall_is_listed(ai_lab: dict[str, Any]) -> None:
    run = asked(ai_lab["ana"], ai_lab["window"])
    cols = run["columns"]
    seen = {r[cols.index("service")]: r[cols.index("sources")] for r in run["rows"]}
    assert seen["ChatGPT"] == "proxy"
    assert seen["Microsoft Copilot"] == "fw"
    assert seen["Gemini"] == "m365"
    assert seen["Claude"] == "dns"


def test_what_was_counted_is_written_from_the_run(ai_lab: dict[str, Any]) -> None:
    run = asked(ai_lab["ana"], ai_lab["window"])
    n = len(run["sources"])
    assert run["counted"] == (
        f"Read {n} sources from Oct 19, 12:00 PM UTC to Oct 20, 12:00 PM UTC and counted"
        " events, grouped by AI service."
    )
    assert run["summary_note"] is None  # the counted line says it once
    assert run["headline"].startswith("4 services in use; most events: ChatGPT (2)")
    # A window that ends now reads as its preset.
    now = datetime.fromisoformat(ai_lab["window"]["end"])
    open_end = {"start": (now - timedelta(days=7)).isoformat()}
    assert "for the last 7 days" in asked(ai_lab["ana"], open_end)["counted"]


def test_sources_read_are_the_ones_the_query_read(ai_lab: dict[str, Any]) -> None:
    """S7: a DNS question reads the DNS source only, of the six the analyst may read."""
    run = asked(ai_lab["ana"], ai_lab["window"], "Top DNS names looked up")
    assert run["ask"]["route"]["library"]["ref"] == "dns_ai/dns_top_domains"
    assert run["sources"] == ["dns"]
    assert run["counted"] is None or "1 source" in run["counted"]


def test_a_catalog_too_long_for_typed_sql_still_answers(ai_lab: dict[str, Any]) -> None:
    """Item 20's SQL is built from the catalog: an admin's own services can make it longer
    than the 20,000 characters typed SQL may have. Ask still runs it by id (the guard reads
    it as usual), a follow-up refers to it by id, and Save as my own and Replace my copy
    say plainly why it cannot be a saved search."""
    admin, h = ai_lab["admin"], ai_lab["h"]
    base = "/api/library/ai_services/ai_services_in_use"
    assert admin.post(f"{base}/copy", headers=h).status_code == 201  # fits while short
    for i in range(30):
        add_service(ai_lab, f"tool_{i:02d}", f"Tool {i}",
                    *[f"tool{i:02d}-{j}.example.com" for j in range(12)])  # fmt: skip
    run = asked(admin, ai_lab["window"], h=h)
    assert len(run["ask"]["sql"]) > 20_000
    assert set(by_service(run)) >= {"Claude", "ChatGPT"}
    for path, code in ((f"{base}/replace", 400), (f"{base}/copy", 400)):
        res = admin.post(path, headers=h)
        assert res.status_code == code, res.text
        assert "longer than a saved search can be" in res.json()["detail"]
    # A follow-up names the earlier answer by id; its SQL is never posted back.
    turn = {"question": QUESTION, "ask_id": run["ask"]["ask_id"]}
    res = admin.post(
        "/api/ask",
        json={"question": "only Claude", "tz": "UTC", "history": [turn], **ai_lab["window"]},
        headers=h,
    )
    assert res.status_code == 200, res.text
    sent = ai_lab["calls"]["seen"][-1]
    assert "ai_services/ai_services_in_use" in str(sent) and "tool00-0" not in str(sent)


def test_a_turn_needs_its_id_or_its_sql(ai_lab: dict[str, Any]) -> None:
    res = ai_lab["ana"].post(
        "/api/ask", json={"question": "only Claude", "history": [{"question": QUESTION}]}
    )
    assert res.status_code == 422


def test_the_counted_line_names_the_window_read_not_the_one_asked(ai_lab: dict[str, Any]) -> None:
    """Second review of 636: "the last 120 days" is cut to Ask's 90-day cap, and the line
    says what was read."""
    run = asked(ai_lab["ana"], {}, "Which AI services are people using in the last 120 days?")
    assert run["ask"]["route"]["time"] == "the last 120 days"
    assert "120 days" not in run["counted"]
    assert "from Jul 22, 12:00 PM UTC to Oct 20, 12:00 PM UTC" in run["counted"]


def test_an_expired_earlier_answer_does_not_block_a_follow_up(ai_lab: dict[str, Any]) -> None:
    """Second review of 636: a turn sent by id alone (its SQL too long to send back) whose
    answer has expired still lets the follow-up run, with a line in its SQL's place."""
    run = asked(ai_lab["ana"], ai_lab["window"])
    ai_lab["app"].state.ask_runs._kept.clear()  # as after 30 minutes or 500 newer answers
    turn = {"question": QUESTION, "ask_id": run["ask"]["ask_id"]}
    body = {"question": "only Claude", "tz": "UTC", "history": [turn], **ai_lab["window"]}
    res = ai_lab["ana"].post("/api/ask", json=body)
    assert res.status_code == 200, res.text
    assert "has expired" in str(ai_lab["calls"]["seen"][-1])
