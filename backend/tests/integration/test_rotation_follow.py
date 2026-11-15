"""One read position per file (ADR-0051, D250), part 2: the watcher keeps the files it reads
open for a while, so a file renamed or deleted under a single-file source is still read to
its end, and a last line without its newline is held until the newline arrives, the file is
rotated, or 5 minutes pass, and is then stored as `parse_status=partial`. Never dropped."""

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from app.engine.duckdb import QueryEngine, QueryScope
from app.ingest import handles
from app.ingest.sources import SourceConfig, SourceStore
from app.ingest.watcher import IngestService
from app.meta.db import MetaDB
from tests.integration.test_sources import LINE, NOW, count, env, service, write  # noqa: F401

HALF = "<38>Oct  9 20:41:05 bastion sshd[5]: half"


def _file(store: Any, f: Path) -> None:
    store.add(SourceConfig(source_id="linux_auth", format="syslog", path=str(f)))


def _moving(env: dict[str, Path]) -> tuple[Any, Any, list[timedelta]]:  # noqa: F811
    """A service whose clock the test moves forward."""
    ahead = [timedelta(0)]
    meta = MetaDB(env["data"] / "meta.sqlite")
    store = SourceStore(meta, allowed_roots=[env["logs"]])
    svc = IngestService(store, meta, env["data"] / "lake", clock=lambda: NOW + ahead[0])
    return svc, store, ahead


def _partial(env: dict[str, Path]) -> list[str]:  # noqa: F811
    res = QueryEngine(env["data"] / "lake").run(
        "SELECT raw FROM events WHERE parse_status = 'partial' ORDER BY raw",
        QueryScope(sources=None),
    )
    return [str(r[0]) for r in res.rows]


# --- following a rename ------------------------------------------------------------------


def test_lines_written_just_before_a_rename_are_not_lost(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1))
    _file(store, f)
    assert svc.run_once() == 1
    write(f, LINE.format(2, 2))  # after the last pass, before the rotation
    f.rename(env["logs"] / "auth.log.1")
    write(f, LINE.format(3, 3), mode="w")
    assert svc.run_once() == 2
    assert count(env) == 3
    assert svc.run_once() == 0


def test_the_tail_of_a_renamed_file_is_stored_once_while_the_new_file_is_empty(
    env: dict[str, Path],  # noqa: F811
) -> None:
    """logrotate `create`: the new file exists but nothing has been written to it yet."""
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1))
    _file(store, f)
    assert svc.run_once() == 1
    write(f, LINE.format(2, 2))
    f.rename(env["logs"] / "auth.log.1")
    write(f, "", mode="w")
    assert [svc.run_once() for _ in range(4)] == [1, 0, 0, 0]
    assert count(env) == 2
    write(f, LINE.format(3, 3))
    assert svc.run_once() == 1


def test_the_tail_is_read_while_the_new_file_cannot_be_opened(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1))
    _file(store, f)
    assert svc.run_once() == 1
    write(f, LINE.format(2, 2))
    f.rename(env["logs"] / "auth.log.1")
    write(f, LINE.format(3, 3), mode="w")
    f.chmod(0o000)
    try:
        assert [svc.run_once(), svc.run_once()] == [1, 0]  # the tail, once
        assert "Cannot read" in (svc.status()["linux_auth"].error or "")
    finally:
        f.chmod(0o644)
    assert svc.run_once() == 1 and count(env) == 3


def test_a_deleted_files_unread_lines_are_still_read(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1))
    _file(store, f)
    assert svc.run_once() == 1
    write(f, LINE.format(2, 2))
    f.unlink()
    write(f, LINE.format(3, 3), mode="w")
    assert svc.run_once() == 2 and count(env) == 3


