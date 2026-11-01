"""Oversized queries fail with an error instead of exhausting memory (D58)."""

import tempfile
from pathlib import Path

import pytest

from app.core import memory
from app.core.errors import QueryFailedError, QueryRejectedError
from app.engine.duckdb import QueryEngine, QueryScope
from app.engine.guard import guard

EVENTS = frozenset({"events"})


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT count(*) FROM (SELECT unnest(range(3000000000)))",
        "SELECT unnest(generate_series(1, 600000000))",
        "SELECT range(-200000000, 0)",
        "SELECT unnest(range(0, 10000000000, 10))",
        "SELECT length(repeat('x', 2000000000))",
        "SELECT lpad('a', 99999999, 'b')",
        "SELECT rpad('a', 99999999, 'b')",
        "SELECT list_resize([1], 50000000)",
        "SELECT array_resize([1], 50000000)",
    ],
)
def test_literal_sizes_past_the_caps_are_refused(sql: str) -> None:
    with pytest.raises(QueryRejectedError, match="too large"):
        guard(sql, EVENTS)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT unnest(range(1000))",
        "SELECT repeat('-', 40)",
        "SELECT lpad(message, 20, ' ') FROM events",
        "SELECT unnest(range(0, 1000, 0))",  # zero step: DuckDB's own error, not ours
    ],
)
def test_ordinary_use_still_passes(sql: str) -> None:
    guard(sql, EVENTS)


def test_engine_reports_out_of_memory_as_a_failed_query() -> None:
    engine = QueryEngine(Path(tempfile.mkdtemp()), memory_mb=64, threads=1)
    sql = (
        "SELECT length(string_agg(repeat('x', 1000000), '')) FROM (SELECT unnest(range(3000)) AS i)"
    )
    with pytest.raises(QueryFailedError, match=r"Out of memory: .* Try a shorter time range"):
        engine.run(sql, QueryScope(None))


def test_budget_is_configured_or_three_quarters_of_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(memory, "available_mb", lambda: 8000)
    assert memory.server_budget_mb(0) == 6000
    assert memory.server_budget_mb(4096) == 4096
    assert memory.server_budget_mb(10) == memory.MIN_MB  # never below what the server needs
    monkeypatch.setattr(memory, "available_mb", lambda: 1000)
    assert memory.server_budget_mb(0) is None  # too small to cap safely
    monkeypatch.setattr(memory, "available_mb", lambda: None)
    assert memory.server_budget_mb(0) is None
    assert memory.available_mb is not None


def _fake_root(tmp: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return tmp


GB = 1024 * 1024 * 1024


@pytest.mark.parametrize(
    ("files", "sysconf", "expected"),
    [
        # LXC: meminfo virtualized to 8 GB, sysconf sees the 512 GB host
        ({"proc/meminfo": "MemTotal:  8388608 kB\n"}, 512 * GB, (8192, "/proc/meminfo")),
        # cgroup v2 limit on the process's own cgroup wins when lower
        (
            {
                "proc/meminfo": "MemTotal:  8388608 kB\n",
                "proc/self/cgroup": "0::/system.slice/app.service\n",
                "sys/fs/cgroup/system.slice/app.service/memory.max": f"{4 * GB}\n",
                "sys/fs/cgroup/memory.max": "max\n",
            },
            512 * GB,
            (4096, "/sys/fs/cgroup/system.slice/app.service/memory.max"),
        ),
        # "max" everywhere is ignored
        (
            {"proc/meminfo": "MemTotal:  8388608 kB\n", "sys/fs/cgroup/memory.max": "max\n"},
            None,
            (8192, "/proc/meminfo"),
        ),
        # cgroup v1 limit, and its "unlimited" sentinel ignored at the root
        (
            {
                "proc/self/cgroup": "4:memory:/docker/abc\n",
                "sys/fs/cgroup/memory/docker/abc/memory.limit_in_bytes": f"{2 * GB}\n",
                "sys/fs/cgroup/memory/memory.limit_in_bytes": "9223372036854771712\n",
            },
            16 * GB,
            (2048, "/sys/fs/cgroup/memory/docker/abc/memory.limit_in_bytes"),
        ),
        # Nothing readable but sysconf
        ({}, 16 * GB, (16384, "sysconf")),
        # Nothing at all
        ({"proc/meminfo": "garbage\n"}, None, None),
    ],
)
def test_detect_takes_the_smallest_visible_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    files: dict[str, str],
    sysconf: int | None,
    expected: tuple[int, str] | None,
) -> None:
    monkeypatch.setattr(memory, "_sysconf_bytes", lambda: sysconf)
    assert memory.detect(_fake_root(tmp_path, files)) == expected


def test_budget_note_names_the_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(memory, "detect", lambda: (8192, "/proc/meminfo"))
    assert memory.budget_note(0) == "auto, 75% of 8192 MB from /proc/meminfo"
    assert memory.budget_note(4096) == "server.memory_limit_mb"
    monkeypatch.setattr(memory, "detect", lambda: None)
    assert memory.budget_note(0) == "auto"
