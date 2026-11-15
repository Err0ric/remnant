"""One read position per file, not per path (ADR-0051, D250; audit 2026-11 H5), part 1:
the position is keyed by the file (source, device, inode) and used only when the open file's
content matches it, so a renamed copy is not read again, a file refilled in place is read
from its start with a warning, and an idle file is not opened at all."""

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from app.ingest import watcher
from app.ingest.sources import SourceConfig
from tests.integration.test_sources import LINE, count, env, service, write  # noqa: F401


def _folder(store: Any, logs: Path) -> None:
    store.add(SourceConfig(source_id="linux_auth", format="syslog", path=str(logs), glob="*"))


def _file(store: Any, f: Path) -> None:
    store.add(SourceConfig(source_id="linux_auth", format="syslog", path=str(f)))


def _warnings(svc: Any) -> tuple[str, ...]:
    return tuple(svc.status()["linux_auth"].warnings)


def test_copytruncate_that_grows_past_the_old_position_is_read_from_zero(
    env: dict[str, Path],  # noqa: F811
) -> None:
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1) + LINE.format(2, 2))
    _file(store, f)
    assert svc.run_once() == 2 and _warnings(svc) == ()
    # logrotate copytruncate, then three new lines before the next pass: the same inode,
    # and already longer than the old position.
    write(f, LINE.format(3, 3) + LINE.format(4, 4) + LINE.format(5, 5), mode="w")
    assert svc.run_once() == 3
    assert count(env) == 5
    # Health is told, and the warning names the file (D250).
    (warning,) = _warnings(svc)
    assert "auth.log" in warning and "read again from its start" in warning
    assert svc.run_once() == 0
    assert _warnings(svc) == (warning,)  # it stays; it is not only there for one pass


def test_a_file_that_shrank_is_read_from_zero_with_a_warning(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1) + LINE.format(2, 2) + LINE.format(3, 3))
    _file(store, f)
    assert svc.run_once() == 3
    write(f, LINE.format(4, 4), mode="w")
    assert svc.run_once() == 1
    assert count(env) == 4 and len(_warnings(svc)) == 1


def test_a_rotated_copy_the_folder_source_also_lists_is_not_read_again(
    env: dict[str, Path],  # noqa: F811
) -> None:
    svc, store = service(env)
    f = env["logs"] / "app.log"
    write(f, LINE.format(1, 1) + LINE.format(2, 2))
    _folder(store, env["logs"])
    assert svc.run_once() == 2
    f.rename(env["logs"] / "app.log.1")  # renamed; the new file is not there yet
    assert svc.run_once() == 0
    write(f, LINE.format(3, 3), mode="w")
    write(env["logs"] / "app.log.1", LINE.format(4, 4))  # a writer that still held it open
    assert svc.run_once() == 2
    assert count(env) == 4
    assert svc.run_once() == 0
    assert _warnings(svc) == ()  # a rename is not a truncation


def test_a_chain_of_rotated_copies_is_not_read_again(env: dict[str, Path]) -> None:  # noqa: F811
    """logrotate `rotate 2` on a folder source that lists the copies: every name shifts in
    one rotation, with no pass in between."""
    svc, store = service(env)
    logs = env["logs"]
    write(logs / "app.log", LINE.format(1, 1) + LINE.format(2, 2))
    _folder(store, logs)
    assert svc.run_once() == 2
    (logs / "app.log").rename(logs / "app.log.1")
    write(logs / "app.log", LINE.format(3, 3), mode="w")
    assert svc.run_once() == 1
    (logs / "app.log.1").rename(logs / "app.log.2")
    (logs / "app.log").rename(logs / "app.log.1")
    write(logs / "app.log", LINE.format(4, 4), mode="w")
    assert svc.run_once() == 1
    assert count(env) == 4
    assert svc.run_once() == 0


def test_another_file_under_a_known_inode_is_read_from_zero(env: dict[str, Path]) -> None:  # noqa: F811
    """A new `b.log` with the inode number of the read `a.log`, starting with the same bytes
    (a long header): the bytes just before the old position differ, so it is another file.
    Not a truncation: the name is not the one the position was saved for."""
    svc, store = service(env)
    logs = env["logs"]
    header = "".join(LINE.format(i, i) for i in range(1, 5))  # more than 256 bytes
    write(logs / "a.log", header + LINE.format(10, 10) + LINE.format(11, 11))
    _folder(store, logs)
    assert svc.run_once() == 6
    (logs / "a.log").rename(logs / "b.log")  # stands in for delete, then inode reuse
    write(logs / "b.log", header + "".join(LINE.format(i, i) for i in range(20, 28)), mode="w")
    assert svc.run_once() == 12  # every line of the new file
    assert _warnings(svc) == ()


