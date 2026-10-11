"""Source discovery: grouping, sampling, matching, and the limits (SPEC 3.6)."""

import os
import shutil
import threading
from pathlib import Path

import pytest

from app.core.errors import SourceRejectedError
from app.ingest import discovery
from app.ingest.discovery import _pattern, _rotations, discover
from app.ingest.sources import SourceConfig, files_for
from app.templates.registry import STARTER_DIR, TemplateRegistry

LOGS = Path(__file__).parent.parent / "fixtures" / "logs"
REGISTRY = TemplateRegistry(STARTER_DIR, Path("/nonexistent"))


@pytest.mark.parametrize(
    ("name", "pattern"),
    [
        ("sshd.log", "sshd.log"),
        ("fortigate-2026-10-09.log", "fortigate-*.log"),
        ("fw_20261009.log", "fw_*.log"),
        ("we[ird]*.log", "we[[]ird][*].log"),
    ],
)
def test_file_name_patterns(name: str, pattern: str) -> None:
    assert _pattern(name) == pattern


def test_rotations_need_their_live_file() -> None:
    names = ["auth.log", "auth.log.1", "auth.log-20261008", "app.1", "fw-2026-10-09.log"]
    assert _rotations(names) == {"auth.log.1", "auth.log-20261008"}


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "remote"
    for host in ("192.0.2.10", "192.0.2.11"):
        (root / host).mkdir(parents=True)
        shutil.copy(LOGS / "linux_sshd" / "sample.log", root / host / "sshd.log")
    shutil.copy(LOGS / "linux_sudo" / "sample.log", root / "192.0.2.10" / "sudo.log")
    shutil.copy(LOGS / "linux_sudo" / "sample.log", root / "192.0.2.10" / "sudo.log.1")
    (root / "fw").mkdir()
    for day in ("2026-10-09", "2026-10-10"):
        shutil.copy(LOGS / "fortinet_fortigate" / "sample.log", root / "fw" / f"fgt-{day}.log")
    (root / "dc01").mkdir()
    shutil.copy(LOGS / "windows_evtx" / "sample.evtx", root / "dc01" / "Security.evtx")
    (root / "archive.log.gz").write_bytes(b"\x1f\x8b" + b"\x00" * 100)
    (root / "blob.bin").write_bytes(b"\x00\x01\x02" * 5000)
    outside = tmp_path / "secret.log"
    outside.write_text("root:x:0:0\n")
    (root / "link.log").symlink_to(outside)
    return root


def test_discovery_groups_samples_and_matches(tree: Path) -> None:
    report = discover(str(tree), [tree], REGISTRY.all(), REGISTRY.tables)
    by_glob = {c.glob: c for c in report.candidates}
    assert set(by_glob) == {
        "*/sshd.log",
        "*/sudo.log",
        "*/fgt-*.log",
        "*/Security.evtx",
        "blob.bin",
    }
    sshd = by_glob["*/sshd.log"]
    assert sshd.files == 2 and sshd.hosts == ["192.0.2.10", "192.0.2.11"]
    assert sshd.matches[0].template_id == "linux_sshd" and sshd.matches[0].passes
    assert sshd.sniff is not None and sshd.sniff.envelope.get("3164", 0) > 0
    assert by_glob["*/sudo.log"].files == 1  # the rotated copy is not offered again
    assert by_glob["*/sudo.log"].matches[0].template_id == "linux_sudo"
    assert by_glob["*/fgt-*.log"].files == 2
    assert by_glob["*/fgt-*.log"].matches[0].template_id == "fortinet_fortigate"
    evtx = by_glob["*/Security.evtx"]
    assert evtx.kind == "evtx" and evtx.matches[0].template_id == "windows_evtx"
    assert by_glob["blob.bin"].kind == "binary" and by_glob["blob.bin"].matches == []
    assert report.skipped == {"compressed": 1, "outside_allowed_roots": 1, "rotated": 1}
    assert not report.truncated
    # Given to a real source, every suggestion reads exactly the files it grouped.
    for c in report.candidates:
        assert c.extra_matches == 0
        source = SourceConfig(source_id="x", format="syslog", path=c.path, glob=c.glob)
        assert len(files_for(source, [tree])) == c.files


def test_globs_that_reach_more_files_are_flagged(tmp_path: Path) -> None:
    root = tmp_path / "r"
    (root / "h1").mkdir(parents=True)
    (root / "h1" / "sys.log").write_text("a\n")
    (root / "h1" / "sys.log.2.gz").write_bytes(b"\x1f\x8b")
    (root / "fw-2026-10-09.log").write_text("a\n")
    (root / "fw-2026-10-09.log.bak").write_text("a\n")  # not a rotation of a live file
    (root / "fw-old.log").write_text("a\n")  # its own candidate, but fw-*.log reaches it
    report = discover(str(root), [root], REGISTRY.all())
    by_glob = {c.glob: c for c in report.candidates}
    assert by_glob["*/sys.log"].extra_matches == 0
    assert by_glob["fw-*.log.bak"].extra_matches == 0
    assert by_glob["fw-old.log"].extra_matches == 0
    assert by_glob["fw-*.log"].extra_matches == 1  # shown to the admin before adding


