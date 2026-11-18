"""Every line of one file stored exactly twice (owner report, 2026-11-17): each way ingest
could read the same lines twice, on real ingest code paths. One file has one reader per
install: a file another source already reads is not read again, and Health says so,
naming both sources; when the reader stops, the next carries on from where it stopped. Two different files with the same lines (a syslog daemon that writes
a line to two files) are two files: both are read, and nothing is deduplicated."""

import os
import random
import shutil
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from app.engine.duckdb import QueryEngine, QueryScope
from app.engine.guard import guard
from app.ingest.sources import SourceConfig, SourceStore
from app.ingest.watcher import IngestService
from app.meta.db import MetaDB
from tests.integration.test_sources import LINE, NOW, count, env, service, write  # noqa: F401

BIND = (
    "<30>Oct  9 20:41:{:02d} ns1 named[812]: client @0x7f2a1c0a5b68 10.20.1.5#53212"
    " (www.example.com): query: www.example.com IN A +E(0)K (10.20.0.53)\n"
)
# The owner's check, as the ingest guide gives it ("Lines stored twice"): it runs in Logs
# SQL mode, through the guard, read-only.
GUIDE = Path(__file__).resolve().parents[3] / "docs" / "ingest" / "README.md"
DUPLICATES_SQL = GUIDE.read_text(encoding="utf-8").split("## Lines stored twice", 1)[1]
DUPLICATES_SQL = DUPLICATES_SQL.split("```sql\n", 1)[1].split("```", 1)[0]


def _bind(
    store: Any,
    sid: str,
    path: Path,
    glob: str = "*",
    template_id: str | None = None,
    fmt: str = "syslog",
) -> None:
    store.add(
        SourceConfig(source_id=sid, format=fmt, path=str(path), glob=glob, template_id=template_id)
    )


def _lines(n: int, first: int = 0) -> str:
    return "".join(BIND.format(i) for i in range(first, first + n))


def _shared(svc: Any, sid: str) -> tuple[tuple[str, str], ...]:
    st = svc.status()[sid]
    assert st.warnings == ()  # a shared file is not a reading problem
    return tuple((f, r) for f, r, _ in st.shared)


# --- one source: the same file under two names is one file (ADR-0051) ----------------