def test_a_refill_with_the_same_bytes_up_to_the_position_is_the_known_limit(
    env: dict[str, Path],  # noqa: F811
) -> None:
    """What the content checks cannot see: a file emptied and refilled in place with the
    same bytes up to the old position. It continues from there (ADR-0051, unsolved)."""
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    same = LINE.format(1, 1) * 6
    write(f, same)
    _file(store, f)
    assert svc.run_once() == 6
    write(f, same + LINE.format(9, 9), mode="w")
    assert svc.run_once() == 1


def test_a_rotation_between_listing_and_reading_does_not_mix_two_files(
    env: dict[str, Path],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The file is identified from the open handle, never from the name: here the name is
    given to a new file after the pass looked at it and before it is opened."""
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1) + LINE.format(2, 2))
    _file(store, f)
    assert svc.run_once() == 2
    write(f, LINE.format(3, 3))  # so the pass opens it
    real = watcher.open_regular

    def rotate_then_open(path: Path, roots: list[Path]) -> Any:
        if path.name == "auth.log" and not (env["logs"] / "auth.log.1").exists():
            f.rename(env["logs"] / "auth.log.1")
            write(f, "".join(LINE.format(i, i) for i in range(10, 15)), mode="w")
        return real(path, roots)

    monkeypatch.setattr(watcher, "open_regular", rotate_then_open)
    # All five lines of the new file, none skipped at the old file's position; and the
    # old file's last line, read through the handle the watcher still held (part 2).
    assert svc.run_once() == 6
    assert count(env, "raw LIKE '%sshd[1_]%'") == 5
    assert count(env) == 8 and svc.run_once() == 0


def test_an_idle_file_is_not_opened(env: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    svc, store = service(env)
    logs = env["logs"]
    for name in ("a.log", "b.log", "c.log"):
        write(logs / name, LINE.format(1, 1))
    _folder(store, logs)
    assert svc.run_once() == 3
    opened: list[str] = []
    real = watcher.open_regular

    def counting(path: Path, roots: list[Path]) -> Any:
        opened.append(path.name)
        return real(path, roots)

    monkeypatch.setattr(watcher, "open_regular", counting)
    assert svc.run_once() == 0 and opened == []
    write(logs / "b.log", LINE.format(2, 2))
    assert svc.run_once() == 1 and opened == ["b.log"]


def test_a_file_longer_than_one_read_is_finished_on_later_passes(
    env: dict[str, Path],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not read to its end is not idle, though its size and time did not change."""
    line = LINE.format(1, 1)
    monkeypatch.setattr(watcher, "READ_LIMIT", len(line) * 2 + 5)
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, line * 5)
    _file(store, f)
    assert [svc.run_once() for _ in range(4)] == [2, 2, 1, 0]
    assert count(env) == 5


def test_a_line_without_its_newline_is_held_and_the_file_is_then_idle(
    env: dict[str, Path],  # noqa: F811
) -> None:
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1) + "<38>Oct  9 20:41:05 bastion sshd[5]: half")
    _file(store, f)
    assert [svc.run_once(), svc.run_once()] == [1, 0]
    write(f, " done\n")
    assert svc.run_once() == 1 and count(env) == 2


# --- the update, and going back (ADR-0051 row 10) --------------------------------------


def _legacy(where: dict[str, Path], path: Path, inode: int, offset: int) -> None:
    """A `checkpoints` row as the version before left it."""
    with sqlite3.connect(where["data"] / "meta.sqlite") as con:
        con.execute(
            "INSERT OR REPLACE INTO checkpoints (source_id, path, inode, offset, csv_header,"
            " skip_to_newline, updated_at) VALUES (?, ?, ?, ?, NULL, 0, ?)",
            ("linux_auth", str(path), inode, offset, "2026-10-09T00:00:00+00:00"),
        )


def test_at_the_update_nothing_is_read_twice(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1) + LINE.format(2, 2) + LINE.format(3, 3))
    _file(store, f)
    _legacy(env, f, f.stat().st_ino, len(LINE.format(1, 1)) * 2)  # two lines read before
    assert svc.run_once() == 1
    assert count(env) == 1


def test_an_old_row_whose_path_has_another_file_now_is_not_used(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1) + LINE.format(2, 2))
    _file(store, f)
    _legacy(env, f, f.stat().st_ino + 1, len(LINE.format(1, 1)))
    assert svc.run_once() == 2


