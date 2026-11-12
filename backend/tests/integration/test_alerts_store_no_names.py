"""AI Watch alert items store no names (D242, ADR-0029 C6): keys and lines keep keyed
references placed by where each person stands, and the people field the exact names;
reading puts them back, byte for byte, for a viewer who may see them."""

import errno
import json
import sqlite3
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import main as main_mod
from app.ai import alert_codes
from app.ai import watch as watch_mod
from app.ai.alert_codes import codes_on, store_without_names
from app.alerts.items import AlertItems
from app.auth.users import User
from app.core.config import load_config
from app.meta.audit import AuditLog
from app.meta.db import MetaDB
from tests.integration.test_ai_people_masking import _audit, ai_lab  # noqa: F401  # fixture
from tests.integration.test_ai_usage import lab  # noqa: F401  # the fixture ai_lab uses
from tests.integration.test_alert_grouping import NOW, Clock
from tests.integration.test_ask import ADMIN_PW, BASE

ADMIN = User("u0", "admin", "admin")
NAMES = ("alice", "bob", "carol", "dave", "dana", "erin")
TEXT = ("subject", "ref_id", "title", "detail", "why", "entity", "changes")
KEY = b"k" * 44
HOST = "mcp|ALICE-PC|Claude Desktop"  # a machine whose name holds a person's
LABEL = "Claude Desktop MCP setup on ALICE-PC"


def _raw(meta: MetaDB) -> list[dict[str, Any]]:
    with meta.connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM alert_items ORDER BY rowid")]


def _no_names(meta: MetaDB, *only: str) -> None:
    """No person in any stored key or line (of the items `only`, when given); ALICE-PC
    is a machine and stays."""
    for r in _raw(meta):
        if only and r["item_id"] not in only:
            continue
        stored = " ".join(str(r[k]) for k in TEXT).replace("ALICE-PC", "").lower()
        assert not [n for n in NAMES if n in stored], r


def _ok(con: sqlite3.Connection) -> bool:
    return True


def _coded(tmp_path: Path) -> tuple[MetaDB, AlertItems]:
    """A store whose start rewrite has completed (nothing to rewrite): raises code."""
    meta = MetaDB(tmp_path / "w.sqlite")
    items = AlertItems(meta, AuditLog(meta), clock=Clock(), install_key=lambda: KEY)
    assert store_without_names(meta, items.refs, _ok, NOW.isoformat()) == (0, 0)
    assert codes_on(meta)
    return meta, items


def _watch(meta: MetaDB, items: AlertItems, rows: dict[str, list[Any]]) -> Any:
    class Engine:
        def run(self, sql: str, *a: Any, **k: Any) -> Any:
            key = next((k for k in rows if k in sql), None)
            return type("R", (), {"rows": rows.get(key, []) if key else [], "sources": []})()

    class Dispatch:
        def enqueue(self, *a: Any) -> None:
            pass

    return watch_mod.AiWatch(
        meta, Engine(), None, Dispatch(), AuditLog(meta), "https://siem.example.com",  # type: ignore[arg-type]  # fakes with only what is used
        clock=Clock(), items=items, domains=lambda: ["example.com"], blocked_burst=10,
    )  # fmt: skip


def test_watch_items_store_references_and_read_back_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta, items = _coded(tmp_path)
    w = _watch(meta, items, {
        "post_tool_use_failure": [("cc|dana@example.com", 12, False), ("cc|erin", 11, False)],
        "claude_account_email": [("dana@example.org", "ws-alpha")],
    })  # fmt: skip
    agent = watch_mod.AgentStatus(
        kind="Claude Code", agent="cc|dana@example.com", label="Claude Code, dana: ws-alpha",
        owners=["dana@example.com"], machine="ws-alpha", first_seen=NOW.isoformat(),
        last_seen=NOW.isoformat(), events_24h=5, state="new", new_items=[],
    )  # fmt: skip
    monkeypatch.setattr(watch_mod, "agents", lambda *a, **k: [agent])
    settings = type("S", (), {"enabled": False, "agents": False, "target_ids": []})()
    w._agents(settings, NOW)
    w._raise_sensitive("dana@example.com", {"secret": 1}, ["claude"], NOW, NOW, day="2026-10-10")
    _no_names(meta)
    read = {i.subject: i for i in items.items(ADMIN, "all")}
    assert set(read) == {
        "agent:cc|dana@example.com", "agent:cc|erin", "account:dana@example.org",
        "sensitive:dana@example.com",
    }  # fmt: skip
    assert read["agent:cc|erin"].people == ["erin"]  # a bare user name is a person
    titles = {i.title for i in items.items(ADMIN, "all")}
    assert "AI agent not reviewed: Claude Code, dana: ws-alpha" in titles
    assert (
        read["account:dana@example.org"].title
        == "Personal Claude account dana@example.org on ws-alpha"
    )
    # The same person raises into the same item after a restart (same install key).
    n = len(_raw(meta))
    again = AlertItems(meta, AuditLog(meta), clock=Clock(), install_key=lambda: KEY)
    _watch(meta, again, {})._raise_sensitive(
        "dana@example.com", {"secret": 2}, ["claude"], NOW, NOW, day="2026-10-10"
    )
    assert len(_raw(meta)) == n


