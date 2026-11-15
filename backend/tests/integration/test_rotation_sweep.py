"""One read position per file (ADR-0051, D250), part 3: records of files not seen for 30
days are removed by the daily maintenance (row 8), and a file whose name was given to a new
file while nobody held the old one says so on the source (row 4)."""

import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any

from app.ingest.sources import SourceConfig, SourceStore
from app.ingest.watcher import IngestService
from app.meta.db import MetaDB
from tests.integration.test_sources import LINE, NOW, count, env, service, write  # noqa: F401


def _moving(env: dict[str, Path]) -> tuple[Any, Any, list[timedelta]]:  # noqa: F811
    ahead = [timedelta(0)]
    meta = MetaDB(env["data"] / "meta.sqlite")
    store = SourceStore(meta, allowed_roots=[env["logs"]])
    svc = IngestService(store, meta, env["data"] / "lake", clock=lambda: NOW + ahead[0])
    return svc, store, ahead


def _records(env: dict[str, Path]) -> list[tuple[str, str]]:  # noqa: F811
    with sqlite3.connect(env["data"] / "meta.sqlite") as con:
        rows = con.execute("SELECT path, seen_at FROM file_positions ORDER BY path").fetchall()
    return [(Path(p).name, s) for p, s in rows]


def _folder(store: Any, logs: Path, glob: str = "*.log") -> None:
    store.add(SourceConfig(source_id="linux_auth", format="syslog", path=str(logs), glob=glob))


# --- the 30-day sweep (row 8) --------------------------------------------------------------


def test_records_of_files_not_seen_for_thirty_days_are_removed(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store, ahead = _moving(env)
    logs = env["logs"]
    write(logs / "kept.log", LINE.format(1, 1))
    write(logs / "gone.log", LINE.format(1, 1))
    _folder(store, logs)
    assert svc.run_once() == 2
    (logs / "gone.log").unlink()
    assert svc.sweep_positions() == 0  # nothing is that old yet
    ahead[0] = timedelta(days=31)
    assert svc.run_once() == 0
    assert svc.sweep_positions() == 1
    assert [name for name, _ in _records(env)] == ["kept.log"]
    # The idle file that is still listed kept its record: it is not read again.
    assert svc.run_once() == 0 and count(env) == 2


def test_an_idle_listed_file_is_noted_as_seen_once_a_day(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store, ahead = _moving(env)
    logs = env["logs"]
    write(logs / "a.log", LINE.format(1, 1))
    _folder(store, logs)
    svc.run_once()
    first = _records(env)[0][1]
    ahead[0] = timedelta(hours=5)
    svc.run_once()
    assert _records(env)[0][1] == first  # not written on every idle pass
    ahead[0] = timedelta(hours=25)
    svc.run_once()
    assert _records(env)[0][1] > first


def test_the_daily_maintenance_runs_the_sweep(env: dict[str, Path]) -> None:  # noqa: F811
    from app.ingest.maintenance import LakeMaintenance

    svc, store = service(env)
    m = LakeMaintenance(env["data"] / "lake", store, 30, 3600.0, 86_400.0)
    ran: list[int] = []
    m.daily = lambda: ran.append(svc.sweep_positions())
    m._retention_job()
    assert ran == [0]


# --- a name given to a new file while the old one was not held (row 4) --------------------


def _note(svc: Any) -> tuple[str, ...]:
    return tuple(svc.status()["linux_auth"].warnings)


def test_a_file_rotated_while_the_server_was_down_is_said_on_the_source(
    env: dict[str, Path],  # noqa: F811
) -> None:
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1))
    store.add(SourceConfig(source_id="linux_auth", format="syslog", path=str(f)))
    assert svc.run_once() == 1
    write(f, LINE.format(2, 2))  # written and rotated while the server is down
    f.rename(env["logs"] / "auth.log.1")
    write(f, LINE.format(3, 3), mode="w")
    svc2, _ = service(env)
    assert svc2.run_once() == 1
    (note,) = _note(svc2)
    assert "auth.log" in note and "while the server was not running" in note
    assert "if there were any, were not read" in note
    assert "2026-10-10 12:00 UTC" in note  # when the old file was last read
    assert svc2.run_once() == 0 and _note(svc2) == (note,)  # it stays for a day, said once


def test_no_note_when_the_source_also_lists_the_rotated_file(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    logs = env["logs"]
    f = logs / "auth.log"
    write(f, LINE.format(1, 1))
    _folder(store, logs, "auth.log*")
    assert svc.run_once() == 1
    write(f, LINE.format(2, 2))
    f.rename(logs / "auth.log.1")
    write(f, LINE.format(3, 3), mode="w")
    svc2, _ = service(env)
    assert svc2.run_once() == 2  # the new file, and the tail of the listed old one
    assert _note(svc2) == () and count(env) == 3


def test_no_note_for_a_rotation_the_server_followed(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1))
    store.add(SourceConfig(source_id="linux_auth", format="syslog", path=str(f)))
    assert svc.run_once() == 1
    for n in (2, 3):  # two rotations: older records of the same name must not raise a note
        write(f, LINE.format(n, n))
        f.rename(env["logs"] / f"auth.log.{n}")
        write(f, LINE.format(n + 10, n + 10), mode="w")
        assert svc.run_once() == 2
        assert _note(svc) == ()


