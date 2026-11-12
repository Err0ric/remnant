"""Reparse a source's template_missing rows once its template loads again (ADR-0050 rows 7
and 8): same event_id, raw, and time; only that source's template_missing rows change; a
crash leaves either the old rows or the new ones; the ledger records it; admin only."""

import asyncio
import json
import socket
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from app.core import lake_files
from app.core.config import load_config
from app.engine.duckdb import QueryEngine, QueryScope
from app.ingest import reparse
from app.ingest.compaction import Compactor
from app.ingest.integrity import IntegrityLedger
from app.ingest.normalizer import SourceSpec, TemplateMissingNormalizer
from app.ingest.records import DecodedLine
from app.ingest.writer import LakeWriter
from app.main import create_app
from app.meta.db import MetaDB
from app.templates.registry import STARTER_DIR, TemplateRegistry
from app.templates.runtime import TemplateNormalizer
from tests.integration.test_integrity import age
from tests.integration.test_schedules import NOW, make_lab
from tests.integration.test_syslog_listener import free_port, listeners

FIXTURE = Path(__file__).parent.parent / "fixtures" / "logs" / "linux_sshd" / "sample.log"
LINES = FIXTURE.read_text().splitlines()
TODAY = NOW.date()


# --- lake level ---------------------------------------------------------------------------


def missing_rows(source_id: str, lines: list[str], at: datetime = NOW) -> list[dict[str, Any]]:
    norm = TemplateMissingNormalizer(
        SourceSpec(source_id=source_id, format="syslog"), "linux_sshd", clock=lambda: at
    )
    out = []
    for line in lines:
        row = norm.normalize(DecodedLine(text=line, bytes_invalid=False, truncated=False))
        assert row is not None
        out.append(row)
    return out


@pytest.fixture
def lake(tmp_path: Path) -> dict[str, Any]:
    meta = MetaDB(tmp_path / "meta.sqlite")
    lake = tmp_path / "lake"
    ledger = IntegrityLedger(meta, lake)
    registry = TemplateRegistry(STARTER_DIR, tmp_path / "templates")
    template = registry.get("linux_sshd")
    assert template is not None

    def make(clock: Callable[[], datetime]) -> TemplateNormalizer:
        return TemplateNormalizer(template, "auth", clock=clock, tables=registry.tables)

    reparser = reparse.Reparser(lake, ledger, make, "linux_sshd")
    return {
        "meta": meta,
        "lake": lake,
        "ledger": ledger,
        "writer": LakeWriter(lake, ledger),
        "reparser": reparser,
        "registry": registry,
        "template": template,
    }


# Kept from the stored row by a reparse (rule 2.6 and ADR-0050 row 7): the last four columns
# of a snapshot, after the ones a reparse may change.
KEPT = ("classification", "owner_id", "time_observed", "raw_bytes_invalid")


def snapshot(lake: Path, where: str = "TRUE") -> dict[str, tuple[Any, ...]]:
    res = QueryEngine(lake).run(
        "SELECT event_id, source_id, raw, time, parse_status, template_id, message,"
        f" actor_user_name, class_uid, {', '.join(KEPT)} FROM events WHERE {where}",
        QueryScope(None),
    )
    return {r[0]: tuple(r[1:]) for r in res.rows}


def run(lab: dict[str, Any], source_id: str = "auth") -> reparse.ReparseResult:
    result: reparse.ReparseResult = lab["reparser"].run(source_id, 30, TODAY)
    return result


def test_rows_keep_event_id_raw_and_time_and_take_the_template(lake: dict[str, Any]) -> None:
    lake["writer"].write(missing_rows("auth", LINES[:20]))
    before = snapshot(lake["lake"])
    assert reparse.pending(lake["lake"], "auth", "linux_sshd", 30, TODAY) == 20
    result = run(lake)
    assert (result.rows, result.files) == (20, 1)
    after = snapshot(lake["lake"])
    assert after.keys() == before.keys()
    for eid, row in after.items():
        old = before[eid]
        assert row[1] == old[1] and row[2] == old[2]  # raw and time from ingest
        assert row[-len(KEPT) :] == old[-len(KEPT) :]  # classification, owner, observed, bytes
        assert row[3] != "template_missing" and row[4] == "linux_sshd"
    assert sum(r[7] == 3002 for r in after.values()) >= 15  # the template's class now
    assert result.time_min and result.time_max
    assert result.time_min.isoformat() == min(r[2] for r in before.values())
    assert result.time_max.isoformat() == max(r[2] for r in before.values())
    assert reparse.pending(lake["lake"], "auth", "linux_sshd", 30, TODAY) == 0


