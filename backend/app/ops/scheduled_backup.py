"""Scheduled backups (handoff item 8): a daily backup of the data folder by the server.

The schedule loop calls `tick()` every 30 seconds. It is cheap: it checks whether today's
backup time has passed with no run since, and whether the last success is too old. A due
backup runs on its own low-priority thread, so schedules and alerts keep going while it
copies. Each run writes `scheduled-<UTC time>.tar.gz` (0600) into the backup folder through
a temporary name, so a half-written file is never counted. Only after a run succeeds are
the oldest scheduled files beyond the kept count deleted; a failed or skipped run deletes
nothing. Hand-made backups (other names) are never touched.

Before a run, free space is checked: a run that would leave less than the reserve
(5% of the disk, at least 1 GiB) is skipped with a warning on Health instead.
With no success for 48 hours, one alert item is raised (kind gap, like other Health
alerts); it stays the only one until a backup succeeds, which closes it as Resolved.
"""

from __future__ import annotations

import os
import re
import shutil
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog

from app.alerts.items import AlertItems
from app.core import clock as app_clock
from app.core.errors import ParamInvalidError, log_detail
from app.meta.audit import AuditLog
from app.meta.db import MetaDB
from app.ops import backup as ops
from app.ops.backup import BACKUPS_DIR, TREES

log = structlog.get_logger(__name__)

DEFAULT_TIME = "02:15"
DEFAULT_KEEP = 14
MAX_KEEP = 90
OVERDUE = timedelta(hours=48)
RESERVE_FRACTION = 0.05
RESERVE_MIN = 1 << 30
KEEP_RUNS = 100
SUBJECT = "backup"
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
NAME_RE = re.compile(r"^scheduled-\d{8}T\d{6}Z\.tar\.gz$")


@dataclass(frozen=True, slots=True)
class BackupSettings:
    enabled: bool
    at_time: str  # HH:MM in the install's time zone
    keep: int
    updated_at: str
    updated_by: str | None


@dataclass(frozen=True, slots=True)
class BackupRun:
    run_id: str
    started_at: str
    finished_at: str | None
    result: str  # running | success | failed | skipped
    file: str | None
    bytes: int | None
    error: str | None


@dataclass(frozen=True, slots=True)
class BackupHealth:
    enabled: bool
    at_time: str
    timezone: str
    keep: int
    folder: str
    kept: int  # scheduled backup files in the folder now
    last: BackupRun | None
    last_success_at: str | None
    next_at: str | None
    state: str  # healthy | attention | unhealthy
    reason: str | None


def _disk(path: Path) -> tuple[int, int]:
    usage = shutil.disk_usage(path)
    return usage.total, usage.free


def _thread(fn: Callable[[], None]) -> None:
    def work() -> None:
        try:
            os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 10)
        except (AttributeError, OSError):
            pass  # not Linux, or not allowed: normal priority
        fn()

    threading.Thread(target=work, name="scheduled-backup", daemon=True).start()


def _mb(n: int) -> str:
    return f"{n / 1e6:,.1f} MB" if n < 1e9 else f"{n / 1e9:,.1f} GB"


