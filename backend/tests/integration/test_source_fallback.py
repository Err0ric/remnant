# ruff: noqa: F811  # the lab fixture is imported, then named by each test
"""ADR-0050 rows 4 to 6 (slice 2): a source storing events without its parser says so on
Health and Sources, naming the source and the template and the detection gap; every alert
target gets one `source_fallback` message when it starts and one `source_fallback_cleared`
with the count when the template loads again; no repeat while it lasts; audited."""

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from tests.integration.test_detection_stops import everyone, lab, sent  # noqa: F401  # fixture

LINE = "<38>Oct  9 20:41:12 bastion sshd[1]: Failed password for root from 203.0.113.9 port 4"


def _append(lab: dict[str, Any], n: int) -> None:
    log = Path(lab["db"]).parent.parent / "logs" / "lin" / "auth.log"
    with log.open("a") as fh:
        fh.write((LINE + "\n") * n)


def _fallback_sent(lab: dict[str, Any]) -> list[tuple[str, str, str]]:
    return [s for s in sent(lab) if s[0].startswith("source_fallback")]


def _error(client: Any, h: dict[str, str] | None = None) -> str:
    src = next(
        s
        for s in client.get("/api/sources", headers=h or {}).json()
        if s["source_id"] == "lin_auth"
    )
    return str(src["status"]["error"])


def test_one_message_each_way_with_the_count_and_audited(lab: dict[str, Any]) -> None:
    app = lab["app"]
    template = app.state.templates._templates.pop("linux_sshd")
    _append(lab, 3)
    app.state.ingest.run_once()
    assert _fallback_sent(lab) == everyone(lab, "source_fallback", "Source lin_auth")
    _append(lab, 2)
    lab["at"].now += timedelta(minutes=5)
    app.state.ingest.run_once()
    app.state.ingest.run_once()
    assert len(_fallback_sent(lab)) == len(lab["targets"])  # no repeat while it lasts

    app.state.templates._templates["linux_sshd"] = template
    app.state.ingest.run_once()
    cleared = [s for s in _fallback_sent(lab) if s[0] == "source_fallback_cleared"]
    assert cleared == everyone(lab, "source_fallback_cleared", "Source lin_auth")
    with app.state.meta.connect() as con:
        details = [
            json.loads(r[0])
            for r in con.execute(
                "SELECT alert FROM alert_deliveries WHERE alert LIKE '%source_fallback_cleared%'"
            )
        ]
        audit = con.execute(
            "SELECT action, detail FROM audit_log WHERE action LIKE 'source.fallback%'"
            " ORDER BY rowid"
        ).fetchall()
    assert "5 events were stored without linux_sshd" in details[0]["detail"]
    assert [a for a, _ in audit] == ["source.fallback", "source.fallback_cleared"]
    assert json.loads(audit[1][1]) == {
        "source_id": "lin_auth",
        "template_id": "linux_sshd",
        "events": 5,
    }
    app.state.ingest.run_once()
    assert len(_fallback_sent(lab)) == 2 * len(lab["targets"])  # nothing more once cleared


def test_the_message_and_the_error_name_the_source_template_and_gap(lab: dict[str, Any]) -> None:
    app = lab["app"]
    app.state.templates._templates.pop("linux_sshd")
    app.state.ingest.run_once()
    error = _error(lab["admin"], lab["h"])
    assert error.startswith(
        "Source lin_auth is storing events without its parser: template linux_sshd is not"
        " available."
    )
    assert "miss these events until they are reparsed" in error
    with app.state.meta.connect() as con:
        (alert,) = {r[0] for r in con.execute("SELECT alert FROM alert_deliveries")}
    assert json.loads(alert)["detail"] == error
    # No server path in it, so an analyst who reads the source sees the same words on
    # Health, not the generic "cannot be read right now".
    overview = lab["ana"].get("/api/overview").json()
    (row,) = [s for s in overview["sources"] if s["source_id"] == "lin_auth"]
    assert row["error"] == error


def test_a_restart_does_not_repeat_the_start_message(lab: dict[str, Any]) -> None:
    app = lab["app"]
    app.state.templates._templates.pop("linux_sshd")
    app.state.ingest.run_once()
    before = len(_fallback_sent(lab))
    app.state.ingest._status.clear()  # a restart forgets in-memory status, not the table
    app.state.ingest.run_once()
    assert len(_fallback_sent(lab)) == before