def test_a_name_the_people_field_would_trim_is_not_coded_and_reads_back(
    tmp_path: Path,
) -> None:
    """`raise_item` stores people stripped and cut to 256 characters, so a name that would
    change there is never coded: a code for it could not be read back (review on #517). It
    stays as it is, masked when read for a viewer without the permission."""
    meta, items = _coded(tmp_path)
    w = _watch(meta, items, {})
    for who in ("frank@example.com ", "g" * 300 + "@example.com"):
        w._raise_sensitive(who, {"secret": 1}, ["claude"], NOW, NOW, day="2026-10-10")
    read = {i.subject for i in items.items(ADMIN, "all")}
    assert "sensitive:frank@example.com " in read
    assert "sensitive:" + "g" * 300 + "@example.com" in read
    assert not any("a person" in i.title for i in items.items(ADMIN, "all"))


def test_one_agent_keeps_one_subject_before_and_after_it_has_an_owner(tmp_path: Path) -> None:
    """Review of PR 515, finding 2: the same agent raised with and without owners is one
    subject, so its standing item, its group, its mute, and an Approved close match."""
    meta, items = _coded(tmp_path)
    w = _watch(meta, items, {})
    first = w._raise_agent(HOST, "agent", LABEL, "In use; owner no person matched", NOW,
                           refresh=True)  # fmt: skip
    later = w._raise_agent(HOST, "agent", LABEL, "In use; owner alice; device ALICE-PC", NOW,
                           refresh=True, count=1)  # fmt: skip
    assert later.item_id == first.item_id and len(_raw(meta)) == 1
    change = w._raise_agent(HOST, "MCP server:wiki", LABEL,
                            f"{LABEL} (alice): new MCP server wiki", NOW)  # fmt: skip
    subjects = {r["subject"] for r in _raw(meta)}
    assert subjects == {f"agent:{HOST}"}
    items.mute(change.item_id, 7, ADMIN, None)
    busy = w._raise_agent(HOST, "busy:2026-11-03", LABEL, f"{LABEL} (alice): 40 events in an hour",
                          NOW)  # fmt: skip
    assert busy is not None and busy.state == "closed" and busy.close_reason == "muted"
    assert items.close_subject("ai_watch", items.subject_of(first.item_id), ADMIN, "approved",
                               "Approved", None) == 2  # fmt: skip
    assert {r["state"] for r in _raw(meta)} == {"closed"}
    _no_names(meta)


def test_a_host_holding_a_name_reads_back_exactly_and_approves_that_agent(
    ai_lab: dict[str, Any],  # noqa: F811
) -> None:
    """Review of PR 515, finding 1: agent `mcp|ALICE-PC|Claude Desktop` with owner `alice`
    reads back byte for byte, and Approved writes that agent id in ai.review."""
    app, admin, h = ai_lab["app"], ai_lab["admin"], ai_lab["h"]
    assert codes_on(app.state.meta)
    why = "In use; owner alice; device ALICE-PC"
    line = f"{LABEL} (alice): new MCP server wiki"
    standing = app.state.ai_watch._raise_agent(HOST, "agent", LABEL, why, NOW, refresh=True)
    change = app.state.ai_watch._raise_agent(HOST, "MCP server:wiki", LABEL, line, NOW)
    stored = {r["item_id"]: r for r in _raw(app.state.meta)}
    assert stored[standing.item_id]["subject"] == f"agent:{HOST}"
    assert "alice" not in stored[standing.item_id]["why"]
    assert "alice" not in stored[change.item_id]["changes"]
    got = admin.get(f"/api/alerts/{standing.item_id}").json()
    assert (got["subject"], got["title"], got["why"]) == (
        f"agent:{HOST}", f"AI agent not reviewed: {LABEL}", why,
    )  # fmt: skip
    assert admin.get(f"/api/alerts/{change.item_id}").json()["changes"] == [line]
    res = admin.post(f"/api/alerts/{change.item_id}/close", json={"reason": "approved"},
                     headers=h)  # fmt: skip
    assert res.status_code == 200, res.text
    assert _audit(ai_lab, "ai.review")[-1]["agent"] == HOST
    assert admin.get(f"/api/alerts/{standing.item_id}").json()["state"] == "closed"


