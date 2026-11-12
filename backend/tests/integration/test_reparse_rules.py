"""Run the enabled rules over a reparse job's range (ADR-0050 row 7, slice 3b): a rule that
needs the template's fields missed the rows stored without it; after the reparse the re-run
finds them, stores normal rule matches, and raises alert items under D200. Only the job's
source is read, a second run adds nothing, and only an admin may start it."""

import json
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.core.errors import RuleRejectedError
from app.detect import runner as runner_module
from app.ingest import reparse as reparse_module
from app.ingest.writer import LakeWriter
from tests.integration.test_reparse import missing_rows
from tests.integration.test_schedules import NOW, make_lab

RULE_ID = "44444444-4444-4444-8444-444444444444"
# `method` comes only from linux_sshd's regex (kept in `unmapped`): a row stored without the
# template has no such field, so the rule cannot match it until the row is reparsed.
RULE = f"""title: SSH password method
id: {RULE_ID}
level: medium
logsource: {{product: linux, service: sshd}}
detection:
  s: {{method: password}}
  condition: s
"""
# After the sample log's last line (Oct 9 21:07), so the job's range holds only these.
NEW = [
    "<38>Oct 10 09:00:05 bastion sshd[4001]: Failed password for mallory from 203.0.113.50"
    " port 4022 ssh2",
    "<38>Oct 10 09:00:09 bastion sshd[4001]: Failed password for mallory from 203.0.113.50"
    " port 4023 ssh2",
    "<38>Oct 10 09:01:00 bastion sshd[4002]: Connection closed by 203.0.113.50 port 4024",
]
SOURCE = "lin_auth"
OTHER = "lin_two"


def rules_url(job_id: str, source: str = SOURCE) -> str:
    return f"/api/sources/{source}/reparse/{job_id}/rules"


@pytest.fixture
def base(tmp_path: Path, pin_now: Callable[[datetime], None]) -> dict[str, Any]:
    """lin_two, another linux_sshd source, holds the NEW lines parsed; the password rule
    enabled. No outage yet."""
    pin_now(NOW)
    lab = make_lab(tmp_path)
    admin, h = lab["admin"], lab["h"]
    (tmp_path / "rules" / "pw.yml").write_text(RULE)
    admin.post("/api/rules/import", json={"path": str(tmp_path / "rules")}, headers=h)
    res = admin.post("/api/rules/enabled", json={"rule_ids": [RULE_ID], "enabled": True}, headers=h)
    assert res.status_code == 200, res.text
    two = tmp_path / "logs" / "two"
    two.mkdir()
    (two / "auth.log").write_text("\n".join(NEW) + "\n")
    body = {"source_id": OTHER, "format": "syslog", "path": str(two), "template_id": "linux_sshd"}
    assert admin.post("/api/sources", json=body, headers=h).status_code == 201
    lab["app"].state.ingest.run_once()
    lab["log"] = tmp_path / "logs" / "lin" / "auth.log"
    lab["rules"] = tmp_path / "rules"
    lab["template"] = lab["app"].state.templates._templates["linux_sshd"]
    return lab


def outage(lab: dict[str, Any], lines: list[str]) -> None:
    """linux_sshd goes missing; lin_auth stores `lines` without it."""
    lab["app"].state.templates._templates.pop("linux_sshd")
    append(lab, lines)


def append(lab: dict[str, Any], lines: list[str]) -> None:
    with lab["log"].open("a") as fh:
        fh.write("\n".join(lines) + "\n")
    assert lab["app"].state.ingest.run_once() == len(lines)


def restore(lab: dict[str, Any]) -> None:
    """The template loads again and the outage clears."""
    lab["app"].state.templates._templates["linux_sshd"] = lab["template"]
    lab["app"].state.ingest.run_once()


@pytest.fixture
def lab(base: dict[str, Any]) -> dict[str, Any]:
    """lin_auth's NEW lines stored while linux_sshd was missing."""
    outage(base, NEW)
    return base