def test_hidden_entries_are_skipped_but_counted_as_reachable(tmp_path: Path) -> None:
    root = tmp_path / "r"
    for host in ("h1", ".h2"):
        (root / host).mkdir(parents=True)
        (root / host / "sys.log").write_text("a\n")
    (root / "h1" / ".sys.log.swp").write_text("a\n")
    report = discover(str(root), [root], REGISTRY.all())
    (c,) = report.candidates
    assert c.glob == "*/sys.log" and c.files == 1
    assert c.extra_matches == 1  # .h2/sys.log: the glob would read it, so the admin sees it
    assert report.skipped == {"hidden": 2}


def test_extra_matches_ignore_links_outside_the_roots(tmp_path: Path) -> None:
    root = tmp_path / "r"
    (root / "h1").mkdir(parents=True)
    (root / "h1" / "sys.log").write_text("a\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "sys.log").write_text("a\n")
    (root / "h2").symlink_to(elsewhere)
    (c,) = discover(str(root), [root], REGISTRY.all()).candidates
    assert c.extra_matches == 0  # the watcher would refuse h2/sys.log too


def test_symlinks_group_by_their_own_name(tmp_path: Path) -> None:
    root = tmp_path / "r"
    (root / "h1").mkdir(parents=True)
    (root / "archive" / "deep").mkdir(parents=True)
    target = root / "archive" / "deep" / "app-2026-10-09.log"
    target.write_text("hello\n")
    (root / "h1" / "current.log").symlink_to(target)
    report = discover(str(root), [root], REGISTRY.all())
    globs = {c.glob for c in report.candidates}
    assert "*/current.log" in globs  # the link, where the source will look
    for c in report.candidates:
        assert len(list(Path(c.path).glob(c.glob))) == c.files


def test_date_folders_are_not_hosts(tmp_path: Path) -> None:
    root = tmp_path / "r"
    for day in ("01", "02"):
        (root / "2026" / "10" / day).mkdir(parents=True)
        (root / "2026" / "10" / day / "app.log").write_text("hello\n")
    (c,) = discover(str(root), [root], REGISTRY.all()).candidates
    assert c.glob == "*/*/*/app.log" and c.hosts == [] and c.files == 2


def test_host_folders_below_a_category_folder(tmp_path: Path) -> None:
    """Scanning a parent of the collector folder: the folder holding the files is the
    host, the folders above it stay literal (homelab: /logs/demo/syslog/<host>/x.log)."""
    root = tmp_path / "demo"
    for host in ("192.0.2.10", "192.0.2.21", "192.0.2.31"):
        (root / "syslog" / host).mkdir(parents=True)
        (root / "syslog" / host / "sudo.log").write_text("a\n")
    (root / "syslog" / "192.0.2.10" / "sshd.log").write_text("a\n")
    (root / "vpn").mkdir()
    (root / "vpn" / "sessions.csv").write_text("a,b\n")
    by_glob = {c.glob: c for c in discover(str(root), [root], REGISTRY.all()).candidates}
    assert set(by_glob) == {"syslog/*/sudo.log", "syslog/*/sshd.log", "*/sessions.csv"}
    assert by_glob["syslog/*/sudo.log"].hosts == ["192.0.2.10", "192.0.2.21", "192.0.2.31"]
    assert by_glob["syslog/*/sudo.log"].files == 3
    assert by_glob["syslog/*/sshd.log"].hosts == ["192.0.2.10"]
    for c in by_glob.values():
        assert c.extra_matches == 0


def test_host_folders_below_date_folders(tmp_path: Path) -> None:
    root = tmp_path / "r"
    for day, host in (("01", "fw01"), ("02", "fw01"), ("02", "fw02")):
        (root / "2026" / "10" / day / host).mkdir(parents=True, exist_ok=True)
        (root / "2026" / "10" / day / host / "fw.log").write_text("a\n")
    (c,) = discover(str(root), [root], REGISTRY.all()).candidates
    assert c.glob == "*/*/*/*/fw.log" and c.hosts == ["fw01", "fw02"] and c.files == 3


def test_date_folders_below_host_folders(tmp_path: Path) -> None:
    root = tmp_path / "r"
    for host in ("fw01", "fw02"):
        (root / host / "2026-10-09").mkdir(parents=True)
        (root / host / "2026-10-09" / "fw.log").write_text("a\n")
    (c,) = discover(str(root), [root], REGISTRY.all()).candidates
    assert c.glob == "*/*/fw.log" and c.hosts == ["fw01", "fw02"]


def test_discovery_refuses_folders_outside_the_roots(tree: Path, tmp_path: Path) -> None:
    with pytest.raises(SourceRejectedError):
        discover(str(tmp_path), [tree], REGISTRY.all())
    with pytest.raises(SourceRejectedError):
        discover(str(tree / "fw" / "fgt-2026-10-09.log"), [tree], REGISTRY.all())


def test_previews_are_bounded_and_free_of_control_characters(tmp_path: Path) -> None:
    root = tmp_path / "r"
    root.mkdir()
    (root / "x.log").write_text("\x1b[31mred\x07 " + "y" * 5000 + "\n" * 3)
    (c,) = discover(str(root), [root], REGISTRY.all()).candidates
    assert c.preview and len(c.preview[0]) <= 300 and "\x1b" not in c.preview[0]


def test_limits_stop_the_walk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery, "MAX_FILES", 5)
    root = tmp_path / "r"
    deep = root / "a" / "b" / "c" / "d" / "e"
    deep.mkdir(parents=True)
    (deep / "deep.log").write_text("x\n")
    for i in range(10):
        (root / f"f{i}.txt").write_text("hello\n")
    report = discover(str(root), [root], REGISTRY.all())
    assert report.truncated and sum(c.files for c in report.candidates) == 5