def test_items_stored_with_names_are_rewritten_once(tmp_path: Path) -> None:
    meta = MetaDB(tmp_path / "b.sqlite")
    items = AlertItems(meta, AuditLog(meta), clock=Clock(), install_key=lambda: KEY)
    before = [  # as older versions stored them: names in the text
        ("sensitive:alice@example.com", "Sensitive data to AI: alice@example.com",
         {"ref_id": "sensitive:alice@example.com:2026-10-10", "people": ["alice@example.com"],
          "why": "secret x1", "group": ("sensitive:alice@example.com", "sensitive")}),
        ("service:chatgpt", "AI service not reviewed: ChatGPT",
         {"ref_id": "service:chatgpt", "detail": "2 people: alice@example.com, bob",
          "people": ["alice@example.com", "bob"]}),
        ("agent:cc|carol@example.com", "AI agent not reviewed: Claude Code, carol@example.com: ws-1",
         {"ref_id": "agent:cc|carol@example.com:agent",
          "why": "In use; owner carol@example.com; device ws-1"}),
        ("mcp:wiki", "MCP server not reviewed: wiki",
         {"ref_id": "mcp:wiki", "detail": "Used by 2: dave, ws-9"}),
        (f"agent:{HOST}", f"AI agent not reviewed: {LABEL}",
         {"ref_id": f"agent:{HOST}:agent", "why": "In use; owner Alice; device ALICE-PC"}),
    ]  # fmt: skip
    for subject, title, kw in before:
        items.raise_item("ai_watch", subject, title, **kw)  # type: ignore[arg-type]  # test kwargs
    first = items.items(ADMIN, "all")
    by = {i.subject: i.item_id for i in first}
    items.mute(by["sensitive:alice@example.com"], 7, ADMIN, None)
    assert not codes_on(meta)
    assert store_without_names(meta, items.refs, _ok, NOW.isoformat()) == (5, 0)
    assert codes_on(meta)
    _no_names(meta)
    with meta.connect() as con:
        (mute,) = con.execute("SELECT subject, title FROM alert_mutes").fetchall()
    stored = {r["item_id"]: r["subject"] for r in _raw(meta)}
    assert mute["subject"] == stored[by["sensitive:alice@example.com"]]
    assert "alice" not in mute["title"]
    assert stored[by[f"agent:{HOST}"]] == f"agent:{HOST}"  # a machine key: untouched
    # Read back, every viewer with the permission sees exactly what they saw before.
    after = {i.item_id: i for i in items.items(ADMIN, "all")}
    for old in first:
        new = after[old.item_id]
        assert (new.subject, new.ref_id, new.title, new.detail, new.why, new.changes) == (
            old.subject, old.ref_id, old.title, old.detail, old.why, old.changes,
        )  # fmt: skip
    assert after[by["agent:cc|carol@example.com"]].people == ["carol@example.com"]  # moved
    assert items.mutes()[0].subject == "sensitive:alice@example.com"
    assert store_without_names(meta, items.refs, _ok, NOW.isoformat()) == (0, 0)  # idempotent
    # Dedup and the mute keep matching: the same ref id is the same item, and a new day's
    # item for her is muted.
    w = _watch(meta, items, {})
    w._raise_sensitive("alice@example.com", {"secret": 1}, ["c"], NOW, NOW, day="2026-10-10")
    assert len(_raw(meta)) == 5
    w._raise_sensitive("alice@example.com", {"secret": 1}, ["c"], NOW, NOW, day="2026-10-11")
    assert _raw(meta)[-1]["close_reason"] == "muted"