def test_the_range_and_ids_cover_rows_with_no_event_time(lake: dict[str, Any]) -> None:
    """A row with no `time` is placed by `time_observed` (as the engine reads it), so the
    reparsed range includes it; every rewritten row's event_id is reported per file."""
    timed = missing_rows("auth", LINES[:2])
    untimed = missing_rows("auth", LINES[2:4], at=NOW + timedelta(hours=2))
    for row in untimed:
        row["time"] = None
    lake["writer"].write(timed + untimed)
    seen: list[str] = []
    result = lake["reparser"].run("auth", 30, TODAY, rewriting=lambda ids, _: seen.extend(ids))
    assert result.rows == 4
    assert sorted(seen) == sorted(r["event_id"] for r in timed + untimed)
    assert result.time_min == min(r["time"] for r in timed)
    assert result.time_max == NOW + timedelta(hours=2)


class Tampering(TemplateNormalizer):
    """A parse whose kept columns differ from every stored row's: what a reparse writes
    for them must still be the stored values."""

    def normalize(self, line: DecodedLine) -> dict[str, Any]:
        row = super().normalize(line)
        row.update(
            classification="cloud_allowed",
            owner_id="mallory",
            time_observed=NOW + timedelta(days=3),
            raw_bytes_invalid=not line.bytes_invalid,
        )
        return row


def test_classification_owner_observed_time_and_byte_flag_stay_as_stored(
    lake: dict[str, Any],
) -> None:
    stored = missing_rows("auth", LINES[:6], at=NOW - timedelta(hours=2))
    for i, r in enumerate(stored):
        r.update(owner_id="grace", raw_bytes_invalid=i % 2 == 0)
    lake["writer"].write(stored)
    before = snapshot(lake["lake"])
    template, registry = lake["template"], lake["registry"]

    def make(clock: Callable[[], datetime]) -> TemplateNormalizer:
        return Tampering(template, "auth", clock=clock, tables=registry.tables)

    tamper = reparse.Reparser(lake["lake"], lake["ledger"], make, "linux_sshd")
    assert tamper.run("auth", 30, TODAY).rows == 6
    after = snapshot(lake["lake"])
    for eid, row in after.items():
        assert row[3] != "template_missing"
        assert dict(zip(KEPT, row[-len(KEPT) :], strict=True)) == dict(
            zip(KEPT, before[eid][-len(KEPT) :], strict=True)
        )


def test_loki_labels_ingest_added_stay_with_the_event(lake: dict[str, Any]) -> None:
    """Ingest adds the stream labels to a Loki row's envelope after the parser; a reparse
    keeps them, as it keeps every value ingest fills after the parser."""
    rows = missing_rows("auth", LINES[:3])
    for r in rows:
        env = json.loads(r["envelope"] or "{}")
        env["loki_labels"] = {"job": "sshd", "host": "web-01.example.internal"}
        r["envelope"] = json.dumps(env)
    lake["writer"].write(rows)
    template, registry = lake["template"], lake["registry"]

    def make(clock: Callable[[], datetime]) -> TemplateNormalizer:
        return TemplateNormalizer(template, "auth", clock=clock, tables=registry.tables)

    loki = reparse.Reparser(lake["lake"], lake["ledger"], make, "linux_sshd", kind="loki")
    assert loki.run("auth", 30, TODAY).rows == 3
    res = QueryEngine(lake["lake"]).run(
        "SELECT parse_status, envelope FROM events", QueryScope(None)
    )
    assert len(res.rows) == 3
    for status, envelope in res.rows:
        assert status != "template_missing"
        assert json.loads(envelope)["loki_labels"] == {
            "job": "sshd",
            "host": "web-01.example.internal",
        }