def test_old_rows_are_copied_once_only(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1))
    _file(store, f)
    assert svc.run_once() == 1
    # A stale row planted after the copy ran must never be taken up, on this or a later
    # start: positions come from `file_positions` only.
    f.unlink()
    write(f, LINE.format(2, 2) + LINE.format(3, 3), mode="w")
    _legacy(env, f, f.stat().st_ino, len(LINE.format(2, 2)))
    svc2, _ = service(env)
    assert svc2.run_once() == 2


def test_the_old_table_is_still_written_so_going_back_reads_on(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1) + LINE.format(2, 2))
    _file(store, f)
    assert svc.run_once() == 2
    with sqlite3.connect(env["data"] / "meta.sqlite") as con:
        rows = con.execute("SELECT path, inode, offset FROM checkpoints").fetchall()
        kept = con.execute("SELECT path, offset FROM file_positions").fetchall()
    assert rows == [(str(f), f.stat().st_ino, f.stat().st_size)]
    assert kept == [(str(f), f.stat().st_size)]


# --- review of #579 ------------------------------------------------------------------------


def test_a_device_number_that_changed_does_not_read_everything_again(
    env: dict[str, Path],  # noqa: F811
) -> None:
    """A device number is not stable across a restart or a remount (LVM, NVMe, NFS, a
    container bind mount). The same inode with matching content is the same file: its
    position moves to the new device number."""
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1) + LINE.format(2, 2))
    _file(store, f)
    assert svc.run_once() == 2
    with sqlite3.connect(env["data"] / "meta.sqlite") as con:
        con.execute("UPDATE file_positions SET device = device + 1")
    write(f, LINE.format(3, 3))
    svc2, _ = service(env)
    assert svc2.run_once() == 1
    assert count(env) == 3
    with sqlite3.connect(env["data"] / "meta.sqlite") as con:
        rows = con.execute("SELECT device, offset FROM file_positions").fetchall()
    assert rows == [(f.stat().st_dev, f.stat().st_size)]  # one record, under the new number


def test_another_devices_record_is_not_taken_when_the_content_differs(
    env: dict[str, Path],  # noqa: F811
) -> None:
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1) + LINE.format(2, 2))
    _file(store, f)
    assert svc.run_once() == 2
    with sqlite3.connect(env["data"] / "meta.sqlite") as con:
        con.execute("UPDATE file_positions SET device = device + 1, tail = 'other'")
    write(f, LINE.format(3, 3))
    svc2, _ = service(env)
    assert svc2.run_once() == 3  # not the same content: a new file, from its start


def test_after_going_back_and_updating_again_nothing_is_read_twice(
    env: dict[str, Path],  # noqa: F811
) -> None:
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1) + LINE.format(2, 2))
    _file(store, f)
    assert svc.run_once() == 2
    # The version before runs for a while: it reads line 3 and moves only `checkpoints`.
    write(f, LINE.format(3, 3))
    with sqlite3.connect(env["data"] / "meta.sqlite") as con:
        con.execute(
            "UPDATE checkpoints SET offset = ?, updated_at = ?",
            (f.stat().st_size, "2026-10-11T00:00:00+00:00"),  # after this version last ran
        )
    svc2, _ = service(env)
    assert svc2.run_once() == 0
    write(f, LINE.format(4, 4))
    assert (
        svc2.run_once() == 1 and count(env) == 3
    )  # line 3 is the older version's, not stored here


def test_a_file_unreadable_at_the_update_keeps_its_old_position(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1) + LINE.format(2, 2))
    _file(store, f)
    _legacy(env, f, f.stat().st_ino, f.stat().st_size)
    f.chmod(0o000)
    try:
        assert svc.run_once() == 0
    finally:
        f.chmod(0o644)
    # Readable again, on a later pass or after a restart: still not read twice.
    assert svc.run_once() == 0
    svc2, _ = service(env)
    assert svc2.run_once() == 0
    write(f, LINE.format(3, 3))
    assert svc2.run_once() == 1


def test_a_source_deleted_and_added_again_starts_afresh(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1) + LINE.format(2, 2))
    _file(store, f)
    assert svc.run_once() == 2
    store.delete("linux_auth")
    with sqlite3.connect(env["data"] / "meta.sqlite") as con:
        assert con.execute("SELECT count(*) FROM file_positions").fetchone() == (0,)
    _file(store, f)
    assert svc.run_once() == 2  # as before ADR-0051: a new source reads its file