def test_an_old_item_named_only_in_its_text_reads_the_same_after_the_rewrite(
    ai_lab: dict[str, Any],  # noqa: F811
) -> None:
    """Owner, 2026-11-11: names move into people, never dropped. An administrator sees the
    original names, an analyst without the permission none, and dedup still matches."""
    app = ai_lab["app"]
    old = app.state.alert_items.raise_item(  # as an older version stored it: no people
        "ai_watch", "agent:cc|alice@example.com",
        "AI agent not reviewed: Claude Code, alice@example.com: ws-0042",
        ref_id="agent:cc|alice@example.com:agent", sources=["claude"],
        why="In use; owner alice@example.com; device ws-0042",
    )  # fmt: skip
    assert old.people == []
    rewritten, kept = store_without_names(app.state.meta, app.state.alert_items.refs, _ok, "x")
    assert rewritten >= 1 and kept == 0
    _no_names(app.state.meta, old.item_id)
    got = ai_lab["admin"].get(f"/api/alerts/{old.item_id}").json()
    assert (got["subject"], got["title"], got["why"], got["people"]) == (
        old.subject, old.title, old.why, ["alice@example.com"],
    )  # fmt: skip
    masked = ai_lab["ana"].get(f"/api/alerts/{old.item_id}")
    assert masked.status_code == 200 and "alice" not in masked.text
    assert masked.json()["people_hidden"] == 1
    n = len(_raw(app.state.meta))
    app.state.ai_watch._raise_agent(
        "cc|alice@example.com", "agent", "Claude Code, alice@example.com: ws-0042",
        "In use; owner alice@example.com; device ws-0042", NOW, refresh=True,
    )  # fmt: skip
    assert len(_raw(app.state.meta)) == n  # the same item, by its subject and ref id


def _seed(data: Path) -> list[dict[str, Any]]:
    """An install whose AI Watch item an older version stored with a name in its text,
    with a mute of that person's sensitive-data alerts and one open."""
    meta = MetaDB(data / "meta.sqlite")
    items = AlertItems(meta, AuditLog(meta), clock=Clock())
    items.raise_item(
        "ai_watch", "agent:cc|alice@example.com",
        "AI agent not reviewed: Claude Code, alice@example.com: ws-0042",
        ref_id="agent:cc|alice@example.com:agent",
        why="In use; owner alice@example.com; device ws-0042",
    )  # fmt: skip
    items.raise_item(
        "ai_watch", "sensitive:alice@example.com", "Sensitive data to AI: alice@example.com",
        ref_id="sensitive:alice@example.com:2026-10-10", people=["alice@example.com"],
    )  # fmt: skip
    with meta.connect() as con:
        con.execute(
            "INSERT INTO alert_mutes (mute_id, kind, subject, title, until, created_at)"
            " VALUES ('m-1', 'ai_watch', 'sensitive:alice@example.com',"
            " 'Sensitive data to AI: alice@example.com', '2099-01-01T00:00:00+00:00',"
            " '2026-10-10T08:30:00+00:00')"
        )
    return _raw(meta)


def _start(tmp_path: Path) -> Any:
    return main_mod.create_app(
        load_config(
            Path("missing.yaml"),
            {"APP__PATHS__DATA_DIR": str(tmp_path / "data"), "APP__SERVER__HOST": "0.0.0.0"},
        )
    )


def _at(monkeypatch: pytest.MonkeyPatch, at: datetime) -> None:
    """The next start's backup is stamped `at`."""
    real = alert_codes.backup_copy
    monkeypatch.setattr(main_mod, "backup_copy", lambda con, folder, _: real(con, folder, at))


def backups(data: Path) -> list[Path]:
    return sorted((data / "backups").glob("meta-before-alert-rewrite-*.sqlite"))


def _copied(path: Path) -> list[dict[str, Any]]:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute("SELECT * FROM alert_items ORDER BY rowid")]
    finally:
        con.close()