def test_a_removed_source_is_forgotten_without_a_message(lab: dict[str, Any]) -> None:
    app = lab["app"]
    app.state.templates._templates.pop("linux_sshd")
    app.state.ingest.run_once()
    before = len(_fallback_sent(lab))
    assert lab["admin"].delete("/api/sources/lin_auth", headers=lab["h"]).status_code == 204
    app.state.ingest.run_once()
    assert len(_fallback_sent(lab)) == before
    with app.state.meta.connect() as con:
        assert con.execute("SELECT count(*) FROM source_fallbacks").fetchone()[0] == 0


def _details(lab: dict[str, Any], kind: str) -> list[str]:
    with lab["app"].state.meta.connect() as con:
        rows = con.execute(
            "SELECT DISTINCT alert FROM alert_deliveries ORDER BY created_at"
        ).fetchall()
    alerts = [json.loads(r[0]) for r in rows]
    return [a["detail"] for a in alerts if a["kind"] == kind and a["title"] == "Source lin_auth"]


def test_switching_to_a_template_that_loads_says_so(lab: dict[str, Any]) -> None:
    """Review on #497: the cleared message names what happened, not "loads again"."""
    app = lab["app"]
    app.state.templates._templates.pop("linux_sshd")
    app.state.ingest.run_once()
    res = lab["admin"].patch(
        "/api/sources/lin_auth", json={"template_id": "auto"}, headers=lab["h"]
    )
    assert res.status_code == 200, res.text
    app.state.ingest.run_once()
    (cleared,) = _details(lab, "source_fallback_cleared")
    assert cleared.startswith("The source now uses template auto instead of linux_sshd.")


def test_switching_to_another_missing_template_closes_one_and_opens_the_other(
    lab: dict[str, Any],
) -> None:
    app = lab["app"]
    registry = app.state.templates
    registry._templates.pop("linux_sshd")
    app.state.ingest.run_once()
    res = lab["admin"].patch(
        "/api/sources/lin_auth", json={"template_id": "windows_nxlog_json"}, headers=lab["h"]
    )
    assert res.status_code == 200, res.text
    registry._templates.pop("windows_nxlog_json")
    app.state.ingest.run_once()
    (cleared,) = _details(lab, "source_fallback_cleared")
    assert cleared.startswith(
        "The source now uses template windows_nxlog_json instead of linux_sshd."
    )
    starts = _details(lab, "source_fallback")
    assert len(starts) == 2 and "template windows_nxlog_json is not available" in starts[1]


def test_a_turned_off_source_is_forgotten_without_a_message(lab: dict[str, Any]) -> None:
    app = lab["app"]
    app.state.templates._templates.pop("linux_sshd")
    app.state.ingest.run_once()
    before = len(_fallback_sent(lab))
    with app.state.meta.connect() as con:  # turned off (no API sets it; the store does)
        con.execute("UPDATE sources SET enabled = 0 WHERE source_id = 'lin_auth'")
    app.state.ingest.run_once()
    assert len(_fallback_sent(lab)) == before
    with app.state.meta.connect() as con:
        assert con.execute("SELECT count(*) FROM source_fallbacks").fetchone()[0] == 0


def test_only_the_exact_fallback_text_skips_the_redaction() -> None:
    """Review on #497: a "Cannot read" error whose file name holds the phrase stays an
    error for administrators only."""
    from app.alerts.fallback import fallback_error, is_fallback_error

    assert is_fallback_error(fallback_error("lin_auth", "linux_sshd"))
    lookalike = (
        "Cannot read 1 of 2 files (x is storing events without its parser: template y: "
        "Permission denied)"
    )
    assert not is_fallback_error(lookalike)
    assert not is_fallback_error(fallback_error("lin_auth", "linux_sshd") + " /srv/secret")