def test_entry_and_time_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "r"
    root.mkdir()
    for i in range(30):
        (root / f"x{i}.gz").write_bytes(b"")
    monkeypatch.setattr(discovery, "MAX_ENTRIES", 10)
    assert discover(str(root), [root], REGISTRY.all()).truncated
    monkeypatch.setattr(discovery, "MAX_ENTRIES", 50_000)
    monkeypatch.setattr(discovery, "SCAN_SECONDS", -1.0)
    assert discover(str(root), [root], REGISTRY.all()).truncated


def test_a_fifo_swapped_in_never_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "r"
    root.mkdir()
    log = root / "x.log"
    log.write_text("hello\n")
    real_group = discovery._group

    def swap_then_group(r: Path, files: list[tuple[Path, Path]]) -> object:
        log.unlink()
        os.mkfifo(log)  # replaced after the walk saw a regular file
        return real_group(r, files)

    monkeypatch.setattr(discovery, "_group", swap_then_group)
    done: list[object] = []
    worker = threading.Thread(
        target=lambda: done.append(discover(str(root), [root], REGISTRY.all())), daemon=True
    )
    worker.start()
    worker.join(timeout=5)
    assert done, "discovery blocked on a FIFO"


def test_open_regular_refuses_fifos_and_devices(tmp_path: Path) -> None:
    from app.ingest.sources import open_regular

    fifo = tmp_path / "pipe.log"
    os.mkfifo(fifo)
    for path in (fifo, Path("/dev/null")):
        with pytest.raises(OSError):
            open_regular(path, [tmp_path, Path("/dev")])
    regular = tmp_path / "ok.log"
    regular.write_text("x\n")
    with open_regular(regular, [tmp_path]) as fh:
        assert fh.read() == b"x\n"


def test_open_regular_refuses_a_parent_folder_swapped_for_a_link(tmp_path: Path) -> None:
    """O_NOFOLLOW covers the file itself only. A folder inside the root replaced by a link to
    somewhere else after the path was checked must not be read through."""
    from app.ingest.sources import open_regular

    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "f.log").write_text("OUTSIDE SECRET\n")
    (root / "sub").rmdir()
    (root / "sub").symlink_to(outside)  # the swap, after resolution
    with pytest.raises(OSError):
        open_regular(root / "sub" / "f.log", [root])
    inside = root / "real"
    inside.mkdir()
    (inside / "g.log").write_text("ok\n")
    (root / "alias").symlink_to(inside)  # a link that stays inside the root is fine
    with open_regular(root / "alias" / "g.log", [root]) as fh:
        assert fh.read() == b"ok\n"


def test_names_that_are_not_utf8_are_skipped_and_counted(tmp_path: Path) -> None:
    root = tmp_path / "r"
    root.mkdir()
    (root / "good.log").write_text("hello\n")
    os.mkdir(os.fsencode(root) + b"/host\xff")
    with open(os.fsencode(root) + b"/host\xff/x.log", "w") as fh:
        fh.write("a\n")
    with open(os.fsencode(root) + b"/fw\xfe.log", "w") as fh:
        fh.write("a\n")
    report = discover(str(root), [root], REGISTRY.all())
    assert [c.glob for c in report.candidates] == ["good.log"]
    assert report.skipped == {"undecodable_name": 2}