def test_the_rewrite_backs_up_meta_first_and_runs_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Owner, 2026-11-11: meta.sqlite is copied (0600, folder 0700) before the rewrite,
    with the rows as they were; a second start makes no copy and rewrites nothing."""
    data = tmp_path / "data"
    before = _seed(data)
    _at(monkeypatch, NOW)
    app = _start(tmp_path)
    (copy,) = backups(data)
    assert copy.name == "meta-before-alert-rewrite-20261103T180000Z.sqlite"
    assert stat.S_IMODE(copy.stat().st_mode) == 0o600
    assert stat.S_IMODE(copy.parent.stat().st_mode) == 0o700
    saved = _copied(copy)
    keys = ("item_id", "subject", "ref_id", "title", "why", "people")
    assert [[r[k] for k in keys] for r in saved] == [[r[k] for k in keys] for r in before]
    assert "alice@example.com" in saved[0]["title"]
    assert sorted(p.name for p in copy.parent.iterdir()) == [copy.name]  # no part copy left
    _no_names(app.state.meta)
    assert not app.state.startup_jobs.failing() and codes_on(app.state.meta)
    after = _raw(app.state.meta)
    again = _start(tmp_path)
    assert backups(data) == [copy] and _raw(again.state.meta) == after


def test_a_second_roll_forward_takes_a_new_backup_of_what_the_older_version_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review of PR 515, finding 6: after a rollback the older version raised a named
    alert; rolling forward again copies meta to a new file before coding it, and the
    first copy is kept as it was."""
    data = tmp_path / "data"
    _seed(data)
    _at(monkeypatch, NOW)
    _start(tmp_path)
    (first,) = backups(data)
    kept = first.read_bytes()
    meta = MetaDB(data / "meta.sqlite")
    AlertItems(meta, AuditLog(meta), clock=Clock()).raise_item(  # the older version
        "ai_watch", "sensitive:bob@example.com", "Sensitive data to AI: bob@example.com",
        ref_id="sensitive:bob@example.com:2026-11-04", people=["bob@example.com"],
    )  # fmt: skip
    _at(monkeypatch, NOW.replace(day=5))
    app = _start(tmp_path)
    assert [p.name for p in backups(data)] == [
        first.name, "meta-before-alert-rewrite-20261105T180000Z.sqlite",
    ]  # fmt: skip
    assert first.read_bytes() == kept
    assert "bob@example.com" in str(_copied(backups(data)[1]))
    _no_names(app.state.meta)


def _warns(app: Any) -> None:
    """Health shows the failed backup before the rewrite, to an administrator."""
    admin = TestClient(app, base_url=BASE)
    token = app.state.auth.setup_url("siem.example.internal", 8080).split("#", 1)[1]
    res = admin.post("/api/setup", json={"token": token, "username": "admin", "password": ADMIN_PW})
    assert res.status_code == 201, res.text
    (warning,) = admin.get("/api/health-checks").json()["background_failures"]
    assert warning["job"] == "alerts.rewrite_backup"
    assert "No space left on device" in warning["detail"]


def _full(con: sqlite3.Connection, folder: Path, at: datetime) -> Path:
    raise OSError(28, "No space left on device")


def _older_raise(data: Path, who: str, day: str) -> None:
    """What the older version raises after a rollback: the plain name in key and text."""
    meta = MetaDB(data / "meta.sqlite")
    AlertItems(meta, AuditLog(meta), clock=Clock()).raise_item(
        "ai_watch", f"sensitive:{who}", f"Sensitive data to AI: {who}",
        ref_id=f"sensitive:{who}:{day}", people=[who],
    )  # fmt: skip


def test_a_kept_item_alone_never_backs_up(tmp_path: Path) -> None:
    """Review of PR 517, finding 1: an item whose coded ref id clashes is kept, found
    before the backup, so it alone causes no copy at any start."""
    meta, items = _coded(tmp_path)
    _watch(meta, items, {})._raise_sensitive(
        "alice@example.com", {"secret": 1}, ["c"], NOW, NOW, day="2026-11-04"
    )
    items.raise_item(  # the older version, same person and day, after a rollback
        "ai_watch", "sensitive:alice@example.com", "Sensitive data to AI: alice@example.com",
        ref_id="sensitive:alice@example.com:2026-11-04", people=["alice@example.com"],
    )  # fmt: skip
    before = _raw(meta)
    calls: list[int] = []

    def counted(con: sqlite3.Connection) -> bool:
        calls.append(1)
        return True

    for _ in range(3):
        assert store_without_names(meta, items.refs, counted, NOW.isoformat()) == (0, 1)
    assert calls == [] and _raw(meta) == before


