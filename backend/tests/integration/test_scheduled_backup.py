"""Scheduled backups (handoff item 8): daily at the set time on a frozen clock, 14 kept and
pruned only after a success, failures and low disk shown on Health, one alert after 48
hours with no success and closed by the next success, settings admin only and audited."""

import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.alerts.items import AlertItems
from app.core import clock
from app.meta.audit import AuditLog
from app.meta.db import MetaDB
from app.ops import scheduled_backup as sb
from app.ops.backup import verify
from tests.integration.test_auditor_sql import lab  # noqa: F401  # fixture
from tests.integration.test_backup import make_data

# 2026-11-09 01:00 in Los Angeles (PST, UTC-8): the default 02:15 is an hour later.
T0 = datetime(2026, 11, 9, 9, 0, tzinfo=UTC)
TZ = "America/Los_Angeles"
BIG = (1 << 40, 1 << 39)  # a 1 TiB disk, half free


@pytest.fixture
def now() -> Iterator[Callable[[datetime], None]]:
    clock.pin(T0)
    yield clock.pin
    clock.pin(None)


def make(tmp_path: Path, disk: tuple[int, int] = BIG) -> tuple[sb.BackupScheduler, MetaDB]:
    data = make_data(tmp_path)
    meta = MetaDB(data / "meta.sqlite")
    audit = AuditLog(meta)
    items = AlertItems(meta, audit, clock=clock.now)
    s = sb.BackupScheduler(
        meta, data, audit, items, tz=TZ, disk=lambda _: disk, spawn=lambda fn: fn()
    )
    s.settings()  # the install's first look: defaults from T0
    return s, meta


def open_alerts(meta: MetaDB) -> list[Any]:
    with meta.connect() as con:
        return con.execute(
            "SELECT * FROM alert_items WHERE subject = 'backup' AND state = 'open'"
        ).fetchall()


def audit_rows(meta: MetaDB, action: str) -> list[Any]:
    with meta.connect() as con:
        return con.execute("SELECT * FROM audit_log WHERE action = ?", (action,)).fetchall()


def test_defaults_on_and_fires_at_set_time(tmp_path: Path, now: Any) -> None:
    s, _ = make(tmp_path)
    st = s.settings()
    assert (st.enabled, st.at_time, st.keep) == (True, "02:15", 14)
    assert not s.tick()  # 01:00 local: not yet
    now(T0 + timedelta(minutes=74))
    assert not s.tick()  # 02:14
    now(T0 + timedelta(minutes=75))
    assert s.tick()  # 02:15: runs
    assert not s.tick()  # once per day
    files = s.files()
    assert [p.name for p in files] == ["scheduled-20261109T101500Z.tar.gz"]
    assert files[0].stat().st_mode & 0o777 == 0o600
    info, _ = verify(files[0])
    assert info.has_key
    h = s.health()
    assert h.state == "healthy" and h.last and h.last.result == "success" and h.last.bytes
    assert h.next_at == "2026-11-10T10:15:00+00:00"
    assert audit_rows(_meta(s), "backup.run")[0]["user_id"] is None


def _meta(s: sb.BackupScheduler) -> MetaDB:
    meta: MetaDB = s._meta
    return meta


def test_upgrade_waits_for_next_time(tmp_path: Path, now: Any) -> None:
    """Settings first seen after today's time (an upgrade at noon): no backup until the next
    day's time, so an update never starts a backup at once."""
    now(T0 + timedelta(hours=12))
    s, _ = make(tmp_path)
    assert not s.tick()
    now(T0 + timedelta(days=1, minutes=75))
    assert s.tick()


def test_keeps_count_and_prunes_only_after_success(tmp_path: Path, now: Any) -> None:
    s, meta = make(tmp_path)
    s.folder.mkdir(mode=0o700)
    hand = s.folder / "backup-2026-10-22.tar.gz"  # a hand-made one is never pruned
    hand.write_bytes(b"x")
    for day in range(16):
        now(T0 + timedelta(days=day, minutes=75))
        assert s.tick()
    assert len(s.files()) == 14 and hand.exists()
    assert s.files()[0].name == "scheduled-20261111T101500Z.tar.gz"

    kept = list(s.files())

    def boom(*_: Any, **__: Any) -> None:
        raise OSError("disk went away")

    real = sb.ops.create
    sb.ops.create = boom  # type: ignore[assignment]  # the next run fails
    try:
        now(T0 + timedelta(days=16, minutes=75))
        assert s.tick()
    finally:
        sb.ops.create = real
    assert s.files() == kept  # nothing pruned, no partial file left
    assert not list(s.folder.glob(".*.tmp"))
    h = s.health()
    assert h.state == "unhealthy" and h.last and h.last.result == "failed"
    assert h.reason and "disk went away" in h.reason
    assert open_alerts(meta) == []  # last success a day ago: no alert yet