def test_events_of_the_last_pass_count_when_the_template_returns_mid_pass(
    lab: dict[str, Any],
) -> None:
    """Review on #497: stored without the parser at the start of the pass, then the
    template is approved: those events are in the cleared count."""
    fallbacks = lab["app"].state.ingest.fallbacks
    fallbacks.update("lin_auth", "linux_sshd", 3, "linux_sshd")
    fallbacks.update("lin_auth", None, 2, "linux_sshd")
    (cleared,) = _details(lab, "source_fallback_cleared")
    assert cleared.startswith("Template linux_sshd loads again. 5 events were stored")


def _rows(lab: dict[str, Any]) -> list[tuple[Any, ...]]:
    with lab["app"].state.meta.connect() as con:
        return [
            tuple(r)
            for r in con.execute(
                "SELECT source_id, template_id, since, events, cleared_at FROM source_fallbacks"
            )
        ]


def test_a_clear_keeps_the_row_with_its_count_until_a_reparse(lab: dict[str, Any]) -> None:
    """The cleared row stays (with when it cleared), so Sources can tell which sources have
    events to reparse without reading the lake on every load (review on #500)."""
    fallbacks = lab["app"].state.ingest.fallbacks
    fallbacks._clock = lab["at"]
    fallbacks.update("lin_auth", "linux_sshd", 3, "linux_sshd")
    lab["at"].now += timedelta(minutes=5)
    fallbacks.update("lin_auth", None, 2, "linux_sshd")
    ((sid, tid, _, events, cleared_at),) = _rows(lab)
    assert (sid, tid, events) == ("lin_auth", "linux_sshd", 5)
    assert cleared_at == lab["at"].now.isoformat()
    kept = _rows(lab)
    fallbacks.update("lin_auth", None, 4, "linux_sshd")  # still fine: nothing changes
    assert _rows(lab) == kept
    assert len(_details(lab, "source_fallback_cleared")) == 1
    assert fallbacks.reparse_offers() == {"lin_auth": "linux_sshd"}
    fallbacks.reparsed("lin_auth", "linux_sshd")
    assert _rows(lab) == []


def test_a_second_outage_after_a_clear_is_a_new_outage(lab: dict[str, Any]) -> None:
    fallbacks = lab["app"].state.ingest.fallbacks
    fallbacks._clock = lab["at"]
    fallbacks.update("lin_auth", "linux_sshd", 3, "linux_sshd")
    fallbacks.update("lin_auth", None, 0, "linux_sshd")
    lab["at"].now += timedelta(hours=2)
    fallbacks.update("lin_auth", "linux_sshd", 4, "linux_sshd")
    assert len(_details(lab, "source_fallback")) == 2  # a new start message
    ((_, tid, since, events, cleared_at),) = _rows(lab)
    assert (tid, since, events, cleared_at) == (
        "linux_sshd",
        lab["at"].now.isoformat(),
        4,
        None,
    )
    assert fallbacks.reparse_offers() == {}
    fallbacks.reparsed("lin_auth", "linux_sshd")  # an outage in progress stays
    assert len(_rows(lab)) == 1
    lab["at"].now += timedelta(minutes=5)
    fallbacks.update("lin_auth", None, 1, "linux_sshd")
    cleared = _details(lab, "source_fallback_cleared")
    assert len(cleared) == 2 and "5 events were stored without linux_sshd" in cleared[-1]
    with lab["app"].state.meta.connect() as con:
        actions = [
            r[0]
            for r in con.execute(
                "SELECT action FROM audit_log WHERE action LIKE 'source.fallback%' ORDER BY rowid"
            )
        ]
    assert actions == ["source.fallback", "source.fallback_cleared"] * 2


def test_a_missing_parser_sends_no_detection_stopped_messages(lab: dict[str, Any]) -> None:
    """Owner, 2026-11-11: ADR-0050's start and back messages replace D236's for a missing
    parser (events are still stored); one outage sends two messages, not four."""
    from app.alerts.stops import GRACE

    app = lab["app"]
    template = app.state.templates._templates.pop("linux_sshd")
    app.state.ingest.run_once()
    lab["at"].now += GRACE + timedelta(minutes=1)
    app.state.ingest.run_once()
    app.state.templates._templates["linux_sshd"] = template
    app.state.ingest.run_once()
    kinds = {k for k, title, _ in sent(lab) if title == "Source lin_auth"}
    assert kinds == {"source_fallback", "source_fallback_cleared"}