def test_a_chain_of_rotations_on_a_single_file_source(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    logs = env["logs"]
    f = logs / "auth.log"
    write(f, LINE.format(1, 1))
    _file(store, f)
    assert svc.run_once() == 1
    for n in (2, 3, 4):
        write(f, LINE.format(n, n))  # unread when the names shift
        if (logs / "auth.log.1").exists():
            (logs / "auth.log.1").rename(logs / "auth.log.2")
        f.rename(logs / "auth.log.1")
        write(f, LINE.format(n + 10, n + 10), mode="w")
        assert svc.run_once() == 2
    assert count(env) == 7 and svc.run_once() == 0


def test_a_handle_is_closed_once_the_renamed_file_is_read_to_its_end(
    env: dict[str, Path],  # noqa: F811
) -> None:
    svc, store, ahead = _moving(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1))
    _file(store, f)
    svc.run_once()
    assert len(svc._handles) == 1
    f.rename(env["logs"] / "auth.log.1")
    write(f, LINE.format(2, 2), mode="w")
    svc.run_once()
    assert len(svc._handles) == 2  # the new file's, and the old one for 30 seconds more
    ahead[0] = timedelta(seconds=31)
    svc.run_once()
    assert [(h.path.name, h.gone_at) for h in svc._handles.of("linux_auth")] == [
        ("auth.log", None)
    ]  # the new file's; the old one is closed


def test_a_handle_not_read_from_for_five_minutes_is_closed(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store, ahead = _moving(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1))
    _file(store, f)
    svc.run_once()
    ahead[0] = timedelta(minutes=4)
    svc.run_once()
    assert len(svc._handles) == 1
    ahead[0] = timedelta(minutes=6)
    svc.run_once()
    assert len(svc._handles) == 0
    write(f, LINE.format(2, 2))
    assert svc.run_once() == 1 and len(svc._handles) == 1  # read again, held again


def test_no_more_handles_than_the_limit_oldest_closed_first(
    env: dict[str, Path],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(handles, "MAX_HANDLES", 2)
    svc, store, ahead = _moving(env)
    logs = env["logs"]
    store.add(SourceConfig(source_id="linux_auth", format="syslog", path=str(logs), glob="*.log"))
    for i, name in enumerate(("a.log", "b.log", "c.log")):
        write(logs / name, LINE.format(1, 1))
        ahead[0] = timedelta(seconds=i)  # read one after another: a.log is the oldest
        assert svc.run_once() == 1
    assert sorted(h.path.name for h in svc._handles.of("linux_auth")) == ["b.log", "c.log"]
    # A file whose handle was closed is handled as after a restart (ADR-0051 row 4): what
    # was written just before its rename is not read unless the source lists the new name.
    write(logs / "a.log", LINE.format(2, 2))
    (logs / "a.log").rename(logs / "a.old")
    write(logs / "b.log", LINE.format(3, 3))
    (logs / "b.log").rename(logs / "b.old")
    assert svc.run_once() == 1  # b's tail, through its handle
    assert count(env) == 4


def test_after_a_restart_a_renamed_files_tail_is_the_known_limit(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1))
    _file(store, f)
    assert svc.run_once() == 1
    write(f, LINE.format(2, 2))
    f.rename(env["logs"] / "auth.log.1")
    write(f, LINE.format(3, 3), mode="w")
    svc2, _ = service(env)  # the handles are gone with the process
    assert svc2.run_once() == 1 and count(env) == 2


def test_a_failed_save_while_following_does_not_store_lines_twice(
    env: dict[str, Path],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1))
    _file(store, f)
    assert svc.run_once() == 1
    write(f, LINE.format(2, 2))
    f.rename(env["logs"] / "auth.log.1")
    write(f, "", mode="w")
    real = svc._positions.save
    failing = [True]

    def save(pos: Any, con: Any = None, replaces: Any = None, now: Any = None) -> None:
        if failing[0] and pos.path.endswith("auth.log") and pos.offset > len(LINE.format(1, 1)):
            raise OSError("disk full")
        real(pos, con, replaces, now)

    monkeypatch.setattr(svc._positions, "save", save)
    svc.run_once()
    assert count(env) == 1  # written, not saved, taken back
    failing[0] = False
    assert svc.run_once() == 1 and count(env) == 2