def test_a_kept_item_after_a_rollback_backs_up_once_across_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review of PR 517, finding 1, the release note's rollback path: the older version
    raises the same plain ref on the same day (kept) and another person's alert (coded);
    the next start backs up once, and later starts make no copy and change nothing."""
    data = tmp_path / "data"
    _seed(data)
    _at(monkeypatch, NOW)
    _start(tmp_path)
    assert len(backups(data)) == 1
    _older_raise(data, "alice@example.com", "2026-10-10")  # clashes with the coded one
    _older_raise(data, "bob@example.com", "2026-11-04")
    for day in (5, 6, 7):
        _at(monkeypatch, NOW.replace(day=day))
        app = _start(tmp_path)
        assert len(backups(data)) == 2, day
        if day == 5:
            after = _raw(app.state.meta)
        assert _raw(app.state.meta) == after
    plain = [r for r in after if r["subject"] == "sensitive:alice@example.com"]
    assert len(plain) == 1  # kept as it was
    _no_names(app.state.meta, *[r["item_id"] for r in after if r not in plain])


def test_a_failed_backup_at_a_later_start_keeps_codes_for_new_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review of PR 517, finding 2: once a start has coded, a later failed backup leaves
    the flag set, so a new raise joins its coded item and the coded mute still matches;
    only the older version's plain row waits, and Health warns."""
    data = tmp_path / "data"
    _seed(data)
    _at(monkeypatch, NOW)
    _start(tmp_path)
    _older_raise(data, "bob@example.com", "2026-11-04")
    monkeypatch.setattr(main_mod, "backup_copy", _full)
    app = _start(tmp_path)
    meta = app.state.meta
    assert codes_on(meta) and len(backups(data)) == 1
    assert _raw(meta)[-1]["subject"] == "sensitive:bob@example.com"  # waits
    n = len(_raw(meta))
    w = app.state.ai_watch
    w._raise_sensitive("alice@example.com", {"secret": 1}, ["c"], NOW, NOW, day="2026-10-10")
    assert len(_raw(meta)) == n  # joined the coded item
    w._raise_sensitive("alice@example.com", {"secret": 1}, ["c"], NOW, NOW, day="2026-10-11")
    new = _raw(meta)[-1]
    assert new["close_reason"] == "muted" and "alice" not in new["subject"]
    _warns(app)


def test_a_backup_without_hard_links_still_copies_and_never_overwrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review of PR 517, finding 3: a filesystem without hard links gets the copy too."""

    def no_links(src: Any, dst: Any) -> None:
        raise OSError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(alert_codes.os, "link", no_links)
    meta, _ = _coded(tmp_path)
    folder = tmp_path / "backups"
    with meta.connect() as con:
        first = alert_codes.backup_copy(con, folder, NOW)
        second = alert_codes.backup_copy(con, folder, NOW)
    assert first.name == "meta-before-alert-rewrite-20261103T180000Z.sqlite"
    assert second.name == "meta-before-alert-rewrite-20261103T180000Z-2.sqlite"
    assert sorted(p.name for p in folder.iterdir()) == sorted([first.name, second.name])
    assert stat.S_IMODE(first.stat().st_mode) == 0o600
    with sqlite3.connect(first) as copy:  # a whole copy: the flag the rewrite set is in it
        flag = copy.execute("SELECT fix_id FROM one_time_fixes").fetchall()
    assert (alert_codes.FLAG,) in flag and _copied(first) == []


def test_a_failed_backup_keeps_names_in_new_raises_so_mutes_and_dedup_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    """Review of PR 515, finding 3: with the backup failing nothing is coded, new raises
    included, so a muted person stays muted and a repeat joins its open item."""
    data = tmp_path / "data"
    before = _seed(data)

    monkeypatch.setattr(main_mod, "backup_copy", _full)
    app = _start(tmp_path)
    assert "{p:" not in str(_raw(app.state.meta)) and not codes_on(app.state.meta)
    assert [r["title"] for r in _raw(app.state.meta)] == [r["title"] for r in before]
    logs = [json.loads(x) for x in capfd.readouterr().err.splitlines() if x.startswith("{")]
    (failed,) = [e for e in logs if e["event"] == "alerts.rewrite_backup_failed"]
    assert failed["error"] == "OSError" and "alice" not in str(failed)
    w = app.state.ai_watch
    w._raise_sensitive("alice@example.com", {"secret": 1}, ["c"], NOW, NOW, day="2026-10-10")
    assert len(_raw(app.state.meta)) == 2  # joined the open item
    w._raise_sensitive("alice@example.com", {"secret": 1}, ["c"], NOW, NOW, day="2026-10-11")
    new = _raw(app.state.meta)[-1]
    assert new["close_reason"] == "muted" and new["subject"] == "sensitive:alice@example.com"
    _warns(app)
    # The next start backs up and codes everything, what was raised meanwhile included,
    # and the mute still matches.
    monkeypatch.undo()
    again = _start(tmp_path).state
    _no_names(again.meta)
    assert codes_on(again.meta) and len(backups(data)) == 1
    again.ai_watch._raise_sensitive(
        "alice@example.com", {"secret": 1}, ["c"], NOW, NOW, day="2026-10-12"
    )
    assert _raw(again.meta)[-1]["close_reason"] == "muted"