# --- second review of #579 -----------------------------------------------------------------


def test_a_push_sources_spool_file_is_not_read_again_at_the_update(env: dict[str, Path]) -> None:  # noqa: F811
    """OTLP spool files are text files too: their old rows are taken over like any other."""
    from app.ingest.sources import SourceStore, spool_name
    from app.ingest.watcher import IngestService
    from app.meta.db import MetaDB
    from tests.integration.test_sources import NOW

    meta = MetaDB(env["data"] / "meta.sqlite")
    spool = env["root"] / "spool"
    store = SourceStore(meta, allowed_roots=[env["logs"]], spool_root=spool)
    svc = IngestService(store, meta, env["data"] / "lake", clock=lambda: NOW)
    store.add(SourceConfig(source_id="otel_in", format="json", kind="otlp"))
    (spool / "otel_in").mkdir(parents=True)
    f = spool / "otel_in" / spool_name(NOW, "otlp")
    write(f, '{"message": "one"}\n{"message": "two"}\n')
    with sqlite3.connect(env["data"] / "meta.sqlite") as con:
        con.execute(
            "INSERT INTO checkpoints (source_id, path, inode, offset, csv_header,"
            " skip_to_newline, updated_at) VALUES (?, ?, ?, ?, NULL, 0, ?)",
            ("otel_in", str(f), f.stat().st_ino, f.stat().st_size, "2026-10-09T00:00:00+00:00"),
        )
    assert svc.run_once() == 0
    write(f, '{"message": "three"}\n')
    assert svc.run_once() == 1


def test_a_file_missing_at_the_update_keeps_its_old_position(env: dict[str, Path]) -> None:  # noqa: F811
    """A folder not mounted yet at the first pass: its files are not read from 0 later."""
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1) + LINE.format(2, 2))
    store.add(
        SourceConfig(source_id="linux_auth", format="syslog", path=str(env["logs"]), glob="*.log")
    )
    _legacy(env, f, f.stat().st_ino, f.stat().st_size)
    away = env["root"] / "away.log"
    f.rename(away)
    assert svc.run_once() == 0
    away.rename(f)
    assert svc.run_once() == 0
    write(f, LINE.format(3, 3))
    assert svc.run_once() == 1


def test_a_device_change_together_with_a_rotation(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    logs = env["logs"]
    f = logs / "app.log"
    write(f, LINE.format(1, 1) + LINE.format(2, 2))
    _folder(store, logs)
    assert svc.run_once() == 2
    with sqlite3.connect(env["data"] / "meta.sqlite") as con:
        con.execute("UPDATE file_positions SET device = device + 1")
    f.rename(logs / "app.log.1")
    write(f, LINE.format(3, 3), mode="w")
    svc2, _ = service(env)
    assert svc2.run_once() == 1  # the renamed copy is known by its content, not read again
    with sqlite3.connect(env["data"] / "meta.sqlite") as con:
        devices = {r[0] for r in con.execute("SELECT device FROM file_positions")}
    assert devices == {f.stat().st_dev}  # the record under the old number is gone


# --- third review of #579 ------------------------------------------------------------------


def _ticking(env: dict[str, Path]) -> tuple[Any, Any, list[Any]]:  # noqa: F811
    """A service whose clock moves a millisecond per reading, as a real one does; the list
    holds the time to add (tests move it forward)."""
    from datetime import timedelta

    from app.ingest.sources import SourceStore
    from app.ingest.watcher import IngestService
    from app.meta.db import MetaDB
    from tests.integration.test_sources import NOW

    ticks = [0]
    ahead: list[Any] = [timedelta(0)]

    def clock() -> Any:
        ticks[0] += 1
        return NOW + ahead[0] + timedelta(milliseconds=ticks[0])

    meta = MetaDB(env["data"] / "meta.sqlite")
    store = SourceStore(meta, allowed_roots=[env["logs"]])
    return IngestService(store, meta, env["data"] / "lake", clock=clock), store, ahead


def test_a_changed_device_number_leaves_one_record_with_a_running_clock(
    env: dict[str, Path],  # noqa: F811
) -> None:
    svc, store, _ = _ticking(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1) + LINE.format(2, 2))
    _file(store, f)
    assert svc.run_once() == 2
    with sqlite3.connect(env["data"] / "meta.sqlite") as con:
        # The two rows of one save carry one time: a newer `checkpoints` row can only be
        # an older version's.
        assert (
            con.execute("SELECT updated_at FROM file_positions").fetchall()
            == con.execute("SELECT updated_at FROM checkpoints").fetchall()
        )
        con.execute("UPDATE file_positions SET device = device + 1")
    write(f, LINE.format(3, 3))
    svc2, _, _ = _ticking(env)
    assert svc2.run_once() == 1
    with sqlite3.connect(env["data"] / "meta.sqlite") as con:
        rows = con.execute("SELECT device, offset FROM file_positions").fetchall()
    assert rows == [(f.stat().st_dev, f.stat().st_size)]