# --- the last line without its newline -----------------------------------------------------


def test_a_part_line_is_stored_as_partial_when_the_file_is_rotated(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store, ahead = _moving(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1) + HALF)
    _file(store, f)
    assert [svc.run_once(), svc.run_once()] == [1, 0]  # held: the newline may still come
    f.rename(env["logs"] / "auth.log.1")
    write(f, LINE.format(2, 2), mode="w")
    assert svc.run_once() == 1 and _partial(env) == []  # the old file is held 30 seconds
    ahead[0] = timedelta(seconds=31)
    assert svc.run_once() == 1  # closed: its part line is stored
    assert _partial(env) == [HALF]
    assert count(env) == 3 and svc.run_once() == 0


def test_a_part_line_is_stored_as_partial_after_five_minutes_without_growth(
    env: dict[str, Path],  # noqa: F811
) -> None:
    svc, store, ahead = _moving(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1) + HALF)
    _file(store, f)
    assert svc.run_once() == 1
    ahead[0] = timedelta(minutes=4)
    assert svc.run_once() == 0 and _partial(env) == []
    ahead[0] = timedelta(minutes=6)
    assert svc.run_once() == 1
    assert _partial(env) == [HALF]
    assert svc.run_once() == 0  # once
    # Never dropped, and never stored twice: what is written after it is read on its own.
    write(f, " done\n" + LINE.format(2, 2))
    assert svc.run_once() == 2 and count(env) == 4


def test_a_part_line_that_keeps_growing_is_not_cut(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store, ahead = _moving(env)
    f = env["logs"] / "auth.log"
    write(f, HALF)
    _file(store, f)
    assert svc.run_once() == 0
    ahead[0] = timedelta(minutes=4)
    write(f, " and more")
    assert svc.run_once() == 0
    ahead[0] = timedelta(minutes=8)  # 4 minutes since it last grew
    assert svc.run_once() == 0
    write(f, " done\n")
    assert svc.run_once() == 1 and _partial(env) == []


# --- the warning is exact while the file is held -------------------------------------------


def test_a_refill_in_place_is_said_plainly_while_the_file_is_held(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1) + LINE.format(2, 2))
    _file(store, f)
    assert svc.run_once() == 2
    write(f, LINE.format(3, 3) + LINE.format(4, 4) + LINE.format(5, 5), mode="w")
    assert svc.run_once() == 3
    (warning,) = svc.status()["linux_auth"].warnings
    # The watcher still holds the file, so it is the same file: not "or replaced".
    assert "emptied and refilled in place" in warning and "replaced" not in warning


def test_a_rename_and_create_never_warns(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1) + LINE.format(2, 2))
    _file(store, f)
    assert svc.run_once() == 2
    f.rename(env["logs"] / "auth.log.1")
    write(f, LINE.format(3, 3), mode="w")
    assert svc.run_once() == 1
    assert svc.status()["linux_auth"].warnings == ()


# --- review of #586 ----------------------------------------------------------------------


def test_a_csv_part_line_is_stored_not_taken_for_the_header(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store, ahead = _moving(env)
    f = env["logs"] / "rows.csv"
    write(f, "time,user,action\n2026-10-09T20:41:01Z,alice,login\n2026-10-09T20:41:02Z,bob,log")
    store.add(SourceConfig(source_id="linux_auth", format="csv", path=str(f)))
    assert svc.run_once() == 1
    ahead[0] = timedelta(minutes=6)
    assert svc.run_once() == 1
    assert _partial(env) == ["2026-10-09T20:41:02Z,bob,log"]
    write(f, "out\n2026-10-09T20:41:03Z,carol,login\n")
    assert svc.run_once() == 2 and count(env) == 4  # the header is still the header


def test_the_tail_is_read_while_the_name_points_to_no_file(env: dict[str, Path]) -> None:  # noqa: F811
    """Renamed away and nothing created yet: the source's path does not exist, and the
    held file is still read to its end."""
    svc, store, ahead = _moving(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1))
    _file(store, f)
    assert svc.run_once() == 1
    write(f, LINE.format(2, 2))
    f.rename(env["logs"] / "auth.log.1")
    assert [svc.run_once(), svc.run_once()] == [1, 0]
    assert count(env) == 2
    assert "does not exist" in (svc.status()["linux_auth"].error or "")  # still said
    ahead[0] = timedelta(seconds=31)
    svc.run_once()
    assert len(svc._handles) == 0
    write(f, LINE.format(3, 3), mode="w")
    assert svc.run_once() == 1 and count(env) == 3