def reparse(lab: dict[str, Any]) -> str:
    """The template loads again; the reparse runs to done. Returns the job id."""
    restore(lab)
    res = lab["admin"].post(f"/api/sources/{SOURCE}/reparse", headers=lab["h"])
    assert res.status_code == 202, res.text
    lab["app"].state.reparse.join(SOURCE)
    job = lab["admin"].get(f"/api/sources/{SOURCE}/reparse").json()["job"]
    assert job["state"] == "done", job
    job_id: str = job["job_id"]
    return job_id


def run_rules(lab: dict[str, Any], job_id: str) -> Any:
    res = lab["admin"].post(rules_url(job_id), headers=lab["h"])
    if res.status_code == 202:
        lab["app"].state.reparse_rules.join(job_id)
    return res


def db(lab: dict[str, Any]) -> sqlite3.Connection:
    con = sqlite3.connect(lab["db"])
    con.row_factory = sqlite3.Row
    return con


def rule_items(lab: dict[str, Any]) -> list[sqlite3.Row]:
    with db(lab) as con:
        return con.execute(
            "SELECT * FROM alert_items WHERE kind = 'rule' AND subject = ?", (RULE_ID,)
        ).fetchall()


def matches(lab: dict[str, Any]) -> list[sqlite3.Row]:
    with db(lab) as con:
        return con.execute(
            "SELECT m.event_id, m.source_id, r.sources_in_scope FROM rule_matches m"
            " JOIN rule_runs r ON r.run_id = m.run_id WHERE r.rule_id = ?",
            (RULE_ID,),
        ).fetchall()


def last(lab: dict[str, Any], client: Any, source: str = SOURCE) -> Any:
    listed = client.get("/api/sources", headers=lab["h"]).json()
    return next(s for s in listed if s["source_id"] == source)["reparse_last"]


def test_the_re_run_finds_what_the_window_missed_once_and_only_on_that_source(
    lab: dict[str, Any],
) -> None:
    admin, h = lab["admin"], lab["h"]
    # During the window the rule cannot see lin_auth's rows (its template is missing).
    during = admin.post(
        f"/api/rules/{RULE_ID}/run",
        json={"start": "2026-10-10T08:00:00Z", "end": "2026-10-10T10:00:00Z"},
        headers=h,
    ).json()
    assert SOURCE not in during["sources_in_scope"]
    assert last(lab, admin) is None  # no job yet

    job_id = reparse(lab)
    shown = last(lab, admin)
    assert shown["job_id"] == job_id and shown["state"] == "done"
    assert shown["rules_state"] is None and shown["rows_rewritten"] == len(NEW)
    assert shown["time_min"].startswith("2026-10-10T09:00:05")
    assert shown["time_max"].startswith("2026-10-10T09:01:00")
    before = len(matches(lab))

    res = run_rules(lab, job_id)
    assert res.status_code == 202, res.text
    assert res.json()["rules_state"] == "running"
    shown = last(lab, admin)
    assert shown["rules_state"] == "done", shown
    assert (shown["rules_count"], shown["rules_matched"], shown["rules_items"]) == (1, 2, 1)
    assert shown["rules_run_at"] and shown["rules_error"] is None

    found = matches(lab)[before:]
    assert len(found) == 2
    assert {m["source_id"] for m in found} == {SOURCE}  # lin_two's same rows: not read
    assert {tuple(json.loads(m["sources_in_scope"])) for m in found} == {(SOURCE,)}
    (item,) = rule_items(lab)
    assert item["count"] == 2 and item["state"] == "open"
    assert json.loads(item["sources"]) == [SOURCE]
    assert item["ref_id"] == f"reparse:{job_id}:{RULE_ID}"
    assert (item["entity"], item["rule"]) == (RULE_ID, "rule")
    assert json.loads(item["people"]) == ["mallory"]

    # Twice for the same job: refused, nothing added.
    again = run_rules(lab, job_id)
    assert again.status_code == 409 and "already" in again.json()["detail"]
    assert len(matches(lab)) == before + 2
    assert len(rule_items(lab)) == 1 and rule_items(lab)[0]["count"] == 2