def test_a_symlink_and_its_target_in_one_folder_are_read_once(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    f = env["logs"] / "queries.log"
    write(f, _lines(3))
    os.symlink(f, env["logs"] / "query.log")
    _bind(store, "dns", env["logs"])
    assert svc.run_once() == 3
    write(f, _lines(2, 3))
    assert svc.run_once() == 2
    assert count(env) == 5


def test_a_hard_link_in_one_folder_is_read_once(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    f = env["logs"] / "queries.log"
    write(f, _lines(3))
    os.link(f, env["logs"] / "queries.copy")
    _bind(store, "dns", env["logs"])
    assert svc.run_once() == 3
    write(f, _lines(2, 3))
    assert svc.run_once() == 2 and svc.run_once() == 0
    assert count(env) == 5


def test_bind_versions_rotation_matched_by_the_glob_is_read_once(env: dict[str, Path]) -> None:  # noqa: F811
    """BIND's own `versions 3` rotation renames queries.log to queries.log.0 and opens a new
    queries.log; the glob `queries.log*` lists both."""
    svc, store = service(env)
    f = env["logs"] / "queries.log"
    write(f, _lines(3))
    _bind(store, "dns", env["logs"], glob="queries.log*")
    assert svc.run_once() == 3
    write(f, _lines(1, 3))
    f.rename(env["logs"] / "queries.log.0")
    write(f, _lines(2, 4), mode="w")
    assert svc.run_once() == 3
    assert svc.run_once() == 0
    assert count(env) == 6


def test_a_restart_reads_on_from_the_saved_position(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    f = env["logs"] / "queries.log"
    write(f, _lines(3))
    _bind(store, "dns", f)
    assert svc.run_once() == 3
    write(f, _lines(2, 3))
    again, _ = service(env)  # a new process on the same data folder
    assert again.run_once() == 2
    assert count(env) == 5


def test_two_services_on_one_data_folder_take_turns_without_repeating(
    env: dict[str, Path],  # noqa: F811
) -> None:
    """Two ingest loops over one data folder (a second process) read the saved position
    each pass, so passes that take turns do not repeat lines."""
    one, store = service(env)
    two, _ = service(env)
    f = env["logs"] / "queries.log"
    f.touch()
    _bind(store, "dns", f)
    for i in range(4):
        write(f, _lines(2, 2 * i))
        assert (one if i % 2 else two).run_once() == 2
    assert count(env) == 8


# --- two sources over one file: the cause that is in the repository ---------------------


def test_a_folder_source_and_a_file_source_over_one_file_store_each_line_once(
    env: dict[str, Path],  # noqa: F811
) -> None:
    svc, store = service(env)
    f = env["logs"] / "queries.log"
    write(f, _lines(3))
    _bind(store, "dns_all", env["logs"])
    _bind(store, "dns_queries", f)
    assert svc.run_once() == 3
    write(f, _lines(2, 3))
    assert svc.run_once() == 2
    assert count(env) == 5
    # The source whose path names the file reads it; the folder source skips it (D273).
    assert count(env, "source_id = 'dns_queries'") == 5
    assert _shared(svc, "dns_all") == (("queries.log", "dns_queries"),)
    assert svc.status()["dns_all"].read_by == "dns_queries"  # every file it lists
    assert svc.status()["dns_all"].shared[0][2] is False  # less specific: may be removed
    assert _shared(svc, "dns_queries") == () and svc.status()["dns_queries"].read_by is None


def test_a_second_source_through_a_symlinked_folder_does_not_read_again(
    env: dict[str, Path],  # noqa: F811
) -> None:
    svc, store = service(env)
    real = env["logs"] / "named"
    real.mkdir()
    write(real / "queries.log", _lines(3))
    os.symlink(real, env["logs"] / "bind")
    _bind(store, "dns_a", real)
    _bind(store, "dns_b", env["logs"] / "bind" / "queries.log")
    assert svc.run_once() == 3
    assert count(env) == 3 and _shared(svc, "dns_a") == (("queries.log", "dns_b"),)
    assert count(env, "source_id = 'dns_b'") == 3  # its path names the file


def test_a_second_source_over_a_hard_link_does_not_read_again(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    (env["logs"] / "a").mkdir()
    (env["logs"] / "b").mkdir()
    write(env["logs"] / "a" / "queries.log", _lines(3))
    os.link(env["logs"] / "a" / "queries.log", env["logs"] / "b" / "queries.log")
    _bind(store, "dns_a", env["logs"] / "a")
    _bind(store, "dns_b", env["logs"] / "b")
    assert svc.run_once() == 3
    write(env["logs"] / "a" / "queries.log", _lines(1, 3))
    assert svc.run_once() == 1
    assert count(env) == 4 and count(env, "source_id = 'dns_a'") == 4  # added first
    assert svc.status()["dns_b"].shared == (("queries.log", "dns_a", True),)  # a tie


def test_two_sources_already_reading_one_file_go_back_to_one_reader(
    env: dict[str, Path],  # noqa: F811
) -> None:
    """An install that stored each line twice before this fix: both sources have a
    position on the file. From the update on, only the one already reading reads on, also
    after a restart."""
    svc, store = service(env)
    f = env["logs"] / "queries.log"
    write(f, _lines(3))
    _bind(store, "dns_b", f)
    assert svc.run_once() == 3
    # What the version before this fix left: the second source read the whole file too.
    st = f.stat()
    had = svc._positions.get("dns_b", st.st_dev, st.st_ino)
    assert had is not None
    _bind(store, "dns_a", env["logs"])
    svc._positions.save(replace(had, source_id="dns_a"))
    write(f, _lines(2, 3))
    assert svc.run_once() == 2
    assert count(env) == 5
    assert count(env, "source_id = 'dns_b'") == 5 and count(env, "source_id = 'dns_a'") == 0
    again, _ = service(env)  # restarted
    write(f, _lines(1, 5))
    assert again.run_once() == 1 and again.run_once() == 0
    assert count(env, "source_id = 'dns_b'") == 6 and count(env, "source_id = 'dns_a'") == 0


def _raws(env: dict[str, Path]) -> list[str]:  # noqa: F811
    res = QueryEngine(env["data"] / "lake").run("SELECT raw FROM events", QueryScope(sources=None))
    return sorted(str(r[0]) for r in res.rows)


def _takeover(env: dict[str, Path], stop: Callable[[SourceStore, str], None]) -> None:  # noqa: F811
    """Two sources over one file; the reader reads to its end, more lines are written, the
    reader stops, and the other carries on from the furthest position: each line once."""
    svc, store = service(env)
    f = env["logs"] / "queries.log"
    write(f, _lines(3))
    _bind(store, "dns_a", f)
    _bind(store, "dns_b", env["logs"])
    assert svc.run_once() == 3
    assert count(env, "source_id = 'dns_a'") == 3
    write(f, _lines(2, 3))
    assert svc.run_once() == 2
    write(f, _lines(4, 5))
    stop(store, "dns_a")
    assert svc.run_once() == 4
    assert svc.run_once() == 0
    assert _raws(env) == sorted(BIND.format(i).rstrip("\n") for i in range(9))
    assert count(env, "source_id = 'dns_b'") == 4
    assert _shared(svc, "dns_b") == ()  # it reads the file now
    assert svc.status()["dns_b"].read_by is None


def _turn_off(store: SourceStore, sid: str) -> None:
    with store._meta.connect() as con:
        con.execute("UPDATE sources SET enabled = 0 WHERE source_id = ?", (sid,))


def test_a_turned_off_reader_hands_the_file_on_without_repeating(
    env: dict[str, Path],  # noqa: F811
) -> None:
    _takeover(env, _turn_off)


def test_a_deleted_reader_hands_the_file_on_without_repeating(env: dict[str, Path]) -> None:  # noqa: F811
    _takeover(env, lambda store, sid: store.delete(sid))


def test_a_file_the_reader_no_longer_lists_is_carried_on_by_the_other(
    env: dict[str, Path],  # noqa: F811
) -> None:
    """The reader's single file is renamed out of its path (rotated while nothing still
    holds it, for example after a restart); the folder source lists the old file under
    its new name and reads on from where the reader stopped."""
    svc, store = service(env)
    f = env["logs"] / "queries.log"
    write(f, _lines(3))
    _bind(store, "dns_a", f)
    _bind(store, "dns_b", env["logs"])
    assert svc.run_once() == 3
    write(f, _lines(2, 3))
    f.rename(env["logs"] / "queries.log.0")
    f.touch()
    again, _ = service(env)  # restarted: no held file
    assert again.run_once() == 2  # the only source that lists it now
    assert again.run_once() == 0
    assert _raws(env) == sorted(BIND.format(i).rstrip("\n") for i in range(5))


def test_a_source_with_some_files_read_elsewhere_keeps_its_own_state(
    env: dict[str, Path],  # noqa: F811
) -> None:
    svc, store = service(env)
    write(env["logs"] / "queries.log", _lines(3))
    write(env["logs"] / "other.log", _lines(2, 3))
    _bind(store, "dns_a", env["logs"] / "queries.log")
    _bind(store, "dns_b", env["logs"])
    assert svc.run_once() == 5
    st = svc.status()["dns_b"]
    assert st.shared == (("queries.log", "dns_a", False),) and st.read_by is None
    assert count(env, "source_id = 'dns_b'") == 2


def test_two_files_with_the_same_lines_are_both_read(env: dict[str, Path]) -> None:  # noqa: F811
    """A syslog daemon that writes each named line to two files (no `stop` after the rule
    for named): two files, so both are stored. A server setting, not a repeat by ingest."""
    svc, store = service(env)
    write(env["logs"] / "syslog", _lines(3))
    write(env["logs"] / "named.log", _lines(3))
    _bind(store, "dns", env["logs"])
    assert svc.run_once() == 6
    assert _shared(svc, "dns") == ()


# --- the owner's check ---------------------------------------------------------------


def test_the_duplicates_query_passes_the_guard_and_tells_the_causes_apart(
    env: dict[str, Path],  # noqa: F811
) -> None:
    guard(DUPLICATES_SQL, {"events"})  # as typed, with now()
    meta = MetaDB(env["data"] / "meta.sqlite")
    store = SourceStore(meta, allowed_roots=[env["logs"]])
    svc = IngestService(store, meta, env["data"] / "lake", clock=lambda: NOW)
    write(env["logs"] / "syslog", _lines(3))
    write(env["logs"] / "named.log", _lines(3))
    _bind(store, "dns", env["logs"])
    svc.run_once()
    res = QueryEngine(env["data"] / "lake").run(
        DUPLICATES_SQL.replace("now() - INTERVAL 1 DAY", "TIMESTAMPTZ '2000-01-01'"),
        QueryScope(sources=None),
    )
    # One source, two copies with their own event ids, stored in the same pass: one
    # source lists two files with the same lines.
    assert [tuple(r) for r in res.rows] == [("dns", 2, False, 0, 3)]


# --- review of #655 ------------------------------------------------------------------------


def test_after_a_restart_the_source_that_held_the_file_keeps_it(env: dict[str, Path]) -> None:  # noqa: F811
    """The holder survives a restart (CLAUDE.md 2.13): the file does not move to the source
    whose id sorts first, so new lines keep the holder's source id and template."""
    svc, store = service(env)
    f = env["logs"] / "queries.log"
    write(f, _lines(3))
    _bind(store, "dns_z", f, template_id="dns_bind")
    assert svc.run_once() == 3
    _bind(store, "app_all", env["logs"])  # added later, sorts first
    write(f, _lines(2, 3))
    assert svc.run_once() == 2
    assert count(env, "source_id = 'dns_z'") == 5
    for _ in range(2):  # two restarts in a row
        again, _ = service(env)
        write(f, _lines(2, 5))
        assert again.run_once() == 2 and again.run_once() == 0
        assert again.status()["app_all"].read_by == "dns_z"
    assert count(env, "source_id = 'app_all'") == 0
    assert count(env, "source_id = 'dns_z'") == 9
    assert count(env, "template_id = 'dns_bind'") == 9  # the holder's template, every line


def test_a_takeover_after_a_device_number_change_does_not_store_again(
    env: dict[str, Path],  # noqa: F811
) -> None:
    """The takeover finds the old reader's position by the same identity rule as a source's
    own record, a changed device number included (D251)."""
    svc, store = service(env)
    f = env["logs"] / "queries.log"
    write(f, _lines(3))
    _bind(store, "dns_z", f)
    assert svc.run_once() == 3
    _bind(store, "app_all", env["logs"])
    assert svc.run_once() == 0
    # A restart over a remount gives the file another device number (SPEC 3.5).
    with store._meta.connect() as con:
        con.execute("UPDATE file_positions SET device = device + 7")
        con.execute("UPDATE sources SET enabled = 0 WHERE source_id = 'dns_z'")
    again, _ = service(env)
    assert again.run_once() == 0
    write(f, _lines(1, 3))
    assert again.run_once() == 1
    assert count(env) == 4 and count(env, "source_id = 'app_all'") == 1


def _rotate(f: Path, versions: bool, n: int) -> None:
    """logrotate `create` (one rotated copy, `.1`), or BIND `versions` (`.0`, `.1`, ...)."""
    if versions:
        for i in range(n - 1, -1, -1):
            old = f.with_name(f"{f.name}.{i}")
            if old.exists():
                old.rename(f.with_name(f"{f.name}.{i + 1}"))
        f.rename(f.with_name(f"{f.name}.0"))
    else:
        f.rename(f.with_name(f"{f.name}.1"))  # replaces the copy before
    f.touch()


@pytest.mark.parametrize("versions", [False, True])
def test_the_specific_source_keeps_every_line_through_rotations(
    env: dict[str, Path],  # noqa: F811
    versions: bool,
) -> None:
    """The holder is the most specific source (D273), from configuration only: a rotation
    makes a new file with no history, and it still goes to the file source, with its
    template; the folder source over the rotated copies stores nothing."""
    svc, store = service(env)
    f = env["logs"] / "queries.log"
    write(f, _lines(2))
    _bind(store, "dns_z", f, template_id="dns_bind")
    _bind(store, "app_all", env["logs"], glob="*.log*")  # sorts first, matches the copies
    assert svc.run_once() == 2
    n = 2
    for r in range(3):
        write(f, _lines(1, n))  # written before the rename, read through the held file
        _rotate(f, versions, r)
        write(f, _lines(2, n + 1))
        n += 3
        assert svc.run_once() == 3 and svc.run_once() == 0
    assert count(env) == n == count(env, "source_id = 'dns_z'")
    assert count(env, "template_id = 'dns_bind'") == n
    assert svc.status()["dns_z"].shared == ()
    again, _ = service(env)  # and after a restart, nothing moves or repeats
    write(f, _lines(1, n))
    assert again.run_once() == 1 and again.run_once() == 0
    assert count(env, "source_id = 'app_all'") == 0


def test_a_stale_larger_position_after_copytruncate_and_a_restart_is_not_used(
    env: dict[str, Path],  # noqa: F811
) -> None:
    svc, store = service(env)
    f = env["logs"] / "queries.log"
    write(f, _lines(3))
    _bind(store, "dns_z", f)
    assert svc.run_once() == 3
    _bind(store, "app_all", env["logs"])
    st = f.stat()
    had = svc._positions.get("dns_z", st.st_dev, st.st_ino)
    assert had is not None  # the other source once read further (before this fix)
    svc._positions.save(replace(had, source_id="app_all", offset=had.offset + 4096))
    write(f, _lines(2, 3), mode="w")  # copytruncate, then two new lines
    again, _ = service(env)
    assert again.run_once() == 2  # from the start, by the file source
    assert count(env, "source_id = 'dns_z'") == 5 and count(env, "source_id = 'app_all'") == 0


def test_equally_specific_sources_tie_to_the_one_added_first(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    write(env["logs"] / "queries.log", _lines(3))
    _bind(store, "zz_first", env["logs"])  # added first, sorts last
    _bind(store, "aa_second", env["logs"])
    assert svc.run_once() == 3
    assert count(env, "source_id = 'zz_first'") == 3
    assert svc.status()["aa_second"].shared == (("queries.log", "zz_first", True),)
    again, _ = service(env)
    write(env["logs"] / "queries.log", _lines(1, 3))
    assert again.run_once() == 1 and count(env, "source_id = 'zz_first'") == 4


def test_a_holder_that_no_longer_lists_the_file_hands_it_on(
    env: dict[str, Path],  # noqa: F811
) -> None:
    """The holder is whoever lists the file now: when the file source's path names a new
    file, the folder source that lists the old one reads on from where it stopped."""
    svc, store = service(env)
    f = env["logs"] / "queries.log"
    write(f, _lines(3))
    _bind(store, "dns_z", f)
    assert svc.run_once() == 3
    _bind(store, "app_all", env["logs"])
    f.rename(env["logs"] / "queries.log.0")
    f.touch()  # dns_z's path is a new, empty file now
    write(env["logs"] / "queries.log.0", _lines(2, 3))
    again, _ = service(env)  # restarted: nothing held
    assert again.run_once() == 2  # read on from where dns_z stopped
    assert count(env) == 5 and count(env, "source_id = 'app_all'") == 2


# --- third review of #655: one rule for where every read starts (D272) -------------------


def test_a_tail_read_while_the_path_is_missing_is_stored_once_by_the_file_source(
    env: dict[str, Path],  # noqa: F811
) -> None:
    """Renamed, and the new file not there yet during a pass: the file source still reads
    the old file's tail through the file it holds, and nothing is stored twice."""
    svc, store = service(env)
    f = env["logs"] / "queries.log"
    write(f, _lines(2))
    _bind(store, "dns_z", f, template_id="dns_bind")
    _bind(store, "app_all", env["logs"], glob="*.log*")
    assert svc.run_once() == 2
    write(f, _lines(3, 2))  # written before the rename
    f.rename(env["logs"] / "queries.log.1")
    assert svc.run_once() == 3  # a pass while the new file is not there yet
    f.touch()
    write(f, _lines(1, 5))
    assert svc.run_once() == 1 and svc.run_once() == 0
    raws = _raws(env)
    assert len(raws) == len(set(raws)) == 6
    assert count(env, "source_id = 'app_all'") == 0


def test_a_source_added_after_a_delete_reads_the_files_no_source_holds(
    env: dict[str, Path],  # noqa: F811
) -> None:
    """A deleted source's positions go to sources that list the same files then; with none,
    they are dropped, and a source added later reads the files from their start."""
    svc, store = service(env)
    write(env["logs"] / "queries.log", _lines(3))
    _bind(store, "fw", env["logs"])
    assert svc.run_once() == 3
    store.delete("fw")
    _bind(store, "fw_fixed", env["logs"], template_id="dns_bind")
    assert svc.run_once() == 3
    assert count(env, "source_id = 'fw_fixed'") == 3


def test_a_deleted_holders_positions_go_to_the_source_that_lists_the_file(
    env: dict[str, Path],  # noqa: F811
) -> None:
    svc, store = service(env)
    f = env["logs"] / "queries.log"
    write(f, _lines(3))
    _bind(store, "dns_z", f)
    _bind(store, "app_all", env["logs"])
    assert svc.run_once() == 3
    store.delete("dns_z")
    with store._meta.connect() as con:
        assert (
            con.execute(
                "SELECT source_id FROM file_positions WHERE source_id LIKE '%dns_z%'"
            ).fetchall()
            == []
        )
    write(f, _lines(1, 3))
    again, _ = service(env)
    assert again.run_once() == 1  # app_all carries on: no line stored twice
    assert count(env) == 4 and count(env, "source_id = 'app_all'") == 1


SEED = 655
STEPS = 300


HEADER = "user,action"


def _csv_fields_right(env: dict[str, Path]) -> bool:  # noqa: F811
    """Every row the CSV source stored was read with the file's header (fifth review)."""
    res = QueryEngine(env["data"] / "lake").run(
        "SELECT count(*) FILTER (WHERE unmapped NOT LIKE '%\"user\"%'), count(*) FROM events"
        " WHERE source_id = 'c_csv'",
        QueryScope(sources=None),
    )
    return int(res.rows[0][0]) == 0


@pytest.mark.slow  # about 18 s: run by the queue (D216)
def test_randomized_rotations_restarts_and_source_changes_store_each_line_once(
    env: dict[str, Path],  # noqa: F811
) -> None:
    """Three sources on one rotating log (a file source, a folder pattern, a recursive
    pattern), and a seeded run of appends, rotations with `create` (to a new numbered name),
    renames with a gap of passes before the new file, `copytruncate` (to a copy no source
    lists, after a pass), restarts, sources turned off and on, and a source deleted and
    added again. After every step no line is stored twice; whenever every source is on and
    the log is there, every line written so far is stored; and at the end every line is.
    By design (ADR-0051): lines that only ever reach a file no source lists are not read,
    so the test never writes to the copies."""
    rng = random.Random(SEED)
    logs = env["logs"]
    f = logs / "app.log"
    f.touch()
    c = logs / "export.csv"
    write(c, HEADER + "\n")
    specs = {
        "f_file": (f, "*", "syslog"),
        "g_glob": (logs, "app.log*", "syslog"),
        "r_rec": (logs, "**/app.log*", "syslog"),
        # A CSV export, read by a CSV file source and a syslog folder source.
        "c_csv": (c, "*", "csv"),
        "x_all": (logs, "export.csv*", "syslog"),
    }
    svc, store = service(env)
    for sid, (path, glob, fmt) in specs.items():
        _bind(store, sid, path, glob=glob, fmt=fmt)
    written: list[str] = []
    rotated = copies = 0
    on = set(specs)

    def rotate(log: Path, create: bool) -> None:
        nonlocal rotated
        rotated += 1
        log.rename(logs / f"{log.name}.{rotated}")
        if create:
            write(log, HEADER + "\n" if log == c else "")

    def mid_pass(log: Path) -> None:
        """A rotation inside a pass: after the holders are found, before any read."""
        real = svc._find_holders

        def then_rotate() -> None:
            real()
            rotate(log, create=True)
            write(log, row() if log == c else line())

        svc._find_holders = then_rotate  # type: ignore[method-assign]  # one pass only
        svc.run_once()
        svc._find_holders = real  # type: ignore[method-assign]

    def row() -> str:
        n = len(written)
        written.append(f"user{n},login")
        return written[-1] + "\n"

    def line() -> str:
        n = len(written)
        written.append(
            f"<30>Oct  9 20:41:00 ns1 named[{n}]: client 10.20.1.5#53212 (n{n}.example.com):"
            f" query: n{n}.example.com IN A + (10.20.0.53)"
        )
        return written[-1] + "\n"

    def stored() -> list[str]:
        return [r for r in _raws(env) if r != HEADER]  # each file's header, as data or not

    for step in range(STEPS):
        ops = ["append", "pass", "create", "gap", "truncate", "restart", "toggle", "readd"]
        op = rng.choices(
            [*ops, "csv", "csv_create", "mid"],
            [30, 20, 8, 5, 4, 5, 8, 3, 15, 4, 4],
        )[0]
        if op == "append" and f.exists():
            write(f, "".join(line() for _ in range(rng.randint(1, 4))))
        elif op == "csv":
            write(c, "".join(row() for _ in range(rng.randint(1, 4))))
        elif op == "csv_create":
            rotate(c, create=True)
        elif op == "mid" and f.exists():
            mid_pass(rng.choice([f, c]))
        elif op in ("create", "gap") and f.exists():
            rotate(f, create=op == "create")
        elif op == "create":
            f.touch()  # the gap ends
        elif op == "truncate" and f.exists() and on & {"f_file", "g_glob", "r_rec"}:
            svc.run_once()  # logrotate copies what is there: a source of the log reads it first
            copies += 1
            shutil.copy(f, logs / f"copy{copies}.txt")
            write(f, "", mode="w")
        elif op == "restart":
            svc, store = service(env)
        elif op == "toggle":
            sid = rng.choice(sorted(specs))
            on ^= {sid}
            with store._meta.connect() as con:
                con.execute(
                    "UPDATE sources SET enabled = ? WHERE source_id = ?", (int(sid in on), sid)
                )
        elif op == "readd":
            sid = rng.choice(sorted(specs))
            store.delete(sid)
            path, glob, fmt = specs[sid]
            if sid == "f_file" and not f.exists():
                f.touch()  # a file source needs its file to be added
            _bind(store, sid, path, glob=glob, fmt=fmt)
            on.add(sid)
        svc.run_once()
        got = stored()
        assert len(got) == len(set(got)), f"step {step} ({op}): a line stored twice"
        assert set(got) <= set(written), f"step {step} ({op})"
        assert _csv_fields_right(env), f"step {step} ({op}): a CSV row under the wrong header"
        if on == set(specs) and f.exists():
            svc.run_once()
            assert sorted(stored()) == sorted(written), f"step {step} ({op}): a line missing"
    # The end: every source on, the log there, two passes.
    if not f.exists():
        f.touch()
    with store._meta.connect() as con:
        con.execute("UPDATE sources SET enabled = 1")
    svc.run_once()
    svc.run_once()
    got = stored()
    assert len(got) == len(set(got)) and sorted(got) == sorted(written)
    assert rotated > 10 and len(written) > 200  # the run did what it says
    assert any(w.startswith("user") for w in written)


def test_after_a_more_specific_source_is_added_a_rotation_tail_goes_to_it(
    env: dict[str, Path],  # noqa: F811
) -> None:
    """Fourth review of #655: the former reader (a folder source) still held the file when
    a file source was added; at the next rotation the tail went to the folder source. The
    rename exception goes only to the holder the rule names, and a former reader closes
    its handle."""
    svc, store = service(env)
    f = env["logs"] / "queries.log"
    write(f, _lines(2))
    _bind(store, "zz_all", env["logs"], glob="*.log*")
    assert svc.run_once() == 2
    _bind(store, "a_dns", f, template_id="dns_bind")  # more specific, added later
    write(f, _lines(1, 2))
    assert svc.run_once() == 1
    write(f, _lines(2, 3))  # written before the rename
    f.rename(f.with_name("queries.log.1"))
    f.touch()
    write(f, _lines(1, 5))
    assert svc.run_once() == 3 and svc.run_once() == 0
    raws = _raws(env)
    assert len(raws) == len(set(raws)) == 6
    assert count(env, "source_id = 'zz_all'") == 2  # only what it read before a_dns came
    assert count(env, "source_id = 'a_dns' AND template_id = 'dns_bind'") == 4


# --- fifth review of #655 ------------------------------------------------------------------


def _csv_rows(env: dict[str, Path], sid: str) -> list[tuple[str, str]]:  # noqa: F811
    res = QueryEngine(env["data"] / "lake").run(
        f"SELECT raw, unmapped FROM events WHERE source_id = '{sid}' ORDER BY raw",
        QueryScope(sources=None),
    )
    return [(str(r[0]), str(r[1])) for r in res.rows]


def test_a_csv_source_taking_over_from_a_syslog_source_uses_the_files_header(
    env: dict[str, Path],  # noqa: F811
) -> None:
    """Only the offset and its content check carry over; the header is the CSV source's
    own, read from the file's first line, so no row is taken for the header."""
    svc, store = service(env)
    f = env["logs"] / "export.csv"
    write(f, "user,action\nalice,login\nbob,logout\n")
    _bind(store, "zz_all", env["logs"])
    assert svc.run_once() == 3  # the header line too: a syslog source stores every line
    _bind(store, "a_csv", f, fmt="csv")  # more specific, added later
    write(f, "carol,login\ndave,login\nerin,logout\n")
    assert svc.run_once() == 3
    rows = _csv_rows(env, "a_csv")
    assert [r for r, _ in rows] == ["carol,login", "dave,login", "erin,logout"]
    assert all('"user"' in u and '"action"' in u for _, u in rows)


def test_a_syslog_source_taking_over_from_a_csv_source_reads_on(
    env: dict[str, Path],  # noqa: F811
) -> None:
    svc, store = service(env)
    f = env["logs"] / "export.csv"
    write(f, "user,action\nalice,login\n")
    _bind(store, "a_csv", f, fmt="csv")
    _bind(store, "zz_all", env["logs"])
    assert svc.run_once() == 1
    with store._meta.connect() as con:
        con.execute("UPDATE sources SET enabled = 0 WHERE source_id = 'a_csv'")
    write(f, "bob,logout\n")
    assert svc.run_once() == 1
    assert [r for r, _ in _csv_rows(env, "zz_all")] == ["bob,logout"]


def test_a_csv_source_taking_over_from_another_csv_source_keeps_the_header(
    env: dict[str, Path],  # noqa: F811
) -> None:
    svc, store = service(env)
    f = env["logs"] / "export.csv"
    write(f, "user,action\nalice,login\n")
    _bind(store, "zz_csv", env["logs"], fmt="csv")
    assert svc.run_once() == 1
    _bind(store, "a_csv", f, fmt="csv")
    write(f, "bob,logout\n")
    assert svc.run_once() == 1
    ((raw, unmapped),) = _csv_rows(env, "a_csv")
    assert raw == "bob,logout" and '"user"' in unmapped


def test_a_rotation_inside_a_pass_goes_to_the_file_source(env: dict[str, Path]) -> None:  # noqa: F811
    """The holder is decided when a source is about to read a file: a file that appears
    under the file source's name during the pass is the file source's."""
    svc, store = service(env)
    f = env["logs"] / "queries.log"
    write(f, _lines(2))
    _bind(store, "dns_z", f, template_id="dns_bind")
    _bind(store, "app_all", env["logs"], glob="*.log")
    assert svc.run_once() == 2
    real = svc._find_holders

    def rotate_after() -> None:
        real()
        write(f, _lines(1, 2))
        f.rename(f.with_name("queries.log.1"))
        f.touch()
        write(f, _lines(3, 3))

    svc._find_holders = rotate_after  # type: ignore[method-assign]
    svc.run_once()
    svc._find_holders = real  # type: ignore[method-assign]
    assert svc.status()["dns_z"].shared == ()  # never "Read by app_all"
    write(f, _lines(1, 6))
    svc.run_once()
    svc.run_once()
    raws = _raws(env)
    assert len(raws) == len(set(raws)) == 7
    assert count(env, "source_id = 'app_all'") == 0


# --- sixth review of #655: one source's failure never affects another ---------------------


def test_a_source_whose_pattern_cannot_be_listed_does_not_stop_the_others(
    env: dict[str, Path],  # noqa: F811
) -> None:
    """`query**.log` passes the pattern check but Python cannot glob it: that source shows
    its error, and every other source is still read."""
    svc, store = service(env)
    write(env["logs"] / "queries.log", _lines(2))
    (env["logs"] / "other").mkdir()
    write(env["logs"] / "other" / "a.log", _lines(3, 10))
    _bind(store, "bad", env["logs"], glob="query**.log")
    _bind(store, "good", env["logs"] / "other")
    assert svc.run_once() == 3
    st = svc.status()
    assert st["bad"].error and st["good"].error is None
    write(env["logs"] / "other" / "a.log", _lines(1, 20))
    assert svc.run_once() == 1


def test_a_source_that_cannot_be_listed_does_not_stop_deleting_another(
    env: dict[str, Path],  # noqa: F811
) -> None:
    svc, store = service(env)
    write(env["logs"] / "queries.log", _lines(2))
    _bind(store, "bad", env["logs"], glob="query**.log")
    _bind(store, "good", env["logs"] / "queries.log")
    assert svc.run_once() == 2
    assert store.delete("good") is True
    assert {s.source_id for s in store.list()} == {"bad"}


# --- seventh review of #655 ------------------------------------------------------------------


def test_a_turned_off_source_does_not_keep_a_stale_read_by(env: dict[str, Path]) -> None:  # noqa: F811
    """Turned off, a source is Paused: it keeps no "Read by" from its last pass, which
    would advise removing it after the reading source is gone."""
    svc, store = service(env)
    f = env["logs"] / "queries.log"
    write(f, _lines(3))
    _bind(store, "dns_all", env["logs"])
    _bind(store, "dns_queries", f)
    svc.run_once()
    assert svc.status()["dns_all"].read_by == "dns_queries"
    _turn_off(store, "dns_all")
    svc.run_once()
    st = svc.status()["dns_all"]
    assert (st.read_by, st.shared) == (None, ())
    store.delete("dns_queries")
    svc.run_once()
    st = svc.status()["dns_all"]
    assert (st.read_by, st.shared) == (None, ())


def test_two_files_of_one_name_in_two_folders_are_two_entries(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    for d in ("a", "b"):
        (env["logs"] / d).mkdir()
        write(env["logs"] / d / "queries.log", _lines(2))
    _bind(store, "dns_some", env["logs"], glob="*/queries.log")
    _bind(store, "dns_rec", env["logs"], glob="**/*.log")
    svc.run_once()
    st = svc.status()["dns_rec"]
    assert st.read_by == "dns_some"
    assert st.shared == (("queries.log", "dns_some", False), ("queries.log", "dns_some", False))