def test_a_file_owed_from_the_update_costs_nothing_until_it_is_listed(
    env: dict[str, Path],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A row main never removed (its file was deleted long ago) is owed, since it cannot
    be told from a folder that is not mounted. It is looked at again only when a file of
    that name is listed, and given up after seven days."""
    from datetime import timedelta

    svc, store, ahead = _ticking(env)
    logs = env["logs"]
    _folder(store, logs)
    gone = logs / "gone.log"
    _legacy(env, gone, 12345, 10)
    calls: list[bool] = []
    real = svc._positions.take_checkpoints

    def counting(sources: set[str], roots: list[Path], start: bool) -> set[tuple[str, str]]:
        calls.append(start)
        return real(sources, roots, start)

    monkeypatch.setattr(svc._positions, "take_checkpoints", counting)
    for _ in range(5):
        svc.run_once()
    assert calls == [True]  # the start only
    ahead[0] = timedelta(days=8)
    write(gone, LINE.format(1, 1))  # a new file of that name, past the seven days
    assert svc.run_once() == 1
    assert calls == [True, False]
    with sqlite3.connect(env["data"] / "meta.sqlite") as con:
        assert con.execute("SELECT value FROM one_time_fixes").fetchall() == [("[]",)]
    svc.run_once()
    assert calls == [True, False]  # nothing is owed any more


def test_the_most_recently_read_files_are_owed_first(
    env: dict[str, Path],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ingest import positions

    monkeypatch.setattr(positions, "MAX_OWED", 1)
    svc, store = service(env)
    logs = env["logs"]
    _folder(store, logs)
    _legacy(env, logs / "old.log", 111, 10)
    _legacy(env, logs / "recent.log", 222, 10)
    with sqlite3.connect(env["data"] / "meta.sqlite") as con:
        con.execute(
            "UPDATE checkpoints SET updated_at = '2026-10-09T12:00:00+00:00' WHERE path LIKE ?",
            ("%recent.log",),
        )
    svc.run_once()
    with sqlite3.connect(env["data"] / "meta.sqlite") as con:
        (value,) = con.execute("SELECT value FROM one_time_fixes").fetchone()
    assert "recent.log" in value and "old.log" not in value


# --- fourth review of #579 -----------------------------------------------------------------


def test_owed_files_that_stay_unreadable_are_tried_once_a_pass(
    env: dict[str, Path],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, store = service(env)
    logs = env["logs"]
    _folder(store, logs)
    files = [logs / f"f{i}.log" for i in range(4)]
    for f in files:
        write(f, LINE.format(1, 1))
        _legacy(env, f, f.stat().st_ino, f.stat().st_size)
        f.chmod(0o000)
    calls: list[bool] = []
    real = svc._positions.take_checkpoints

    def counting(sources: set[str], roots: list[Path], start: bool) -> set[tuple[str, str]]:
        calls.append(start)
        return real(sources, roots, start)

    monkeypatch.setattr(svc._positions, "take_checkpoints", counting)
    try:
        svc.run_once()
        svc.run_once()
        svc.run_once()
    finally:
        for f in files:
            f.chmod(0o644)
    assert calls == [True, False, False]  # the start, then one look a pass, not one a file
    assert svc.run_once() == 0  # readable now: every old position is taken, nothing twice


def test_an_empty_files_record_does_not_survive_a_device_change(env: dict[str, Path]) -> None:  # noqa: F811
    """A record at offset 0 matches any content. Left under the old device number, it
    would send the file back to its start if that number ever returned."""
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, "")
    _file(store, f)
    assert svc.run_once() == 0
    with sqlite3.connect(env["data"] / "meta.sqlite") as con:
        con.execute("UPDATE file_positions SET device = device + 1")
    write(f, LINE.format(1, 1) + LINE.format(2, 2))
    svc2, _ = service(env)
    assert svc2.run_once() == 2
    with sqlite3.connect(env["data"] / "meta.sqlite") as con:
        rows = con.execute("SELECT device, offset FROM file_positions").fetchall()
    assert rows == [(f.stat().st_dev, f.stat().st_size)]
