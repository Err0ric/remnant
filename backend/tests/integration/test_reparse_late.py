"""A rule re-run over reparsed events notifies (D241): one grouped "Late detection from
reparse" message per run to each target of the enabled schedules that run a matched rule,
with the rules, their match counts, and the event time range; its alert items are marked
late. Also the two narrow gaps of the carry-over: ids are recorded before a file is
published, and a stopped job that rewrote the last rows offers the rule re-run itself."""

import json
from collections.abc import Iterator
from typing import Any

import pytest

from app.alerts.render import Alert, slack_payload
from app.core.errors import RuleRejectedError
from app.detect import runner as runner_module
from app.ingest import reparse as reparse_module
from tests.integration.test_reparse_rules import (
    NEW,
    OTHER,
    RULE,
    RULE_ID,
    SOURCE,
    append,
    base,
    db,
    lab,
    last,
    match_times,
    outage,
    pw,
    recorded,
    reparse,
    restore,
    rule_items,
    rules_url,
    run_rules,
)
from tests.integration.test_schedules import schedule

__all__ = ["base", "lab"]  # the fixtures, used by name

RULE2_ID = "66666666-6666-4666-8666-666666666666"
RULE2 = RULE.replace(RULE_ID, RULE2_ID).replace("SSH password method", "SSH password second")
RULE3_ID = "77777777-7777-4777-8777-777777777777"
RULE3 = RULE.replace(RULE_ID, RULE3_ID).replace("SSH password method", "SSH password third")


def add_rule(lab: dict[str, Any], rule_id: str, text: str) -> None:
    admin, h = lab["admin"], lab["h"]
    (lab["rules"] / f"{rule_id}.yml").write_text(text)
    admin.post("/api/rules/import", json={"path": str(lab["rules"])}, headers=h)
    res = admin.post("/api/rules/enabled", json={"rule_ids": [rule_id], "enabled": True}, headers=h)
    assert res.status_code == 200, res.text


def target(lab: dict[str, Any], name: str) -> str:
    res = lab["admin"].post(
        "/api/alert-targets",
        json={"name": name, "kind": "webhook", "url": f"http://127.0.0.1:9/{name}"},
        headers=lab["h"],
    )
    assert res.status_code == 201, res.text
    tid: str = res.json()["target_id"]
    return tid


def rule_schedule(
    lab: dict[str, Any],
    rule_id: str,
    targets: list[str],
    paused: bool = False,
    owner: str = "admin",
    **body: Any,
) -> str:
    client = lab[owner]
    h = lab["h"] if owner == "admin" else None
    res = schedule(client, h, kind="rule", target_id=rule_id, target_ids=targets, **body)
    assert res.status_code == 201, res.text
    sid: str = res.json()["schedule_id"]
    if paused:
        res = lab["admin"].patch(f"/api/schedules/{sid}", json={"paused": True}, headers=lab["h"])
        assert res.status_code == 200, res.text
    return sid