def test_an_open_item_for_the_rule_today_grows(lab: dict[str, Any]) -> None:
    """D200: an item already open for the same rule and day takes the re-run's matches."""
    open_item = lab["app"].state.alert_items.raise_item(
        "rule", RULE_ID, "SSH password method", ref_id="earlier-run", count=3,
        sources=[OTHER], group=(RULE_ID, "rule"),
    )  # fmt: skip
    job_id = reparse(lab)
    assert run_rules(lab, job_id).status_code == 202
    (item,) = rule_items(lab)
    assert item["item_id"] == open_item.item_id and item["count"] == 5
    assert last(lab, lab["admin"])["rules_items"] == 1


def test_admin_only_audited_and_refused_until_done(lab: dict[str, Any]) -> None:
    admin, h = lab["admin"], lab["h"]
    job_id = reparse(lab)
    url = rules_url(job_id)
    assert lab["ana"].post(url).status_code == 403
    assert lab["aud"].post(url).status_code == 403
    assert admin.post(url).status_code == 403  # no CSRF token
    assert last(lab, lab["ana"]) is None  # reparse jobs are for administrators
    assert admin.post(rules_url(job_id, "nope"), headers=h).status_code == 404
    assert admin.post(rules_url("no-such-job"), headers=h).status_code == 404
    assert admin.post(rules_url(job_id, OTHER), headers=h).status_code == 404  # not its job
    with db(lab) as con:  # a job still running: refused (a stopped one: test_reparse_late)
        con.execute("UPDATE reparse_jobs SET state = 'running' WHERE job_id = ?", (job_id,))
    res = admin.post(url, headers=h)
    assert res.status_code == 409 and "finished" in res.json()["detail"]
    with db(lab) as con:
        con.execute("UPDATE reparse_jobs SET state = 'done' WHERE job_id = ?", (job_id,))
    assert run_rules(lab, job_id).status_code == 202

    rows = lab["aud"].get("/api/audit/events", params={"action": "source.reparse_rules"}).json()
    steps = {r["detail"]["step"]: r for r in rows}
    assert set(steps) == {"start", "end"}
    end = steps["end"]["detail"]
    assert end["job_id"] == job_id and end["source_id"] == SOURCE
    assert (end["rules"], end["matches"], end["items"]) == (1, 2, 1)
    assert steps["end"]["outcome"] == "success"
    assert all(r["user_id"] == steps["start"]["user_id"] for r in rows)
    runs = lab["aud"].get("/api/audit/events", params={"action": "rule.run"}).json()
    assert any(r["detail"]["sources_in_scope"] == [SOURCE] for r in runs)


def test_a_job_with_nothing_rewritten_has_nothing_to_run_over(lab: dict[str, Any]) -> None:
    job_id = reparse(lab)
    with db(lab) as con:
        con.execute("DELETE FROM reparse_job_events WHERE job_id = ?", (job_id,))
    res = lab["admin"].post(rules_url(job_id), headers=lab["h"])
    assert res.status_code == 409 and "rewrote no events" in res.json()["detail"]


def test_rules_left_running_are_interrupted_and_can_finish(lab: dict[str, Any]) -> None:
    """A restart during the re-run: the job says so, and a second start runs only the
    rules that had not run for it yet (here none had)."""
    job_id = reparse(lab)
    with db(lab) as con:
        con.execute("UPDATE reparse_jobs SET rules_state = 'running' WHERE job_id = ?", (job_id,))
    assert run_rules(lab, job_id).status_code == 409  # still running
    assert lab["app"].state.reparse_rules.interrupt_left_running() == 1
    assert last(lab, lab["admin"])["rules_state"] == "interrupted"
    assert run_rules(lab, job_id).status_code == 202
    assert last(lab, lab["admin"])["rules_state"] == "done"
    assert len(rule_items(lab)) == 1


