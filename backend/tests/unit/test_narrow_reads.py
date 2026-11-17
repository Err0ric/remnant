"""Two narrowed reads give exactly the answers of the wide reads they replace (findings
2026-11, fixes A and C): the Dashboard's lookup of matched events reads only the matched
sources from the first match on, and Agents reads only sources whose files can hold its
templates. Each is compared with the old wide read on a lake where a difference would show:
rows in other sources and on other days, matches at the window's edges, test records, and a
source the caller may not see."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.ai import agents as agents_mod
from app.ai.test_records import HOOKS
from app.core.schema import COLUMN_NAMES
from app.engine.duckdb import QueryEngine, QueryScope
from app.engine.narrow import pinned_templates
from app.ingest.writer import LakeWriter
from app.search import dashboard as dash

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


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


# --- A: the Dashboard's involved lookup ---------------------------------------------------


@pytest.fixture
def detections_lake(tmp_path: Path) -> tuple[QueryEngine, list[dict[str, Any]]]:
    start, before, _ = dash.bounds("7d", NOW, "UTC")
    rows = []
    for d in range(14):  # every day of the window and the window before, three sources
        for src in ("linux_sshd", "win_auth", "fw", "quiet"):  # "quiet" never matches
            at = before + timedelta(days=d, hours=3)
            rows.append(row(src, src, at, actor_user_name=f"u{d}", device_hostname=f"h{d}"))
    rows += [
        # matched at the window's very start and at its very end (now)
        row("linux_sshd", "linux_sshd", start, actor_user_name="alice", device_hostname="a1"),
        row("win_auth", "win_auth", NOW, actor_user_name="bob", device_hostname="b1"),
        # observed late: filed and filtered by its own time
        row("fw", "fw", start + timedelta(hours=1), time_observed=NOW, actor_user_name="carol"),
        # no time of its own: its observed time counts
        row("fw", "fw", NOW - timedelta(days=1), time=None, actor_user_name="dave"),
        # in a source the caller may not see
        row("hidden", "hidden", NOW - timedelta(hours=2), actor_user_name="mallory"),
    ]
    LakeWriter(tmp_path / "lake").write(rows)
    return QueryEngine(tmp_path / "lake"), rows


def as_match(r: dict[str, Any]) -> tuple[str, str, str, datetime, str, str]:
    """A `_matches` row: the recorded time is the text a rule run stores."""
    ts = r["time"] or r["time_observed"]
    return ("rule", "high", r["event_id"], dash._utc(datetime.fromisoformat(str(ts))), r["source_id"], "sha")  # type: ignore[return-value]  # _utc of a datetime is one  # fmt: skip


def test_the_involved_lookup_is_the_wide_one(
    detections_lake: tuple[QueryEngine, list[dict[str, Any]]],
) -> None:
    engine, rows = detections_lake
    start, before, _ = dash.bounds("7d", NOW, "UTC")
    run = dash._Run(engine, QueryScope(sources=None, start=before, end=NOW), {"start": start})
    readable = ["linux_sshd", "win_auth", "fw", "quiet"]  # not "hidden"
    # Matches in the window: edges, late, untimed, hidden, and some of every day's rows
    # of the three matched sources, the first of them a day and three hours into the window.
    now = [as_match(r) for r in rows[-5:-3] + rows[-1:]]
    now += [
        as_match(r)
        for r in rows[:-5]
        if r["source_id"] != "quiet"
        and r["time"] >= start + timedelta(days=1)
        and r["time"].day % 2
    ]
    late = [as_match(r) for r in rows[-3:-1]]  # the late-observed and the untimed event
    ids = sorted({m[2] for m in now + late})
    wide = run(dash.INVOLVED_SQL, readable, ids=ids)
    # A run of its own, so the sources and the start it reads are the narrow lookup's alone.
    run = dash._Run(engine, QueryScope(sources=None, start=before, end=NOW), {"start": start})
    asked: list[tuple[list[str], datetime]] = []
    since = run.since

    def spy(sql: str, sources: list[str], at: datetime, **extra: Any) -> list[list[Any]]:
        asked.append((sources, at))
        return since(sql, sources, at, **extra)

    run.since = spy  # type: ignore[method-assign]  # records what the lookup asks for
    narrow = dash.involved_events(run, readable, now + late, start)
    assert sorted(map(tuple, narrow)) == sorted(map(tuple, wide))
    found = {r[0] for r in narrow}
    assert len(found) == len(ids) - 1  # every match but the hidden one
    hidden = rows[-1]["event_id"]
    assert hidden not in found
    # The narrow read opened only the matched sources, from a second before the first match:
    # a readable source with no match is not read, and the wide read fails both lines.
    assert run.read == {"linux_sshd", "win_auth", "fw"}
    first = min(m[3] for m in now + late)
    assert asked == [(["linux_sshd", "win_auth", "fw"], first - timedelta(seconds=1))]
    assert first == start  # the match at the window's very start sets it


def test_no_match_reads_nothing(
    detections_lake: tuple[QueryEngine, list[dict[str, Any]]],
) -> None:
    engine, _ = detections_lake
    start, before, _ = dash.bounds("7d", NOW, "UTC")
    run = dash._Run(engine, QueryScope(sources=None, start=before, end=NOW), {"start": start})
    assert dash.involved_events(run, ["fw"], [], start) == []
    assert run.read == set()


# --- C: Agents ------------------------------------------------------------------------------

# The two queries as they were before they pinned their templates.
OLD_ITEMS = agents_mod.ITEMS_SQL.replace(
    "FROM events WHERE template_id = 'claude_hooks' AND " + HOOKS[len("(template_id = 'claude_hooks' AND ") : -1],
    f"FROM events WHERE {HOOKS}",
)  # fmt: skip
OLD_HOURLY = f"""
WITH u AS (
  SELECT CASE template_id
           WHEN 'claude_code_otel' THEN 'cc|'
             || coalesce(nullif(actor_user_name, ''), device_hostname, '?')
           WHEN 'claude_hooks' THEN 'cc|'
             || coalesce(nullif(actor_user_name, ''), device_hostname, '?')
           WHEN 'anthropic_reports' THEN 'key|' || json_extract_string(unmapped, '$.api_key_id')
         END AS agent, date_trunc('hour', coalesce(time, time_observed)) AS h
  FROM events
  WHERE template_id = 'claude_code_otel' OR {HOOKS}
     OR (template_id = 'anthropic_reports' AND message = 'anthropic.usage')
)
SELECT agent,
       max(n) FILTER (WHERE h < $recent) AS usual,
       max(n) FILTER (WHERE h >= $recent) AS peak