def test_low_disk_skips_with_warning(tmp_path: Path, now: Any) -> None:
    s, _ = make(tmp_path, disk=(10 << 30, 1 << 30))  # 1 GiB free of 10: under the reserve
    now(T0 + timedelta(minutes=75))
    assert s.tick()
    assert s.files() == []
    h = s.health()
    assert h.state == "attention" and h.last and h.last.result == "skipped"
    assert h.reason and "Not enough free space" in h.reason


def test_overdue_raises_one_alert_and_success_clears(tmp_path: Path, now: Any) -> None:
    s, meta = make(tmp_path)
    now(T0 + timedelta(minutes=75))
    assert s.tick()
    real = sb.ops.create

    def boom(*_: Any, **__: Any) -> None:
        raise OSError("read-only file system")

    sb.ops.create = boom  # type: ignore[assignment]
    try:
        for day in (1, 2):
            now(T0 + timedelta(days=day, minutes=75))
            s.tick()
        assert len(open_alerts(meta)) == 1  # 48 hours since the success at day 0
        for minutes in (1, 30, 600):  # many ticks later: still one
            now(T0 + timedelta(days=2, minutes=75 + minutes))
            s.tick()
        alerts = open_alerts(meta)
        assert len(alerts) == 1 and alerts[0]["kind"] == "gap"
        assert alerts[0]["title"] == "No successful backup in 48 hours"
        assert s.health().state == "unhealthy"
    finally:
        sb.ops.create = real
    now(T0 + timedelta(days=3, minutes=75))
    assert s.tick()
    assert open_alerts(meta) == []
    with meta.connect() as con:
        row = con.execute("SELECT * FROM alert_items WHERE subject = 'backup'").fetchone()
    assert row["close_reason"] == "resolved" and row["closed_by"] is None
    assert s.health().state == "healthy"


def test_crash_mid_run_is_failed_at_start(tmp_path: Path, now: Any) -> None:
    s, _ = make(tmp_path)
    started: list[Callable[[], None]] = []
    s._spawn = started.append  # the run never gets to finish
    now(T0 + timedelta(minutes=75))
    assert s.tick()
    assert s.health().last.result == "running"  # type: ignore[union-attr]
    assert s.recover() == 1
    assert s.health().last.result == "failed"  # type: ignore[union-attr]


def test_settings_admin_only_and_audited(lab: dict[str, Any]) -> None:  # noqa: F811
    admin, h = lab["admin"], lab["h"]
    res = admin.get("/api/settings/backups")
    assert res.status_code == 200
    assert res.json()["enabled"] is True and res.json()["keep"] == 14
    res = admin.put(
        "/api/settings/backups", json={"enabled": True, "at_time": "03:40", "keep": 7}, headers=h
    )
    assert res.status_code == 200 and res.json()["at_time"] == "03:40"
    bad = admin.put(
        "/api/settings/backups", json={"enabled": True, "at_time": "25:00", "keep": 7}, headers=h
    )
    assert bad.status_code == 400
    assert (
        admin.put(
            "/api/settings/backups",
            json={"enabled": True, "at_time": "03:40", "keep": 0},
            headers=h,
        ).status_code
        == 400
    )
    meta = lab["app"].state.meta
    rows = audit_rows(meta, "settings.backup")
    ids = {u["username"]: u["user_id"] for u in admin.get("/api/users").json()}
    assert len(rows) == 1 and rows[0]["user_id"] == ids["admin"]
    detail = json.loads(rows[0]["detail"])
    assert detail["from"]["keep"] == 14 and detail["to"] == {
        "enabled": True,
        "at_time": "03:40",
        "keep": 7,
    }

    from tests.integration.test_auditor_sql import client

    for name in ("ana", "aud"):
        c = client(lab, name)
        assert c.get("/api/settings/backups").status_code == 403
        assert (
            c.put(
                "/api/settings/backups", json={"enabled": False, "at_time": "01:00", "keep": 1}
            ).status_code
            == 403
        )
    health = admin.get("/api/health-checks").json()["backup"]
    assert health["enabled"] is True and health["keep"] == 7 and health["last"] is None


def test_restore_leaves_backups_folder_in_place(tmp_path: Path, now: Any) -> None:
    s, _ = make(tmp_path)
    now(T0 + timedelta(minutes=75))
    assert s.tick()
    archive = s.files()[0]
    _, kept = sb.ops.restore(archive, s._data, replace=True)
    assert kept is not None and not (kept / "backups").exists()
    assert s.files() == [archive]  # still beside the restored data