def test_a_second_start_skips_rules_that_already_ran_for_the_job(lab: dict[str, Any]) -> None:
    job_id = reparse(lab)
    with db(lab) as con:
        con.execute(
            "INSERT INTO reparse_rule_runs (job_id, rule_id, run_id, state)"
            " VALUES (?, ?, 'r1', 'done')",
            (job_id, RULE_ID),
        )
        con.execute(
            "UPDATE reparse_jobs SET rules_state = 'failed', rules_count = 1, rules_matched = 2,"
            " rules_items = 1 WHERE job_id = ?",
            (job_id,),
        )
    before = len(matches(lab))
    assert run_rules(lab, job_id).status_code == 202
    shown = last(lab, lab["admin"])
    assert shown["rules_state"] == "done"
    assert (shown["rules_count"], shown["rules_matched"], shown["rules_items"]) == (1, 2, 1)
    assert len(matches(lab)) == before and rule_items(lab) == []


# --- the rows the re-run reads (review of #503) -------------------------------------------


def write_untimed(lab: dict[str, Any], lines: list[str], at: datetime) -> None:
    """lin_auth rows stored without the template and with no event time (a headerless line,
    or JSON with no time field): the engine places them by `time_observed` (`at`)."""
    rows = missing_rows(SOURCE, lines, at)
    for row in rows:
        row["time"] = None
    app = lab["app"]
    LakeWriter(app.state.lake_dir, app.state.integrity).write(rows)


def match_times(lab: dict[str, Any]) -> list[str]:
    with db(lab) as con:
        return [
            r["event_time"]
            for r in con.execute(
                "SELECT m.event_time FROM rule_matches m JOIN rule_runs r ON r.run_id = m.run_id"
                " WHERE r.rule_id = ? AND r.sources_in_scope = ? ORDER BY 1",
                (RULE_ID, json.dumps([SOURCE])),
            )
        ]


def test_rows_with_no_time_are_run_over(base: dict[str, Any]) -> None:
    """Every reparsed row lacks `time`: the job's range comes from `time_observed`, and the
    rules still run over them."""
    at = NOW - timedelta(hours=1)
    write_untimed(base, NEW[:2], at)
    job_id = reparse(base)
    shown = last(base, base["admin"])
    assert shown["rows_rewritten"] == 2
    assert shown["time_min"].startswith("2026-10-10T11:00:00")
    assert shown["time_max"].startswith("2026-10-10T11:00:00")
    assert run_rules(base, job_id).status_code == 202
    shown = last(base, base["admin"])
    assert shown["rules_state"] == "done" and shown["rules_matched"] == 2, shown
    assert len(match_times(base)) == 2


def test_rows_with_and_without_time_are_all_run_over(lab: dict[str, Any]) -> None:
    """NEW rows have a time (09:00); one more has none and was observed at 11:30: the range
    spans both, so all three matching rows are found."""
    write_untimed(lab, NEW[:1], NOW - timedelta(minutes=30))
    job_id = reparse(lab)
    shown = last(lab, lab["admin"])
    assert shown["time_min"].startswith("2026-10-10T09:00:05")
    assert shown["time_max"].startswith("2026-10-10T11:30:00")
    assert run_rules(lab, job_id).status_code == 202
    assert last(lab, lab["admin"])["rules_matched"] == 3
    assert len(match_times(lab)) == 3


def pw(at: str, port: int) -> str:
    return (
        f"<38>Oct 10 {at} bastion sshd[4001]: Failed password for mallory from 203.0.113.50"
        f" port {port} ssh2"
    )