FROM (SELECT agent, h, count(*) AS n FROM u WHERE agent IS NOT NULL GROUP BY 1, 2)
GROUP BY 1
LIMIT 2000"""  # fixed SQL text


def test_the_old_queries_and_the_new_ones_are_narrowed_alike() -> None:
    """The old shapes pin their templates inside an OR of parenthesized ANDs, which is now
    read too (S7, fix list 2026-11-16), so both narrow to the same templates."""
    assert OLD_ITEMS != agents_mod.ITEMS_SQL
    want = {"claude_code_otel", "claude_hooks", "mcp_inventory", "anthropic_reports"}
    assert pinned_templates(OLD_ITEMS, {"recent": NOW}) == want
    assert pinned_templates(OLD_HOURLY, {"recent": NOW}) == want - {"mcp_inventory"}
    assert pinned_templates(agents_mod.ITEMS_SQL, {"recent": NOW}) == want
    assert pinned_templates(agents_mod.HOURLY_SQL, {"recent": NOW}) == want - {"mcp_inventory"}


def hook(source: str, at: datetime, who: str | None, host: str | None, **attr: Any) -> dict[str, Any]:  # fmt: skip
    body = {"attr": {"tool_name": "Bash", **attr}}
    return row(
        source, "claude_hooks", at, actor_user_name=who, device_hostname=host,
        message="claude_hooks.pre_tool_use", unmapped=json.dumps(body),
    )  # fmt: skip


@pytest.fixture
def agents_lake(tmp_path: Path) -> QueryEngine:
    rows = []
    for h in range(0, 24 * 35, 5):  # 35 days, past the 30-day baseline on both ends
        at = NOW - timedelta(hours=h)
        rows.append(row("win_dns", "dns_windows", at))  # never an agent's
        # A custom source that received hooks records: found by its files, not its name.
        rows.append(hook("custom_upload", at, "alice@example.com", "ws-0001"))
        rows.append(hook("claude", at, "bob@example.com", "ws-0002", mcp_server_name="github"))
        otel = {"attr": {"tool_name": "Read", "model": "claude-sonnet-5-5"}}
        rows.append(row("claude", "claude_code_otel", at, actor_user_name="carol@example.com",
                        device_hostname="ws-0003", unmapped=json.dumps(otel)))  # fmt: skip
        if h % 15 == 0:
            rows.append(row("inv", "mcp_inventory", at, device_hostname="ws-0004",
                            message="filesystem", unmapped=json.dumps({"client": "Cursor"})))  # fmt: skip
            rows.append(row("reports", "anthropic_reports", at, message="anthropic.usage",
                            unmapped=json.dumps({"api_key_id": "k1", "model": "m"})))  # fmt: skip
        # A mixed source: mostly not an agent's, a few hooks records among them.
        rows.append(row("mixed", "linux_sshd", at))
    rows.append(hook("mixed", NOW - timedelta(hours=1), "dave@example.com", "ws-0005"))
    # A burst in the last hour, so the hourly spike counts are compared too.
    rows += [hook("claude", NOW - timedelta(minutes=m), "bob@example.com", "ws-0002") for m in range(40)]  # fmt: skip
    # A test record (no person, no machine): left out by both.
    rows.append(hook("claude", NOW - timedelta(hours=2), None, None, test_record="true"))
    # A source the caller may not see.
    rows.append(hook("hidden", NOW - timedelta(hours=3), "mallory@example.com", "ws-0666"))
    LakeWriter(tmp_path / "lake").write(rows)
    return QueryEngine(tmp_path / "lake")


def answers(engine: QueryEngine, allowed: list[str] | None) -> list[Any]:
    return [vars(a) if hasattr(a, "__dict__") else {k: getattr(a, k) for k in a.__slots__} for a in agents_mod.agents(engine, allowed, NOW)]  # fmt: skip


@pytest.mark.parametrize(
    "allowed", [None, ["win_dns", "custom_upload", "claude", "inv", "reports", "mixed"], ["claude"]]
)
def test_agents_are_the_wide_answer(
    agents_lake: QueryEngine, monkeypatch: pytest.MonkeyPatch, allowed: list[str] | None
) -> None:
    narrow = answers(agents_lake, allowed)
    monkeypatch.setattr(agents_mod, "ITEMS_SQL", OLD_ITEMS)
    monkeypatch.setattr(agents_mod, "HOURLY_SQL", OLD_HOURLY)
    wide = answers(agents_lake, allowed)
    assert narrow == wide
    names = {a["agent"] for a in narrow}
    assert ("cc|mallory@example.com" in names) is (allowed is None)
    if allowed != ["claude"]:
        assert {"cc|alice@example.com", "cc|dave@example.com", "key|k1"} <= names


def test_agents_read_only_sources_that_can_hold_their_records(agents_lake: QueryEngine) -> None:
    scope = QueryScope(None, NOW - timedelta(days=30), NOW)
    read = set(agents_lake.run(agents_mod.ITEMS_SQL, scope, {"recent": NOW}).sources)
    assert read == {"custom_upload", "claude", "inv", "reports", "mixed", "hidden"}
    hourly = set(agents_lake.run(agents_mod.HOURLY_SQL, scope, {"recent": NOW}).sources)
    assert "win_dns" not in hourly and {"custom_upload", "mixed"} <= hourly