def late_sent(lab: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """(target, alert) for each late-detection delivery, oldest first."""
    with db(lab) as con:
        rows = con.execute(
            "SELECT target_id, alert, source_id FROM alert_deliveries ORDER BY created_at, rowid"
        ).fetchall()
    out = []
    for r in rows:
        alert = json.loads(r["alert"])
        if alert["kind"] == "late_detection":
            assert r["source_id"] == SOURCE
            out.append((r["target_id"], alert))
    return out


@pytest.fixture
def two_rules(lab: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """RULE and RULE2 both match lin_auth's 2 reparsed password lines. Targets: one hears
    RULE, one hears both, one is on a paused RULE2 schedule, one on a saved search."""
    add_rule(lab, RULE2_ID, RULE2)
    lab["t_one"], lab["t_both"] = target(lab, "one"), target(lab, "both")
    lab["t_paused"], lab["t_search"] = target(lab, "paused"), target(lab, "search")
    rule_schedule(lab, RULE_ID, [lab["t_one"], lab["t_both"]])
    rule_schedule(lab, RULE2_ID, [lab["t_both"]])
    rule_schedule(lab, RULE2_ID, [lab["t_paused"]], paused=True)
    res = schedule(lab["admin"], lab["h"], target_ids=[lab["t_search"]])  # a saved search
    assert res.status_code == 201, res.text
    yield lab


def test_each_target_gets_one_late_message_with_the_rules_it_hears_about(
    two_rules: dict[str, Any],
) -> None:
    lab = two_rules
    job_id = reparse(lab)
    shown = last(lab, lab["admin"])
    assert run_rules(lab, job_id).status_code == 202
    shown = last(lab, lab["admin"])
    assert (shown["rules_state"], shown["rules_matched"]) == ("done", 4)

    sent = late_sent(lab)
    assert sorted(t for t, _ in sent) == sorted([lab["t_one"], lab["t_both"]])
    by = dict(sent)
    one, both = by[lab["t_one"]], by[lab["t_both"]]
    for alert in (one, both):
        assert alert["range_start"] == shown["time_min"]
        assert alert["range_end"] == shown["time_max"]
        assert "lin_auth" in alert["title"]
        assert alert["link"].endswith("/alerts")
    assert one["count"] == 2 and "SSH password method (2 matches)" in one["detail"]
    assert "SSH password second" not in one["detail"]
    assert both["count"] == 4
    assert "SSH password method (2 matches)" in both["detail"]
    assert "SSH password second (2 matches)" in both["detail"]
    text = json.dumps(slack_payload(Alert(**one)))
    assert "Late detection from reparse" in text and "2 matches" in text
    assert f"Range: {shown['time_min']} to {shown['time_max']}" in text

    # The items are late, with the event time range, on the list and the item's page.
    items = rule_items(lab)
    assert len(items) == 1 and items[0]["late"] == 1
    assert (items[0]["late_start"], items[0]["late_end"]) == (shown["time_min"], shown["time_max"])
    listed = lab["admin"].get("/api/alerts").json()["items"]
    late = [i for i in listed if i["subject"] in (RULE_ID, RULE2_ID)]
    assert len(late) == 2 and all(i["late"] for i in late)
    one_item = lab["admin"].get(f"/api/alerts/{late[0]['item_id']}").json()
    assert (one_item["late"], one_item["late_start"], one_item["late_end"]) == (
        True,
        shown["time_min"],
        shown["time_max"],
    )

    end = next(
        r
        for r in lab["aud"]
        .get("/api/audit/events", params={"action": "source.reparse_rules"})
        .json()
        if r["detail"]["step"] == "end"
    )
    assert end["detail"]["notified"] == {"targets": 2, "rules": 2}


def test_no_message_for_a_rule_without_a_schedule_or_with_no_matches(
    lab: dict[str, Any],
) -> None:
    """RULE matches but runs on no schedule: its item is raised (late) and nothing is sent.
    RULE3 has a schedule with a target but matches nothing here."""
    add_rule(lab, RULE3_ID, RULE3.replace("method: password", "method: publickey"))
    rule_schedule(lab, RULE3_ID, [target(lab, "quiet")])
    job_id = reparse(lab)
    assert run_rules(lab, job_id).status_code == 202
    shown = last(lab, lab["admin"])
    assert (shown["rules_state"], shown["rules_count"], shown["rules_matched"]) == ("done", 2, 2)
    assert late_sent(lab) == []
    (item,) = rule_items(lab)
    assert item["late"] == 1


def test_no_message_when_nothing_matched(base: dict[str, Any]) -> None:
    rule_schedule(base, RULE_ID, [target(base, "quiet")])
    outage(base, [NEW[2]])  # a closed connection: no password method
    job_id = reparse(base)
    assert run_rules(base, job_id).status_code == 202
    assert last(base, base["admin"])["rules_matched"] == 0
    assert late_sent(base) == []


# The stop in step 2 ends the run's thread, as a restart would.
@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_restart_never_sends_the_message_twice(
    two_rules: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    lab = two_rules
    job_id = reparse(lab)
    reruns = lab["app"].state.reparse_rules
    dispatcher = lab["app"].state.alert_dispatcher
    real_enqueue = dispatcher.enqueue
    calls: list[int] = []

    # 1. A stop inside the message's transaction: nothing is queued, nothing marked sent.
    def crash_second(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("power cut")
        return real_enqueue(*args, **kwargs)

    monkeypatch.setattr(dispatcher, "enqueue", crash_second)
    assert run_rules(lab, job_id).status_code == 202
    assert last(lab, lab["admin"])["rules_state"] == "failed"
    assert late_sent(lab) == []  # the first target's message rolled back with it
    monkeypatch.undo()

    # 2. A stop after the messages are queued, before the run is marked done (a restart).
    real_end = reruns._end

    def stop(*_: Any, **__: Any) -> None:
        raise SystemExit  # not caught by the run: rules_state stays running

    monkeypatch.setattr(reruns, "_end", stop)
    assert run_rules(lab, job_id).status_code == 202
    monkeypatch.setattr(reruns, "_end", real_end)
    assert len(late_sent(lab)) == 2
    assert reruns.interrupt_left_running() == 1

    # 3. Started again: every rule is done and announced; nothing more is sent.
    assert run_rules(lab, job_id).status_code == 202
    assert last(lab, lab["admin"])["rules_state"] == "done"
    assert len(late_sent(lab)) == 2


def test_a_retry_after_a_partial_run_sends_only_the_rules_that_matched_in_it(
    two_rules: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    lab = two_rules
    job_id = reparse(lab)
    real = runner_module.compile_rule

    def refuse(data: bytes) -> Any:
        if RULE2_ID.encode() in data:
            raise RuleRejectedError("this rule cannot be compiled now")
        return real(data)

    monkeypatch.setattr(runner_module, "compile_rule", refuse)
    assert run_rules(lab, job_id).status_code == 202
    assert last(lab, lab["admin"])["rules_state"] == "partial"
    first = late_sent(lab)
    assert sorted(t for t, _ in first) == sorted([lab["t_one"], lab["t_both"]])
    assert all("SSH password second" not in a["detail"] for _, a in first)
    monkeypatch.undo()

    assert run_rules(lab, job_id).status_code == 202
    assert last(lab, lab["admin"])["rules_state"] == "done"
    retry = late_sent(lab)[len(first) :]
    assert [t for t, _ in retry] == [lab["t_both"]]
    assert "SSH password second (2 matches)" in retry[0][1]["detail"]
    assert "SSH password method" not in retry[0][1]["detail"]
    assert retry[0][1]["count"] == 2


def test_an_open_item_that_grows_from_a_late_run_is_marked_late(lab: dict[str, Any]) -> None:
    open_item = lab["app"].state.alert_items.raise_item(
        "rule", RULE_ID, "SSH password method", ref_id="earlier-run", count=3,
        sources=["lin_two"], group=(RULE_ID, "rule"),
    )  # fmt: skip
    assert not open_item.late
    job_id = reparse(lab)
    assert run_rules(lab, job_id).status_code == 202
    (item,) = rule_items(lab)
    shown = last(lab, lab["admin"])
    assert item["item_id"] == open_item.item_id and item["count"] == 5
    assert (item["late"], item["late_start"], item["late_end"]) == (
        1,
        shown["time_min"],
        shown["time_max"],
    )


# --- who hears: as a scheduled run of each schedule would alert (review of D241) ------------


def heard_of_the_rule(lab: dict[str, Any], tid: str) -> list[str]:
    """Every message queued for a target, of any kind, that is late or names the rule.
    (Source health messages such as "template loads again" go to every target.)"""
    with db(lab) as con:
        rows = con.execute(
            "SELECT alert FROM alert_deliveries WHERE target_id = ?", (tid,)
        ).fetchall()
    return [
        str(r["alert"])
        for r in rows
        if json.loads(r["alert"])["kind"] == "late_detection" or "SSH password method" in r["alert"]
    ]


def test_a_schedule_whose_owner_cannot_read_the_source_hears_nothing(lab: dict[str, Any]) -> None:
    """ana's group reads lin_two only, so a scheduled run of her RULE schedule could never
    alert on lin_auth: her target hears nothing, while an admin's schedule of the same rule
    does (CLAUDE.md rule 13)."""
    lab["admin"].put(
        f"/api/groups/{lab['gid']}/sources", json={"source_ids": [OTHER]}, headers=lab["h"]
    )
    t_ana, t_admin = target(lab, "ana"), target(lab, "admin")
    rule_schedule(lab, RULE_ID, [t_ana], owner="ana")
    rule_schedule(lab, RULE_ID, [t_admin])
    job_id = reparse(lab)
    assert run_rules(lab, job_id).status_code == 202
    assert last(lab, lab["admin"])["rules_matched"] == 2
    assert [t for t, _ in late_sent(lab)] == [t_admin]
    assert heard_of_the_rule(lab, t_ana) == []  # none of the message reaches her target


def test_a_schedule_whose_owner_lost_the_source_hears_nothing(lab: dict[str, Any]) -> None:
    """A scheduled run would pause it (the owner lost a source it read), not alert."""
    t_ana = target(lab, "ana")
    rule_schedule(lab, RULE_ID, [t_ana], owner="ana")  # ana reads lin_auth now
    lab["admin"].put(
        f"/api/groups/{lab['gid']}/sources", json={"source_ids": [OTHER]}, headers=lab["h"]
    )
    job_id = reparse(lab)
    assert run_rules(lab, job_id).status_code == 202
    assert heard_of_the_rule(lab, t_ana) == []


def test_a_permitted_analysts_schedule_hears(lab: dict[str, Any]) -> None:
    t_ana = target(lab, "ana")
    rule_schedule(lab, RULE_ID, [t_ana], owner="ana")  # ana's group reads lin_auth
    job_id = reparse(lab)
    assert run_rules(lab, job_id).status_code == 202
    ((tid, alert),) = late_sent(lab)
    assert tid == t_ana and "SSH password method (2 matches)" in alert["detail"]


@pytest.mark.parametrize(
    ("kind", "value", "hears"),
    [
        ("above", 5, False),
        ("above", 1, True),
        ("below", 5, True),
        ("below", 1, False),
        # A change against the last run's window cannot be judged for a late run: told.
        ("change_pct", 50, True),
    ],
)
def test_a_schedule_threshold_applies_as_on_a_scheduled_run(
    lab: dict[str, Any], kind: str, value: float, hears: bool
) -> None:
    """A rule schedule with a threshold alerts only when the run's count meets it, so its
    targets hear of the 2 late matches only then."""
    tid = target(lab, "thr")
    rule_schedule(lab, RULE_ID, [tid], threshold_kind=kind, threshold_value=value)
    job_id = reparse(lab)
    assert run_rules(lab, job_id).status_code == 202
    assert last(lab, lab["admin"])["rules_matched"] == 2
    assert [t for t, _ in late_sent(lab)] == ([tid] if hears else [])


def test_a_muted_rule_sends_no_late_message_and_its_item_closes_as_muted(
    two_rules: dict[str, Any],
) -> None:
    """As on a scheduled run: the item is written and closed at once as muted (marked late),
    and nothing is sent for the rule. RULE2, not muted, is still announced."""
    lab = two_rules
    earlier = lab["app"].state.alert_items.raise_item(
        "rule", RULE_ID, "SSH password method", ref_id="earlier-run", count=1,
        group=(RULE_ID, "rule"),
    )  # fmt: skip
    h = lab["h"]
    res = lab["admin"].post(f"/api/alerts/{earlier.item_id}/mute", json={"days": 7}, headers=h)
    assert res.status_code == 200, res.text
    res = lab["admin"].post(
        f"/api/alerts/{earlier.item_id}/close", json={"reason": "expected"}, headers=h
    )
    assert res.status_code == 200, res.text
    job_id = reparse(lab)
    assert run_rules(lab, job_id).status_code == 202
    assert last(lab, lab["admin"])["rules_matched"] == 4

    sent = late_sent(lab)
    assert [t for t, _ in sent] == [lab["t_both"]]  # t_one hears RULE only
    assert "SSH password second (2 matches)" in sent[0][1]["detail"]
    assert "SSH password method" not in sent[0][1]["detail"]
    new = [i for i in rule_items(lab) if i["item_id"] != earlier.item_id]
    assert len(new) == 1
    assert (new[0]["state"], new[0]["close_reason"], new[0]["late"]) == ("closed", "muted", 1)


# --- the two gaps of the carry-over ---------------------------------------------------------


def two_files(base: dict[str, Any]) -> None:
    """Two lake files of lin_auth stored without the template, the template back."""
    outage(base, [pw("08:00:01", 5001), pw("08:00:02", 5002)])
    append(base, [pw("09:00:01", 5005), pw("09:00:02", 5006)])
    restore(base)


def stopped_reparse(base: dict[str, Any], monkeypatch: pytest.MonkeyPatch, when: str) -> str:
    """A reparse that stops on its first file: `after` the file is published (before the
    job records anything more), or `before` it is published."""
    real = reparse_module.publish

    def cut(*args: Any, **kwargs: Any) -> Any:
        if when == "after":
            real(*args, **kwargs)
        raise RuntimeError("power cut")

    monkeypatch.setattr(reparse_module, "publish", cut)
    res = base["admin"].post(f"/api/sources/{SOURCE}/reparse", headers=base["h"])
    assert res.status_code == 202, res.text
    base["app"].state.reparse.join(SOURCE)
    monkeypatch.undo()
    job = base["admin"].get(f"/api/sources/{SOURCE}/reparse").json()["job"]
    assert job["state"] == "failed", job
    job_id: str = job["job_id"]
    return job_id


@pytest.mark.parametrize("when", ["after", "before"])
def test_ids_are_recorded_before_the_file_is_published(
    base: dict[str, Any], monkeypatch: pytest.MonkeyPatch, when: str
) -> None:
    """A stop right after a publish loses no ids (they were recorded first, with their
    range); a stop before it leaves the rows template_missing, and the next reparse rewrites
    them with the same ids, which are counted once."""
    two_files(base)
    first = stopped_reparse(base, monkeypatch, when)
    ids = recorded(base, first)
    assert len(ids) == 2
    old = base["app"].state.reparse.get(SOURCE, first)
    assert old.time_min is not None and old.time_min.startswith("2026-10-10T08:00:01")

    job_id = reparse(base)
    mine = recorded(base, job_id)
    assert len(mine) == 4 and len(set(mine)) == 4 and set(ids) <= set(mine)
    shown = last(base, base["admin"])
    assert shown["time_min"].startswith("2026-10-10T08:00:01")
    assert run_rules(base, job_id).status_code == 202
    assert last(base, base["admin"])["rules_matched"] == 4
    times = match_times(base)
    assert len(times) == 4 and len(set(times)) == 4, times


def test_a_stopped_job_that_rewrote_the_last_rows_offers_the_rule_re_run(
    base: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its rows are rewritten and none are left to reparse, so no later job would take its
    ids over until the next outage: its own rule re-run starts instead."""
    outage(base, [pw("08:00:01", 5001), pw("08:00:02", 5002)])
    restore(base)
    first = stopped_reparse(base, monkeypatch, "after")
    again = base["admin"].post(f"/api/sources/{SOURCE}/reparse", headers=base["h"])
    assert again.status_code == 409  # nothing is waiting to be reparsed
    shown = last(base, base["admin"])
    assert (shown["job_id"], shown["state"], shown["rules_ready"]) == (first, "failed", True)

    assert run_rules(base, first).status_code == 202
    shown = last(base, base["admin"])
    assert (shown["rules_state"], shown["rules_matched"], shown["rules_items"]) == ("done", 2, 1)
    assert shown["rules_ready"] is True  # its result stays shown
    (item,) = rule_items(base)
    assert item["late"] == 1 and item["count"] == 2


def test_a_stopped_job_with_rows_still_to_reparse_waits_for_the_next_reparse(
    base: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The source list offers the re-run from metadata only and never reads the lake for
    it; the start checks the lake and refuses while rows remain, saying how many."""
    two_files(base)
    first = stopped_reparse(base, monkeypatch, "after")
    jobs = base["app"].state.reparse

    def no_lake(*_: Any, **__: Any) -> int:
        raise AssertionError("the source list read the lake")

    monkeypatch.setattr(jobs, "left", no_lake)
    monkeypatch.setattr(reparse_module, "pending", no_lake)
    shown = last(base, base["admin"])
    assert (shown["job_id"], shown["state"], shown["rules_ready"]) == (first, "failed", True)
    monkeypatch.undo()

    res = base["admin"].post(rules_url(first), headers=base["h"])
    assert res.status_code == 409
    assert res.json()["detail"].startswith("Reparse the remaining 2 events first")
    assert last(base, base["admin"])["rules_state"] is None  # nothing started
    job_id = reparse(base)  # takes its ids over
    assert last(base, base["admin"])["rules_ready"] is True
    assert len(recorded(base, job_id)) == 4