def test_only_the_rows_the_reparse_rewrote_are_run_over(base: dict[str, Any]) -> None:
    """Two outages, the template back in between, one reparse: rows parsed normally between
    them match the rule too, but scheduled runs saw them already, so the re-run leaves them."""
    outage(base, [pw("08:00:01", 5001), pw("08:00:02", 5002)])
    restore(base)
    append(base, [pw("08:30:01", 5003), pw("08:30:02", 5004)])  # parsed with the template
    outage(base, [pw("09:00:01", 5005), pw("09:00:02", 5006)])
    job_id = reparse(base)
    shown = last(base, base["admin"])
    assert shown["rows_rewritten"] == 4
    assert shown["time_min"].startswith("2026-10-10T08:00:01")
    assert shown["time_max"].startswith("2026-10-10T09:00:02")

    assert run_rules(base, job_id).status_code == 202
    shown = last(base, base["admin"])
    assert (shown["rules_state"], shown["rules_matched"], shown["rules_items"]) == ("done", 4, 1)
    times = match_times(base)
    assert len(times) == 4 and not any("08:30" in t for t in times), times
    (item,) = rule_items(base)
    assert item["count"] == 4
    with db(base) as con:  # the rewritten ids are not kept once every rule has run
        assert con.execute("SELECT count(*) FROM reparse_job_events").fetchone()[0] == 0

    # The rows in between do match the rule: a run over the whole range finds all six
    # (lin_two's rows are after it).
    res = base["admin"].post(
        f"/api/rules/{RULE_ID}/run",
        json={"start": "2026-10-10T07:00:00Z", "end": "2026-10-10T09:00:03Z"},
        headers=base["h"],
    )
    assert res.json()["match_count"] == 6


def runs_on_source(lab: dict[str, Any], rule_id: str = RULE_ID) -> list[sqlite3.Row]:
    with db(lab) as con:
        return con.execute(
            "SELECT run_id, status FROM rule_runs WHERE rule_id = ? AND sources_in_scope = ?",
            (rule_id, json.dumps([SOURCE])),
        ).fetchall()