def test_only_that_sources_template_missing_rows_in_retention_change(
    lake: dict[str, Any],
) -> None:
    writer: LakeWriter = lake["writer"]
    mixed = missing_rows("auth", LINES[:5])
    other_template = missing_rows("auth", LINES[5:8])
    for r in other_template:
        r["template_id"] = "cisco_asa"  # marked for another template: not this job's
    writer.write(mixed + missing_rows("auth", []) + other_template)
    ok = missing_rows("auth", LINES[8:10])
    for r in ok:
        r.update(parse_status="ok", parse_errors=None, template_id="linux_sshd")
    writer.write(ok)
    writer.write(missing_rows("other", LINES[:5]))
    old = NOW - timedelta(days=45)
    writer.write(missing_rows("auth", LINES[10:12], at=old))
    other_files = sorted((lake["lake"] / "source=other").rglob("part-*.parquet"))
    other_bytes = [p.read_bytes() for p in other_files]
    before = snapshot(lake["lake"])

    result = run(lake)
    assert result.rows == 5 and result.files == 1
    after = snapshot(lake["lake"])
    assert after.keys() == before.keys()
    changed = {k for k in after if after[k] != before[k]}
    assert changed == {r["event_id"] for r in mixed}
    assert sorted((lake["lake"] / "source=other").rglob("part-*.parquet")) == other_files
    assert [p.read_bytes() for p in other_files] == other_bytes


def test_ledger_records_the_rewrite_and_verify_passes(lake: dict[str, Any]) -> None:
    lake["writer"].write(missing_rows("auth", LINES[:10]))
    run(lake)
    with lake["meta"].connect() as con:
        rows = con.execute("SELECT op, reason FROM lake_ledger ORDER BY seq").fetchall()
    assert [r[0] for r in rows] == ["add", "add"]
    assert rows[1][1].startswith("reparsed 10 rows from part-")
    age(lake["lake"])
    assert lake["ledger"].verify().status == "verified"
    # After the grace period the next maintenance pass deletes the old file.
    later = datetime.now(UTC) + timedelta(hours=1)
    report = Compactor(
        lake["lake"], today=lambda: TODAY, events=lake["ledger"], clock=lambda: later
    ).run()
    assert report.deleted == 1
    with lake["meta"].connect() as con:
        removed = con.execute("SELECT reason FROM lake_ledger WHERE op = 'remove'").fetchall()
    assert len(removed) == 1 and removed[0][0].startswith("reparsed into part-")
    age(lake["lake"])
    assert lake["ledger"].verify().status == "verified"
    assert len(snapshot(lake["lake"])) == 10