def test_no_note_when_the_new_file_comes_a_pass_after_the_rename(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1))
    store.add(SourceConfig(source_id="linux_auth", format="syslog", path=str(f)))
    assert svc.run_once() == 1
    write(f, LINE.format(2, 2))
    f.rename(env["logs"] / "auth.log.1")
    assert svc.run_once() == 1  # read to its end through the handle, then closed
    write(f, LINE.format(3, 3), mode="w")
    assert svc.run_once() == 1
    assert _note(svc) == ()


# --- review of #587 ----------------------------------------------------------------------


def test_a_quiet_file_rotated_while_the_server_runs_raises_no_note(env: dict[str, Path]) -> None:  # noqa: F811
    """A low-volume log rotated nightly: its handle was closed after 5 idle minutes and
    nothing was written since. Every line is stored; nothing is claimed lost."""
    svc, store, ahead = _moving(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1))
    store.add(SourceConfig(source_id="linux_auth", format="syslog", path=str(f)))
    assert svc.run_once() == 1
    ahead[0] = timedelta(minutes=10)
    assert svc.run_once() == 0 and len(svc._handles) == 0
    f.rename(env["logs"] / "auth.log.1")
    write(f, LINE.format(2, 2), mode="w")
    assert svc.run_once() == 1
    assert _note(svc) == () and count(env) == 2


def test_no_note_when_the_device_number_changed_over_the_restart(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    logs = env["logs"]
    f = logs / "auth.log"
    write(f, LINE.format(1, 1))
    _folder(store, logs, "auth.log*")
    assert svc.run_once() == 1
    write(f, LINE.format(2, 2))
    f.rename(logs / "auth.log.1")
    write(f, LINE.format(3, 3), mode="w")
    with sqlite3.connect(env["data"] / "meta.sqlite") as con:
        con.execute("UPDATE file_positions SET device = device + 1")
    svc2, _ = service(env)
    assert svc2.run_once() == 2 and count(env) == 3
    assert _note(svc2) == ()  # the source lists the rotated file: it was read


def test_the_note_goes_after_a_day(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1))
    store.add(SourceConfig(source_id="linux_auth", format="syslog", path=str(f)))
    assert svc.run_once() == 1
    f.rename(env["logs"] / "auth.log.1")
    write(f, LINE.format(2, 2), mode="w")
    svc2, _, ahead = _moving(env)
    assert svc2.run_once() == 1 and len(_note(svc2)) == 1
    ahead[0] = timedelta(hours=23)
    svc2.run_once()
    assert len(_note(svc2)) == 1
    ahead[0] = timedelta(hours=25)
    svc2.run_once()
    assert _note(svc2) == ()


def test_a_source_that_cannot_be_listed_keeps_its_records(env: dict[str, Path]) -> None:  # noqa: F811
    """A folder that is away for more than 30 days (a share not mounted): its records stay,
    or every file would be read again when it returns."""
    svc, store, ahead = _moving(env)
    logs = env["logs"]
    sub = logs / "share"
    sub.mkdir()
    write(sub / "a.log", LINE.format(1, 1))
    _folder(store, sub)
    assert svc.run_once() == 1
    away = env["root"] / "share-away"
    sub.rename(away)
    ahead[0] = timedelta(days=31)
    svc.run_once()
    assert svc.status()["linux_auth"].error  # it says the path is gone
    assert svc.sweep_positions() == 0
    away.rename(sub)
    assert svc.run_once() == 0 and count(env) == 1  # nothing read twice