def test_a_crash_at_any_point_repeats_no_match_and_no_item_count(
    lab: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = reparse(lab)
    before = len(matches(lab))
    items = lab["app"].state.alert_items
    reruns = lab["app"].state.reparse_rules

    def crash(*_: Any, **__: Any) -> None:
        raise RuntimeError("crash")

    # 1. After the rule's matches are stored, before its item is raised.
    monkeypatch.setattr(items, "raise_item", crash)
    assert run_rules(lab, job_id).status_code == 202
    assert last(lab, lab["admin"])["rules_state"] == "failed"
    assert len(matches(lab)) == before + 2 and rule_items(lab) == []
    monkeypatch.undo()

    # 2. Inside the transaction that grows the item and marks the rule done: rolled back.
    monkeypatch.setattr(reruns, "_done", crash)
    assert run_rules(lab, job_id).status_code == 202
    assert last(lab, lab["admin"])["rules_state"] == "failed"
    assert rule_items(lab) == []
    monkeypatch.undo()

    assert run_rules(lab, job_id).status_code == 202
    shown = last(lab, lab["admin"])
    assert shown["rules_state"] == "done", shown
    assert (shown["rules_count"], shown["rules_matched"], shown["rules_items"]) == (1, 2, 1)
    assert len(matches(lab)) == before + 2  # the stored run was used, not run again
    assert len(runs_on_source(lab)) == 1
    (item,) = rule_items(lab)
    assert item["count"] == 2


RULE2_ID = "55555555-5555-4555-8555-555555555555"
RULE2 = RULE.replace(RULE_ID, RULE2_ID).replace("SSH password method", "SSH password again")


def test_a_rule_that_fails_leaves_the_run_partial_and_a_retry_runs_only_it(
    lab: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, h = lab["admin"], lab["h"]
    (lab["rules"] / "pw2.yml").write_text(RULE2)
    admin.post("/api/rules/import", json={"path": str(lab["rules"])}, headers=h)
    res = admin.post(
        "/api/rules/enabled", json={"rule_ids": [RULE2_ID], "enabled": True}, headers=h
    )
    assert res.status_code == 200, res.text
    job_id = reparse(lab)
    real = runner_module.compile_rule

    def refuse(data: bytes) -> Any:
        if RULE2_ID.encode() in data:
            raise RuleRejectedError("this rule cannot be compiled now")
        return real(data)

    monkeypatch.setattr(runner_module, "compile_rule", refuse)
    started = admin.post(rules_url(job_id), headers=h)
    assert started.status_code == 202
    lab["app"].state.reparse_rules.join(job_id)
    shown = last(lab, admin)
    assert shown["rules_state"] == "partial", shown
    assert (shown["rules_count"], shown["rules_matched"], shown["rules_items"]) == (1, 2, 1)
    assert "1 of 2 rules could not run" in shown["rules_error"]
    assert "Rules page" not in shown["rules_error"]
    (failed,) = shown["rules_failed"]
    assert failed["rule_id"] == RULE2_ID and failed["title"] == "SSH password again"
    assert "cannot be compiled" in failed["error"]
    rows = lab["aud"].get("/api/audit/events", params={"action": "source.reparse_rules"}).json()
    end = next(r for r in rows if r["detail"]["step"] == "end")
    assert end["outcome"] == "failure" and end["detail"]["failed"] == [RULE2_ID]

    monkeypatch.undo()
    assert run_rules(lab, job_id).status_code == 202
    shown = last(lab, admin)
    assert shown["rules_state"] == "done" and shown["rules_failed"] == [], shown
    assert (shown["rules_count"], shown["rules_matched"], shown["rules_items"]) == (2, 4, 2)
    assert len(runs_on_source(lab)) == 1  # the rule that ran is not run again
    with db(lab) as con:  # the failed run read nothing; the retry ran it once more
        runs = con.execute("SELECT status FROM rule_runs WHERE rule_id = ?", (RULE2_ID,))
        assert sorted(r["status"] for r in runs) == ["failed", "ok"]
    again = run_rules(lab, job_id)
    assert again.status_code == 409 and "already" in again.json()["detail"]


# --- rows a stopped reparse rewrote --------------------------------------------------------


def stop_after_one_file(lab: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> str:
    """A reparse that rewrites one file and stops on the next (as a power cut would): the
    first file's rows are rewritten and their ids recorded, and the job ends `failed`.
    Returns the job id."""
    real = reparse_module.Reparser._rewrite
    calls: list[int] = []

    def cut(self: Any, *args: Any) -> Any:
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("power cut")
        return real(self, *args)

    monkeypatch.setattr(reparse_module.Reparser, "_rewrite", cut)
    res = lab["admin"].post(f"/api/sources/{SOURCE}/reparse", headers=lab["h"])
    assert res.status_code == 202, res.text
    lab["app"].state.reparse.join(SOURCE)
    monkeypatch.undo()
    job = lab["admin"].get(f"/api/sources/{SOURCE}/reparse").json()["job"]
    assert job["state"] == "failed", job
    assert (job["rows_rewritten"], job["files_rewritten"]) == (2, 1)
    job_id: str = job["job_id"]
    return job_id


def recorded(lab: dict[str, Any], job_id: str) -> list[str]:
    with db(lab) as con:
        return [
            i
            for r in con.execute(
                "SELECT event_ids FROM reparse_job_events WHERE job_id = ? ORDER BY seq",
                (job_id,),
            )
            for i in json.loads(r["event_ids"])
        ]


def reparse_audits(lab: dict[str, Any], job_id: str) -> dict[str, Any]:
    rows = lab["aud"].get("/api/audit/events", params={"action": "source.reparse"}).json()
    return {r["detail"]["step"]: r["detail"] for r in rows if r["detail"]["job_id"] == job_id}


@pytest.mark.parametrize("ended", ["failed", "interrupted"])
def test_the_next_reparse_takes_over_the_rows_a_stopped_one_rewrote(
    base: dict[str, Any], monkeypatch: pytest.MonkeyPatch, ended: str
) -> None:
    """A stopped reparse can never offer the rule re-run (it is not done), and the next one
    skips the rows it rewrote. The next one takes over their ids and widens its range to
    them, so its rule re-run finds the rows of both files, once."""
    admin, h = base["admin"], base["h"]
    outage(base, [pw("08:00:01", 5001), pw("08:00:02", 5002)])
    append(base, [pw("09:00:01", 5005), pw("09:00:02", 5006)])  # a second file
    restore(base)
    first = stop_after_one_file(base, monkeypatch)
    if ended == "interrupted":  # a restart, not an exception, ended it
        with db(base) as con:
            con.execute("UPDATE reparse_jobs SET state = 'interrupted' WHERE job_id = ?", (first,))
    carried = recorded(base, first)
    assert len(carried) == 2

    job_id = reparse(base)
    shown = last(base, admin)
    assert shown["job_id"] == job_id
    assert shown["rows_rewritten"] == 2  # its own file
    assert shown["time_min"].startswith("2026-10-10T08:00:01")  # covers both files
    assert shown["time_max"].startswith("2026-10-10T09:00:02")
    mine = recorded(base, job_id)
    assert len(mine) == 4 and len(set(mine)) == 4 and set(carried) <= set(mine)
    assert recorded(base, first) == []
    start = reparse_audits(base, job_id)["start"]
    assert start["carried_from"] == [first] and start["carried_events"] == 2

    assert run_rules(base, job_id).status_code == 202
    shown = last(base, admin)
    assert (shown["rules_state"], shown["rules_matched"], shown["rules_items"]) == ("done", 4, 1)
    times = match_times(base)
    assert len(times) == 4, times
    assert sum("08:00" in t for t in times) == 2 and sum("09:00" in t for t in times) == 2
    (item,) = rule_items(base)
    assert item["count"] == 4

    # The stopped job keeps its history and offers no rule re-run.
    old = base["app"].state.reparse.get(SOURCE, first)
    assert (old.state, old.rows_rewritten, old.files_rewritten) == (ended, 2, 1)
    assert old.rules_state is None
    assert admin.post(rules_url(first), headers=h).status_code == 409

    # A later outage and reparse carry nothing again: its re-run reads only its own rows.
    outage(base, [pw("10:00:01", 5007)])
    later = reparse(base)
    assert len(recorded(base, later)) == 1
    assert "carried_from" not in reparse_audits(base, later)["start"]
    assert run_rules(base, later).status_code == 202
    assert last(base, admin)["rules_matched"] == 1
    assert len(match_times(base)) == 5
    assert rule_items(base)[0]["count"] == 5


def test_rows_carried_through_a_second_stop_reach_the_job_that_finishes(
    base: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first job stops after one file; the second takes its rows over and stops before
    rewriting anything (its range is still the carried one); the third finishes and takes
    over all of them."""
    outage(base, [pw("08:00:01", 5001), pw("08:00:02", 5002)])
    append(base, [pw("09:00:01", 5005), pw("09:00:02", 5006)])
    restore(base)
    first = stop_after_one_file(base, monkeypatch)

    def cut(*_: Any, **__: Any) -> Any:
        raise RuntimeError("power cut")

    monkeypatch.setattr(reparse_module.Reparser, "run", cut)
    assert (
        base["admin"].post(f"/api/sources/{SOURCE}/reparse", headers=base["h"]).status_code == 202
    )
    base["app"].state.reparse.join(SOURCE)
    monkeypatch.undo()
    second = last(base, base["admin"])
    assert second["state"] == "failed" and second["rows_rewritten"] == 0
    assert second["time_min"] is not None and second["time_max"] is not None
    assert len(recorded(base, second["job_id"])) == 2 and recorded(base, first) == []
    end = reparse_audits(base, second["job_id"])["end"]
    assert end["time_min"] == second["time_min"]

    job_id = reparse(base)
    assert len(recorded(base, job_id)) == 4
    assert recorded(base, second["job_id"]) == []
    assert reparse_audits(base, job_id)["start"]["carried_from"] == [second["job_id"]]
    assert run_rules(base, job_id).status_code == 202
    assert last(base, base["admin"])["rules_matched"] == 4
    assert len(match_times(base)) == 4


def test_a_done_job_or_one_whose_rules_ran_is_not_taken_over(
    base: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only stopped jobs whose rules never ran give up their rows: a done job keeps its own
    rule re-run."""
    outage(base, [pw("08:00:01", 5001)])
    done = reparse(base)
    outage(base, [pw("09:00:01", 5005)])
    later = reparse(base)
    assert len(recorded(base, done)) == 1 and len(recorded(base, later)) == 1
    assert "carried_from" not in reparse_audits(base, later)["start"]