def test_crash_after_publish_before_retire_shows_only_the_new_rows(
    lake: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    lake["writer"].write(missing_rows("auth", LINES[:10]))
    before = snapshot(lake["lake"])

    def crash(*_: Any, **__: Any) -> None:
        raise RuntimeError("power cut")

    monkeypatch.setattr(reparse, "finish", crash)
    with pytest.raises(RuntimeError):
        run(lake)
    folder = next((lake["lake"] / "source=auth").glob("day=*"))
    assert len(list(folder.glob("part-*.parquet"))) == 2  # both files on disk
    mid = snapshot(lake["lake"])
    assert mid.keys() == before.keys()  # never both
    assert all(r[3] != "template_missing" for r in mid.values())
    monkeypatch.undo()
    # The next maintenance pass finishes the job from the manifest.
    report = Compactor(lake["lake"], today=lambda: TODAY, events=lake["ledger"]).run()
    assert report.recovered == 1
    assert not list(folder.glob(f"*{lake_files.MANIFEST_SUFFIX}"))
    assert snapshot(lake["lake"]) == mid
    age(lake["lake"])
    assert lake["ledger"].verify().status == "verified"


def test_crash_before_publish_keeps_the_old_rows(
    lake: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    lake["writer"].write(missing_rows("auth", LINES[:10]))
    before = snapshot(lake["lake"])

    def crash(*_: Any, **__: Any) -> None:
        raise RuntimeError("power cut")

    monkeypatch.setattr(reparse, "publish", crash)
    with pytest.raises(RuntimeError):
        run(lake)
    assert snapshot(lake["lake"]) == before  # never neither
    monkeypatch.undo()
    Compactor(lake["lake"], today=lambda: TODAY, events=lake["ledger"]).run()
    folder = next((lake["lake"] / "source=auth").glob("day=*"))
    assert not list(folder.glob(f"*{lake_files.MANIFEST_SUFFIX}"))
    assert snapshot(lake["lake"]) == before
    # A later job still finds and reparses them.
    assert run(lake).rows == 10


def test_a_file_changed_behind_the_ledger_is_not_rewritten(lake: dict[str, Any]) -> None:
    lake["writer"].write(missing_rows("auth", LINES[:5]))
    (path,) = list(lake["lake"].rglob("part-*.parquet"))
    table = pq.read_table(path)
    pq.write_table(table.slice(0, 4), path)  # edited outside the product
    result = run(lake)
    assert result.rows == 0 and result.skipped_files == 1


# --- API ----------------------------------------------------------------------------------


@pytest.fixture
def api(tmp_path: Path, pin_now: Callable[[datetime], None]) -> dict[str, Any]:
    pin_now(NOW)
    lab = make_lab(tmp_path)
    registry = lab["app"].state.templates
    template = registry._templates.pop("linux_sshd")
    log = tmp_path / "logs" / "lin" / "auth.log"
    with log.open("a") as fh:
        fh.write("\n".join(LINES[:6]) + "\n")
    assert lab["app"].state.ingest.run_once() == 6
    lab["template"] = template
    return lab


def restore(lab: dict[str, Any]) -> None:
    lab["app"].state.templates._templates["linux_sshd"] = lab["template"]


def query(lab: dict[str, Any], sql: str) -> list[list[Any]]:
    res = lab["admin"].post("/api/query", json={"sql": sql}, headers=lab["h"])
    assert res.status_code == 200, res.text
    rows: list[list[Any]] = res.json()["rows"]
    return rows


URL = "/api/sources/lin_auth/reparse"


def test_admin_reparses_and_everyone_else_is_refused(api: dict[str, Any]) -> None:
    admin, h = api["admin"], api["h"]
    status = admin.get(URL).json()
    assert status["pending"] == 6 and status["template_available"] is False
    assert status["job"] is None
    res = admin.post(URL, headers=h)
    assert res.status_code == 409 and "linux_sshd" in res.json()["detail"]

    restore(api)
    assert admin.get(URL).json()["template_available"] is True
    assert api["ana"].post(URL).status_code == 403
    assert api["aud"].post(URL).status_code == 403
    assert api["ana"].get(URL).status_code == 403
    assert admin.post("/api/sources/nope/reparse", headers=h).status_code == 404
    assert admin.post(URL).status_code == 403  # no CSRF token

    before = query(api, "SELECT event_id, raw FROM events ORDER BY event_id")
    untouched = query(
        api,
        "SELECT event_id, parse_status, message FROM events"
        " WHERE parse_status <> 'template_missing' ORDER BY event_id",
    )
    missing = query(
        api, "SELECT event_id FROM events WHERE parse_status = 'template_missing' ORDER BY 1"
    )
    res = admin.post(URL, headers=h)
    assert res.status_code == 202, res.text
    job = res.json()
    assert job["state"] == "running" and job["rows_found"] == 6
    api["app"].state.reparse.join("lin_auth")
    job = admin.get(URL).json()["job"]
    assert job["state"] == "done", job
    assert (job["rows_rewritten"], job["files_rewritten"]) == (6, 1)
    assert job["time_min"] and job["time_max"] and job["finished_at"]
    assert admin.get(URL).json()["pending"] == 0

    assert query(api, "SELECT event_id, raw FROM events ORDER BY event_id") == before
    after = query(
        api,
        "SELECT event_id, parse_status, message FROM events"
        f" WHERE event_id NOT IN ({','.join(repr(m[0]) for m in missing)}) ORDER BY event_id",
    )
    assert after == untouched
    assert query(api, "SELECT count(*) FROM events WHERE parse_status = 'template_missing'") == [
        [0]
    ]
    # Nothing left: a second start is refused.
    assert admin.post(URL, headers=h).status_code == 409

    # The auditor sees both audit rows and a ledger that still verifies.
    rows = api["aud"].get("/api/audit/events", params={"action": "source.reparse"}).json()
    details = sorted((r["detail"]["step"], r["user_id"]) for r in rows)
    assert [d[0] for d in details] == ["end", "start"]
    start = next(r for r in rows if r["detail"]["step"] == "start")
    assert start["detail"]["events"] == 6 and start["detail"]["source_id"] == "lin_auth"
    end = next(r for r in rows if r["detail"]["step"] == "end")
    assert end["detail"]["rows_rewritten"] == 6 and end["outcome"] == "success"
    denied = api["aud"].get("/api/audit/events", params={"action": "access.denied"}).json()
    assert any(r["detail"]["path"] == URL for r in denied)
    age(api["app"].state.lake_dir)
    assert api["aud"].get("/api/integrity").status_code == 200
    seal = admin.post("/api/integrity/verify", headers=h).json()
    assert seal["status"] == "verified", seal["findings"]


def test_one_job_per_source(api: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    restore(api)
    release = threading.Event()
    original = reparse.Reparser.run

    def slow(self: reparse.Reparser, *args: Any, **kwargs: Any) -> reparse.ReparseResult:
        release.wait(10)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(reparse.Reparser, "run", slow)
    admin, h = api["admin"], api["h"]
    assert admin.post(URL, headers=h).status_code == 202
    second = admin.post(URL, headers=h)
    assert second.status_code == 409 and "already running" in second.json()["detail"]
    assert admin.get(URL).json()["job"]["state"] == "running"
    release.set()
    api["app"].state.reparse.join("lin_auth")
    assert admin.get(URL).json()["job"]["state"] == "done"


def test_a_busy_lake_refuses_politely(api: dict[str, Any]) -> None:
    from app.ingest.lakelock import lake_lock

    restore(api)
    with lake_lock(api["app"].state.lake_dir) as held:
        assert held
        res = api["admin"].post(URL, headers=api["h"])
    assert res.status_code == 409 and "try again" in res.json()["detail"].lower()
    assert api["admin"].get(URL).json()["job"] is None


def test_a_job_left_running_is_interrupted_on_restart(tmp_path: Path) -> None:
    config = load_config(Path("missing.yaml"), {"APP__PATHS__DATA_DIR": str(tmp_path / "data")})
    create_app(config)
    with sqlite3.connect(tmp_path / "data" / "meta.sqlite") as con:
        con.execute(
            "INSERT INTO reparse_jobs (job_id, source_id, template_id, user_id, state,"
            " started_at, rows_found) VALUES ('j1', 'edge', 'linux_sshd', NULL, 'running',"
            " '2026-10-10T12:00:00+00:00', 5)"
        )
    app = create_app(config)
    with sqlite3.connect(tmp_path / "data" / "meta.sqlite") as con:
        state, finished = con.execute(
            "SELECT state, finished_at FROM reparse_jobs WHERE job_id = 'j1'"
        ).fetchone()
    assert state == "interrupted" and finished is not None
    assert app.state.reparse.latest("edge").state == "interrupted"


SENT = "<38>Oct  9 20:41:12 fw-edge sshd[1]: Failed password for root from 203.0.113.9 port 4"


def test_a_listener_source_keeps_its_sender_as_device_ip(
    tmp_path: Path, pin_now: Callable[[datetime], None]
) -> None:
    """At ingest a syslog listener source fills device_ip with the sender when the parse
    leaves it empty (ADR-0021 row 5); a reparse applies the same rule from the stored row."""
    pin_now(NOW)
    lab = make_lab(tmp_path)
    udp = free_port(socket.SOCK_DGRAM)
    res = lab["admin"].post(
        "/api/sources",
        json={"source_id": "net_tm", "kind": "syslog", "format": "syslog",
              "template_id": "linux_sshd", "syslog": {"protocol": "udp", "port": udp}},
        headers=lab["h"],
    )  # fmt: skip
    assert res.status_code == 201, res.text
    registry = lab["app"].state.templates
    template = registry._templates.pop("linux_sshd")
    owner = listeners(lab, tmp_path)

    async def scenario() -> None:
        await owner.reconcile(lab["app"].state.sources.list())
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(SENT.encode() + b"\n", ("127.0.0.1", udp))
        # Wait for the line, not a fixed time (owner, 2026-11-10); the ceiling is for a hang.
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 10
        while owner.status()["net_tm"].received < 1 and loop.time() < deadline:
            await asyncio.sleep(0.05)
        await owner.close()

    asyncio.run(scenario())
    lab["app"].state.ingest.run_once()
    sql = "SELECT device_ip, parse_status FROM events WHERE source_id = 'net_tm'"
    assert query(lab, sql) == [["127.0.0.1", "template_missing"]]

    registry._templates["linux_sshd"] = template
    url = "/api/sources/net_tm/reparse"
    assert lab["admin"].post(url, headers=lab["h"]).status_code == 202
    lab["app"].state.reparse.join("net_tm")
    assert lab["admin"].get(url).json()["job"]["state"] == "done"
    ((ip, status),) = query(lab, sql)
    assert status != "template_missing"
    assert ip == "127.0.0.1"  # the sender, as ingest stores it with the template


def test_sources_flag_a_reparse_offer_until_a_reparse_is_done(api: dict[str, Any]) -> None:
    """Sources asks for the exact count only for flagged sources: the flag comes from the
    cleared fallback row, without reading the lake (review on #500)."""
    admin, h = api["admin"], api["h"]

    def flag(client: Any) -> Any:
        listed = client.get("/api/sources", headers=h).json()
        return next(s for s in listed if s["source_id"] == "lin_auth")["reparse_pending"]

    assert flag(admin) is False  # the template is still missing: nothing to offer yet
    restore(api)
    api["app"].state.ingest.run_once()  # the template loads again: the outage clears
    assert flag(admin) is True
    assert flag(api["ana"]) is False  # reparse is for administrators
    assert admin.post(URL, headers=h).status_code == 202
    api["app"].state.reparse.join("lin_auth")
    assert admin.get(URL).json()["job"]["state"] == "done"
    assert flag(admin) is False
    with api["app"].state.meta.connect() as con:
        assert con.execute("SELECT count(*) FROM source_fallbacks").fetchone()[0] == 0


def test_a_skipped_file_keeps_the_reparse_offer(api: dict[str, Any]) -> None:
    """A file whose content differs from the ledger is not rewritten, so its
    template_missing rows remain: Sources keeps offering the reparse (never silent)."""
    admin, h = api["admin"], api["h"]
    restore(api)
    api["app"].state.ingest.run_once()
    lake_dir = Path(api["app"].state.engine._lake)
    path = next(
        p
        for p in lake_dir.rglob("source=lin_auth/**/part-*.parquet")
        if "template_missing" in pq.read_table(p, columns=["parse_status"]).column(0).to_pylist()
    )
    table = pq.read_table(path)
    pq.write_table(table.slice(0, max(1, table.num_rows - 1)), path)  # edited outside
    assert admin.post(URL, headers=h).status_code == 202
    api["app"].state.reparse.join("lin_auth")
    job = admin.get(URL).json()["job"]
    assert job["state"] == "done", job
    listed = admin.get("/api/sources", headers=h).json()
    assert next(s for s in listed if s["source_id"] == "lin_auth")["reparse_pending"] is True


def test_the_integrity_report_counts_reparsed_files_and_rows(api: dict[str, Any]) -> None:
    """Owner, 2026-11-11: the reparse is in the ledger as add and remove with "reparsed"
    reasons, like compaction, and the integrity report shows the count for its period."""
    admin, h = api["admin"], api["h"]
    restore(api)
    api["app"].state.ingest.run_once()
    assert admin.post(URL, headers=h).status_code == 202
    api["app"].state.reparse.join("lin_auth")
    job = admin.get(URL).json()["job"]
    report = admin.get("/api/integrity/report", params={"days": 30}).json()
    assert report["reparsed"] == {"files": job["files_rewritten"], "rows": job["rows_rewritten"]}
    assert report["reparsed"]["rows"] > 0