class BackupScheduler:
    def __init__(
        self,
        meta: MetaDB,
        data_dir: Path,
        audit: AuditLog,
        items: AlertItems | None,
        folder: Path | None = None,
        tz: str = "UTC",
        clock: Callable[[], datetime] = app_clock.now,
        disk: Callable[[Path], tuple[int, int]] = _disk,
        spawn: Callable[[Callable[[], None]], None] = _thread,
    ) -> None:
        self._meta = meta
        self._data = data_dir
        self._audit = audit
        self._items = items
        self.folder = folder or data_dir / BACKUPS_DIR
        self.tz_name = tz
        try:
            self._tz = ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            self._tz, self.tz_name = ZoneInfo("UTC"), "UTC"
        self._clock = clock
        self._disk = disk
        self._spawn = spawn
        self._lock = threading.Lock()  # one backup at a time

    def _now(self) -> datetime:
        return self._clock().astimezone(UTC)

    def recover(self) -> int:
        """At start: a run left `running` by a stop or crash is failed, and its temporary
        file is removed. Returns how many runs it marked."""
        with self._meta.connect() as con:
            n = con.execute(
                "UPDATE backup_runs SET result = 'failed', finished_at = ?,"
                " error = 'The server stopped during the backup' WHERE result = 'running'",
                (self._now().isoformat(),),
            ).rowcount
        if self.folder.is_dir():
            for p in self.folder.glob(".scheduled-*.tar.gz.tmp"):
                p.unlink(missing_ok=True)
        return int(n)

    # --- settings -------------------------------------------------------------------------

    def settings(self) -> BackupSettings:
        with self._meta.connect() as con:
            row = con.execute("SELECT * FROM backup_settings WHERE id = 1").fetchone()
            if row is None:
                # First look on this install: the defaults, on, from now (an upgrade does
                # not run a backup at once; the first is at the next backup time).
                con.execute(
                    "INSERT OR IGNORE INTO backup_settings (id, updated_at) VALUES (1, ?)",
                    (self._now().isoformat(),),
                )
                row = con.execute("SELECT * FROM backup_settings WHERE id = 1").fetchone()
        return BackupSettings(
            bool(row["enabled"]), row["at_time"], int(row["keep"]), row["updated_at"],
            row["updated_by"],
        )  # fmt: skip

    def save(
        self, enabled: bool, at_time: str, keep: int, actor: str, ip: str | None
    ) -> BackupSettings:
        if not TIME_RE.fullmatch(at_time):
            raise ParamInvalidError("Give the time as HH:MM, 00:00 to 23:59")
        if not 1 <= keep <= MAX_KEEP:
            raise ParamInvalidError(f"Keep between 1 and {MAX_KEEP} backups")
        before = self.settings()
        with self._meta.connect() as con:
            con.execute(
                "UPDATE backup_settings SET enabled = ?, at_time = ?, keep = ?,"
                " updated_at = ?, updated_by = ? WHERE id = 1",
                (int(enabled), at_time, keep, self._now().isoformat(), actor),
            )
        after = self.settings()
        self._audit.write(
            "settings.backup",
            "success",
            actor,
            ip,
            {"from": _setting(before), "to": _setting(after)},
        )
        return after

    # --- schedule -------------------------------------------------------------------------

    def _slot(self, s: BackupSettings, now: datetime) -> datetime:
        """The latest backup time at or before `now`, in UTC."""
        hh, mm = (int(x) for x in s.at_time.split(":"))
        local = now.astimezone(self._tz)
        slot = datetime.combine(local.date(), time(hh, mm), tzinfo=self._tz)
        if slot > local:
            slot = datetime.combine(local.date() - timedelta(days=1), time(hh, mm), self._tz)
        return slot.astimezone(UTC)

    def next_at(self, s: BackupSettings, now: datetime) -> datetime:
        slot = self._slot(s, now)
        hh, mm = (int(x) for x in s.at_time.split(":"))
        day = slot.astimezone(self._tz).date() + timedelta(days=1)
        nxt = datetime.combine(day, time(hh, mm), tzinfo=self._tz).astimezone(UTC)
        changed = datetime.fromisoformat(s.updated_at)
        return slot if self._due_slot(s, slot, changed) else nxt

    def _due_slot(self, s: BackupSettings, slot: datetime, changed: datetime) -> bool:
        """The slot counts only if the settings were in place before it, and nothing ran
        since it."""
        if changed > slot:
            return False
        with self._meta.connect() as con:
            ran = con.execute(
                "SELECT 1 FROM backup_runs WHERE started_at >= ? LIMIT 1", (slot.isoformat(),)
            ).fetchone()
        return ran is None

    def tick(self) -> bool:
        """Start a backup if one is due; check the 48-hour alert. True when one started."""
        now = self._now()
        s = self.settings()
        started = False
        if s.enabled:
            slot = self._slot(s, now)
            if self._due_slot(s, slot, datetime.fromisoformat(s.updated_at)):
                if self._lock.acquire(blocking=False):
                    run_id = self._begin(slot, now)
                    self._spawn(lambda: self._run_locked(run_id, s.keep))
                    started = True
        try:
            self._overdue(s, now)
        except Exception as exc:  # never stops the schedule
            log.warning("backup.overdue_check_failed", **log_detail(exc))
        return started

    def _begin(self, slot: datetime, now: datetime) -> str:
        run_id = str(uuid.uuid4())
        with self._meta.connect() as con:
            con.execute(
                "INSERT INTO backup_runs (run_id, slot, started_at, result)"
                " VALUES (?, ?, ?, 'running')",
                (run_id, slot.isoformat(), now.isoformat()),
            )
            con.execute(
                "DELETE FROM backup_runs WHERE run_id NOT IN"
                " (SELECT run_id FROM backup_runs ORDER BY started_at DESC LIMIT ?)",
                (KEEP_RUNS,),
            )
        return run_id

    def _run_locked(self, run_id: str, keep: int) -> None:
        try:
            self._run(run_id, keep)
        except Exception as exc:  # recorded as failed; never fatal
            self._finish(run_id, "failed", error=f"{type(exc).__name__}: {exc}"[:500])
            log.warning("backup.failed", **log_detail(exc))
        finally:
            self._lock.release()

    def _estimate(self) -> int:
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT bytes FROM backup_runs WHERE result = 'success'"
                " ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        if row is not None and row["bytes"]:
            return int(row["bytes"])
        total = 0  # never backed up: the data it would copy, uncompressed
        for name in ("meta.sqlite", *TREES):
            p = self._data / name
            if p.is_file():
                total += p.stat().st_size
            elif p.is_dir():
                total += sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
        return total

    def _run(self, run_id: str, keep: int) -> None:
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        need = self._estimate()
        size, free = self._disk(self.folder)
        reserve = max(RESERVE_MIN, int(size * RESERVE_FRACTION))
        if free - need < reserve:
            self._finish(
                run_id,
                "skipped",
                error=(
                    f"Not enough free space: {_mb(free)} free, a backup needs about {_mb(need)}"
                    f" and {_mb(reserve)} is kept free. Free some space or keep fewer backups."
                ),
            )
            log.warning("backup.skipped_low_disk")
            return
        stamp = self._now().strftime("%Y%m%dT%H%M%SZ")
        final = self.folder / f"scheduled-{stamp}.tar.gz"
        tmp = self.folder / f".{final.name}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as fh:
                ops.create(self._data, fh)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, final)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        pruned = self._prune(keep)
        self._finish(run_id, "success", file=final.name, size=final.stat().st_size, pruned=pruned)
        if self._items is not None:
            self._items.close_resolved("gap", SUBJECT, "A backup succeeded")

    def files(self) -> list[Path]:
        """Scheduled backup files, oldest first (names sort by time)."""
        if not self.folder.is_dir():
            return []
        return sorted(p for p in self.folder.iterdir() if NAME_RE.fullmatch(p.name) and p.is_file())

    def _prune(self, keep: int) -> int:
        old = self.files()[:-keep]
        for p in old:
            p.unlink(missing_ok=True)
        return len(old)

    def _finish(
        self,
        run_id: str,
        result: str,
        *,
        file: str | None = None,
        size: int | None = None,
        error: str | None = None,
        pruned: int = 0,
    ) -> None:
        with self._meta.connect() as con:
            con.execute(
                "UPDATE backup_runs SET finished_at = ?, result = ?, file = ?, bytes = ?,"
                " error = ? WHERE run_id = ?",
                (self._now().isoformat(), result, file, size, error, run_id),
            )
        self._audit.write(
            "backup.run",
            "success" if result == "success" else "failure",
            None,
            None,
            {"run_id": run_id, "result": result, "file": file, "bytes": size, "pruned": pruned},
        )

    # --- health ---------------------------------------------------------------------------

    def _last(self, success: bool = False) -> BackupRun | None:
        where = "WHERE result = 'success'" if success else ""
        with self._meta.connect() as con:
            r = con.execute(
                f"SELECT * FROM backup_runs {where} ORDER BY started_at DESC LIMIT 1"  # noqa: S608  # fixed text
            ).fetchone()
        if r is None:
            return None
        return BackupRun(
            r["run_id"], r["started_at"], r["finished_at"], r["result"], r["file"], r["bytes"],
            r["error"],
        )  # fmt: skip

    def _overdue(self, s: BackupSettings, now: datetime) -> None:
        if self._items is None or not s.enabled:
            return
        ok = self._last(success=True)
        since = datetime.fromisoformat(ok.started_at if ok else s.updated_at)
        if now - since < OVERDUE:
            return
        last = self._last()
        why = f" Last run: {last.result}." if last and last.result != "success" else ""
        if last and last.error:
            why += f" {last.error}"
        self._items.raise_item(
            "gap",
            SUBJECT,
            "No successful backup in 48 hours",
            # One per episode: the last success names it, so repeats return the same item.
            ref_id=f"backup:{ok.started_at if ok else 'never'}",
            detail=(
                f"The last successful backup was {ok.started_at[:16]} UTC." if ok
                else "No scheduled backup has succeeded yet."
            ) + why + " See Health, Backups.",
            severity="medium",
        )  # fmt: skip

    def health(self) -> BackupHealth:
        now = self._now()
        s = self.settings()
        last = self._last()
        ok = last if last and last.result == "success" else self._last(success=True)
        state, reason = "healthy", None
        if not s.enabled:
            state = "attention"
            reason = "Scheduled backups are turned off (Settings, About and licenses)"
        elif last is None:
            state, reason = "attention", "No scheduled backup has run yet"
        elif last.result == "failed":
            state, reason = "unhealthy", f"The last backup failed: {last.error or 'no detail'}"
        elif last.result == "running":
            reason = "A backup is running now"
        elif last.result == "skipped":
            state, reason = "attention", f"The last backup was skipped. {last.error or ''}"
        if s.enabled and state != "unhealthy":
            since = datetime.fromisoformat(ok.started_at if ok else s.updated_at)
            if now - since >= OVERDUE:
                state = "unhealthy"
                reason = reason or "No successful backup in 48 hours"
        return BackupHealth(
            enabled=s.enabled,
            at_time=s.at_time,
            timezone=self.tz_name,
            keep=s.keep,
            folder=str(self.folder),
            kept=len(self.files()),
            last=last,
            last_success_at=ok.started_at if ok else None,
            next_at=self.next_at(s, now).isoformat() if s.enabled else None,
            state=state,
            reason=reason,
        )


def _setting(s: BackupSettings) -> dict[str, Any]:
    return {"enabled": s.enabled, "at_time": s.at_time, "keep": s.keep}