def test_a_part_line_that_does_not_parse_is_still_partial(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store, ahead = _moving(env)
    f = env["logs"] / "app.jsonl"
    write(f, '{"message": "one"}\n{"message": "tw')
    store.add(SourceConfig(source_id="linux_auth", format="json", path=str(f)))
    assert svc.run_once() == 1
    ahead[0] = timedelta(minutes=6)
    assert svc.run_once() == 1
    res = QueryEngine(env["data"] / "lake").run(
        "SELECT parse_status, parse_errors, raw FROM events WHERE raw LIKE '%tw'",
        QueryScope(sources=None),
    )
    status, errors, raw = res.rows[0]
    assert status == "partial" and str(errors).startswith("no_newline") and raw == '{"message": "tw'


def test_an_over_long_part_line_is_marked_truncated(
    env: dict[str, Path],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ingest import watcher

    monkeypatch.setattr(watcher, "MAX_LINE", 64)
    svc, store, ahead = _moving(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1) + HALF + "x" * 200)
    _file(store, f)
    assert svc.run_once() == 1
    ahead[0] = timedelta(minutes=6)
    assert svc.run_once() == 1
    res = QueryEngine(env["data"] / "lake").run(
        "SELECT parse_errors, length(raw) FROM events WHERE parse_errors LIKE '%no_newline%'",
        QueryScope(sources=None),
    )
    errors, size = res.rows[0]
    assert "no_newline" in str(errors) and "truncated" in str(errors) and size == 64
    assert svc.run_once() == 0  # the whole part line was used, not only its first 64 bytes


def test_a_renamed_file_that_cannot_be_read_to_its_end_is_closed_after_five_minutes(
    env: dict[str, Path],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ingest import watcher

    line = LINE.format(1, 1)
    svc, store, ahead = _moving(env)
    f = env["logs"] / "auth.log"
    write(f, line)
    _file(store, f)
    assert svc.run_once() == 1
    write(f, line * 40)
    f.rename(env["logs"] / "auth.log.1")
    write(f, "", mode="w")
    monkeypatch.setattr(watcher, "READ_LIMIT", len(line) + 5)  # one line a pass
    assert svc.run_once() == 1
    ahead[0] = timedelta(minutes=4)
    assert svc.run_once() == 1  # still held, still read
    ahead[0] = timedelta(minutes=6)  # five minutes after the rename was seen
    assert svc.run_once() == 1  # read once more, then closed though not at its end
    assert all(h.gone_at is None for h in svc._handles.of("linux_auth"))
    assert svc.run_once() == 0


def test_the_handles_of_a_source_turned_off_or_deleted_are_closed(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    logs = env["logs"]
    write(logs / "a.log", LINE.format(1, 1))
    write(logs / "b.log", LINE.format(1, 1))
    store.add(SourceConfig(source_id="linux_auth", format="syslog", path=str(logs / "a.log")))
    store.add(SourceConfig(source_id="other", format="syslog", path=str(logs / "b.log")))
    svc.run_once()
    assert len(svc._handles) == 2
    import sqlite3

    with sqlite3.connect(env["data"] / "meta.sqlite") as con:  # turned off
        con.execute("UPDATE sources SET enabled = 0 WHERE source_id = 'linux_auth'")
    svc.run_once()
    assert [h.path.name for h in svc._handles.of("other")] == ["b.log"] and len(svc._handles) == 1
    store.delete("other")
    svc.run_once()
    assert len(svc._handles) == 0


# --- second review of #586 -----------------------------------------------------------------


def test_a_held_file_that_cannot_be_read_does_not_stop_the_others(
    env: dict[str, Path],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A read through a held handle can fail (a file deleted on a file server, a disk
    error): that file is given up, the source is not in error, the rest is followed."""
    import errno

    from app.ingest import watcher

    svc, store = service(env)
    logs = env["logs"]
    store.add(SourceConfig(source_id="linux_auth", format="syslog", path=str(logs), glob="*.log"))
    for name in ("a.log", "b.log"):
        write(logs / name, LINE.format(1, 1))
    assert svc.run_once() == 2
    for name in ("a.log", "b.log"):
        write(logs / name, LINE.format(2, 2))
        (logs / name).rename(logs / (name + ".old"))
    write(logs / "c.log", LINE.format(3, 3))
    real = watcher.same_content
    broken = next(f for f, h in svc._handles.items("linux_auth") if h.path.name == "a.log")

    def failing(fh: Any, pos: Any, size: int) -> bool:
        if (pos.source_id, pos.device, pos.inode) == broken:
            raise OSError(errno.ESTALE, "stale file handle")
        return real(fh, pos, size)

    monkeypatch.setattr(watcher, "same_content", failing)
    assert svc.run_once() == 2  # c.log, and b.log's tail
    st = svc.status()["linux_auth"]
    assert st.error is None and st.files == 1
    # a.log's handle is given up; b.log's is held 30 seconds more.
    assert sorted(h.path.name for h in svc._handles.of("linux_auth")) == ["b.log", "c.log"]
    assert svc.run_once() == 0


# --- held 30 seconds after the end (owner, 2026-11-13; D252) -----------------------------


def _rotated(env: dict[str, Path]) -> tuple[Any, list[timedelta], Path, Path]:  # noqa: F811
    """A single-file source read once, then rotated with `create`: the old file is
    `auth.log.1`, which the source does not list, and a program may still write to it."""
    svc, store, ahead = _moving(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1))
    _file(store, f)
    assert svc.run_once() == 1
    old = env["logs"] / "auth.log.1"
    f.rename(old)
    write(f, "", mode="w")
    assert svc.run_once() == 0  # the rename is seen; the old file is at its end
    return svc, ahead, f, old


def test_what_a_program_still_writes_to_the_old_file_is_read(env: dict[str, Path]) -> None:  # noqa: F811
    """Until it is told to reopen its log, a program keeps writing to the renamed file."""
    svc, ahead, _, old = _rotated(env)
    ahead[0] = timedelta(seconds=10)
    write(old, LINE.format(2, 2))
    assert svc.run_once() == 1
    ahead[0] = timedelta(seconds=25)
    write(old, LINE.format(3, 3))
    assert svc.run_once() == 1 and count(env) == 3
    assert [h.path.name for h in svc._handles.of("linux_auth") if h.gone_at] == ["auth.log"]


def test_a_line_finished_in_the_old_file_within_the_hold_is_one_whole_line(
    env: dict[str, Path],  # noqa: F811
) -> None:
    svc, ahead, _, old = _rotated(env)
    ahead[0] = timedelta(seconds=5)
    write(old, HALF)
    assert svc.run_once() == 0  # held: not stored as a part line while the file is held
    ahead[0] = timedelta(seconds=20)
    write(old, " done\n")
    assert svc.run_once() == 1
    assert _partial(env) == [] and count(env) == 2


def test_the_old_file_is_closed_thirty_seconds_after_it_was_read_to_its_end(
    env: dict[str, Path],  # noqa: F811
) -> None:
    svc, ahead, _, old = _rotated(env)
    ahead[0] = timedelta(seconds=10)
    write(old, LINE.format(2, 2) + HALF)
    assert svc.run_once() == 1
    ahead[0] = timedelta(seconds=25)
    assert svc.run_once() == 0 and _partial(env) == []  # still held
    ahead[0] = timedelta(seconds=31)  # 30 seconds after it was first read to its end
    assert svc.run_once() == 1  # closed, and the part line is stored
    assert _partial(env) == [HALF]
    assert [h for h in svc._handles.of("linux_auth") if h.gone_at] == []
    write(old, " too late\n")  # after the close: the known limit
    assert svc.run_once() == 0 and count(env) == 3


def test_a_file_that_keeps_growing_is_still_closed_after_thirty_seconds(
    env: dict[str, Path],  # noqa: F811
) -> None:
    svc, ahead, _, old = _rotated(env)
    for i in (1, 2, 3, 4):  # a line every 10 seconds
        ahead[0] = timedelta(seconds=10 * i)
        write(old, LINE.format(i, i))
        svc.run_once()
    # Read at 10, 20, and at 30 seconds, when it is closed; the line at 40 is not.
    assert count(env) == 4
    assert [h for h in svc._handles.of("linux_auth") if h.gone_at] == []


def test_a_part_line_is_stored_at_the_five_minute_cap(
    env: dict[str, Path],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A renamed file not read to its end before the cap: at the cap it is read once more
    and closed, and when that read reaches its end the last line is stored."""
    from app.ingest import watcher

    line = LINE.format(1, 1)
    svc, store, ahead = _moving(env)
    f = env["logs"] / "auth.log"
    write(f, line)
    _file(store, f)
    assert svc.run_once() == 1
    write(f, line * 3 + HALF)
    f.rename(env["logs"] / "auth.log.1")
    write(f, "", mode="w")
    monkeypatch.setattr(watcher, "READ_LIMIT", len(line) + 5)  # one line a pass
    assert svc.run_once() == 1
    monkeypatch.undo()
    ahead[0] = timedelta(minutes=6)
    assert svc.run_once() == 3  # the two lines left, and the part line
    assert _partial(env) == [HALF]
    assert [h for h in svc._handles.of("linux_auth") if h.gone_at] == []


def test_a_name_that_points_to_the_file_again_is_an_ordinary_held_file(
    env: dict[str, Path],  # noqa: F811
) -> None:
    """Away for one pass and back (a tool that moves a file and moves it back): the file
    is closed after 5 idle minutes like any other, and a later rotation gets its hold."""
    svc, store, ahead = _moving(env)
    f = env["logs"] / "auth.log"
    aside = env["logs"] / "auth.aside"
    write(f, LINE.format(1, 1))
    _file(store, f)
    assert svc.run_once() == 1
    f.rename(aside)
    svc.run_once()
    aside.rename(f)
    ahead[0] = timedelta(seconds=5)
    svc.run_once()
    assert [h.gone_at for h in svc._handles.of("linux_auth")] == [None]
    ahead[0] = timedelta(minutes=4)
    write(f, LINE.format(2, 2))
    assert svc.run_once() == 1
    # A real rotation now: what is written to the old file 4 seconds later is read.
    f.rename(env["logs"] / "auth.log.1")
    write(f, "", mode="w")
    svc.run_once()
    ahead[0] = timedelta(minutes=4, seconds=4)
    write(env["logs"] / "auth.log.1", LINE.format(3, 3))
    assert svc.run_once() == 1 and count(env) == 3
    ahead[0] = timedelta(minutes=12)
    svc.run_once()
    assert len(svc._handles) == 0  # idle: closed


def test_a_renamed_file_is_closed_at_its_time_even_when_storing_fails(
    env: dict[str, Path],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, ahead, _, old = _rotated(env)
    write(old, LINE.format(2, 2))

    def failing(source_id: str, rows: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(svc, "_write", failing)
    ahead[0] = timedelta(seconds=10)
    svc.run_once()
    assert [h for h in svc._handles.of("linux_auth") if h.gone_at]  # kept: it may recover
    ahead[0] = timedelta(minutes=6)
    svc.run_once()
    assert [h for h in svc._handles.of("linux_auth") if h.gone_at] == []