def test_a_listed_file_that_cannot_be_opened_keeps_its_record(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store, ahead = _moving(env)
    logs = env["logs"]
    write(logs / "a.log", LINE.format(1, 1))
    write(logs / "b.log", LINE.format(1, 1))
    _folder(store, logs)
    assert svc.run_once() == 2
    write(logs / "a.log", LINE.format(2, 2))
    (logs / "a.log").chmod(0o000)
    try:
        ahead[0] = timedelta(days=31)
        svc.run_once()
        # The source has an error for that file, so nothing of it is swept.
        assert svc.sweep_positions() == 0
    finally:
        (logs / "a.log").chmod(0o644)
    assert svc.run_once() == 1 and count(env) == 3


# --- second review of #587 -----------------------------------------------------------------


def test_an_empty_mount_point_does_not_get_its_records_swept(env: dict[str, Path]) -> None:  # noqa: F811
    """A share that is not mounted leaves its mount point: an empty folder that lists
    without an error, on another device than the files were on. That says nothing about
    the files, so their records stay and nothing is read twice when the share returns."""
    svc, store, ahead = _moving(env)
    logs = env["logs"]
    write(logs / "a.log", LINE.format(1, 1))
    _folder(store, logs)
    assert svc.run_once() == 1
    away = env["root"] / "a-away.log"
    (logs / "a.log").rename(away)  # the share goes: the folder is there, and empty
    with sqlite3.connect(env["data"] / "meta.sqlite") as con:
        con.execute("UPDATE file_positions SET device = device + 1")  # the files' own device
    ahead[0] = timedelta(days=31)
    assert svc.run_once() == 0 and svc.status()["linux_auth"].error is None
    assert svc.sweep_positions() == 0
    with sqlite3.connect(env["data"] / "meta.sqlite") as con:
        con.execute("UPDATE file_positions SET device = device - 1")  # the share is back
    away.rename(logs / "a.log")
    assert svc.run_once() == 0 and count(env) == 1


def test_what_counts_as_a_file_that_is_gone(env: dict[str, Path]) -> None:  # noqa: F811
    from app.ingest.positions import FilePosition, file_is_gone

    logs = env["logs"]
    f = logs / "a.log"
    write(f, LINE.format(1, 1))
    st = f.stat()

    def record(path: Path, device: int = st.st_dev, inode: int = st.st_ino) -> FilePosition:
        return FilePosition("s", device, inode, str(path), 0, 0, 0, "", "")

    assert not file_is_gone(record(f))  # there
    assert file_is_gone(record(logs / "deleted.log"))  # its folder is there, it is not
    assert file_is_gone(record(f, inode=st.st_ino + 1))  # another file has the name
    assert not file_is_gone(record(logs / "sub" / "x.log"))  # its folder is away
    assert not file_is_gone(record(logs / "deleted.log", device=st.st_dev + 1))  # other device


def test_a_source_first_listed_on_a_later_pass_still_gets_the_note(env: dict[str, Path]) -> None:  # noqa: F811
    """The folder comes back a moment after the server started: the first time the source
    is listed is the pass that can tell a file was rotated while the server was down."""
    svc, store = service(env)
    logs = env["logs"]
    sub = logs / "share"
    sub.mkdir()
    f = sub / "auth.log"
    write(f, LINE.format(1, 1))
    store.add(SourceConfig(source_id="linux_auth", format="syslog", path=str(f)))
    assert svc.run_once() == 1
    write(f, LINE.format(2, 2))
    f.rename(sub / "auth.log.1")
    write(f, LINE.format(3, 3), mode="w")
    away = env["root"] / "share-away"
    sub.rename(away)
    svc2, _ = service(env)
    assert svc2.run_once() == 0 and _note(svc2) == ()  # not listed yet
    away.rename(sub)
    assert svc2.run_once() == 1
    assert len(_note(svc2)) == 1


# --- third review of #587 ------------------------------------------------------------------


def test_the_note_on_a_folder_source_whose_new_file_comes_later(env: dict[str, Path]) -> None:  # noqa: F811
    """Rotated while the server was down, and the new file is created only when the next
    line is written: the first listing has no file of that name."""
    svc, store = service(env)
    logs = env["logs"]
    f = logs / "auth.log"
    write(f, LINE.format(1, 1))
    _folder(store, logs)
    assert svc.run_once() == 1
    write(f, LINE.format(2, 2))
    f.rename(logs / "auth.log.1")  # not matched by *.log
    svc2, _ = service(env)
    assert svc2.run_once() == 0 and _note(svc2) == ()
    write(f, LINE.format(3, 3), mode="w")
    assert svc2.run_once() == 1
    (note,) = _note(svc2)
    assert note.startswith("auth.log was replaced")


def test_no_note_for_an_empty_file_known_under_another_device_number(
    env: dict[str, Path],  # noqa: F811
) -> None:
    """D251: the current file was still empty at shutdown and the device number changed.
    It is the same file, so an older file of the same name does not raise the note."""
    svc, store = service(env)
    logs = env["logs"]
    f = logs / "auth.log"
    write(f, LINE.format(1, 1))
    store.add(SourceConfig(source_id="linux_auth", format="syslog", path=str(f)))
    assert svc.run_once() == 1
    f.rename(logs / "auth.log.1")
    write(f, "", mode="w")
    assert svc.run_once() == 0  # the new, empty file has its record at offset 0
    with sqlite3.connect(env["data"] / "meta.sqlite") as con:
        con.execute("UPDATE file_positions SET device = device + 1")
    write(f, LINE.format(2, 2))
    svc2, _ = service(env)
    assert svc2.run_once() == 1 and count(env) == 2
    assert _note(svc2) == ()


def test_every_file_rotated_while_down_is_named(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    logs = env["logs"]
    names = ["a.log", "b.log", "c.log", "d.log"]
    for name in names:
        write(logs / name, LINE.format(1, 1))
    _folder(store, logs)
    assert svc.run_once() == 4
    for name in names:
        (logs / name).rename(logs / (name + ".1"))
        write(logs / name, LINE.format(2, 2), mode="w")
    svc2, _ = service(env)
    assert svc2.run_once() == 4
    (note,) = _note(svc2)
    assert note.startswith("a.log, b.log, c.log and 1 more were replaced")


def test_the_app_wires_the_sweep_into_the_daily_maintenance(tmp_path: Path) -> None:
    from tests.integration.test_schedules import make_lab

    app = make_lab(tmp_path)["app"]
    assert app.state.maintenance.daily == app.state.ingest.sweep_positions
