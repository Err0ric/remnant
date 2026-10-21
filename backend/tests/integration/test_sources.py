"""Sources: allowed_roots enforcement, tail/watch with checkpoints, rotation, API."""

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.core.errors import SourceRejectedError
from app.engine.duckdb import QueryEngine, QueryScope
from app.ingest.sources import SourceConfig, SourceStore, resolve_source_path
from app.ingest.watcher import IngestService
from app.main import create_app
from app.meta.db import MetaDB

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
LINE = "<38>Oct  9 20:41:{:02d} bastion sshd[{}]: Accepted publickey for jordan\n"


@pytest.fixture
def env(tmp_path: Path) -> dict[str, Path]:
    logs = tmp_path / "logs"
    logs.mkdir()
    data = tmp_path / "data"
    return {"logs": logs, "data": data, "root": tmp_path}


def service(env: dict[str, Path]) -> tuple[IngestService, SourceStore]:
    meta = MetaDB(env["data"] / "meta.sqlite")
    store = SourceStore(meta, allowed_roots=[env["logs"]])
    return IngestService(store, meta, env["data"] / "lake", clock=lambda: NOW), store


def count(env: dict[str, Path], where: str = "TRUE") -> int:
    res = QueryEngine(env["data"] / "lake").run(
        f"SELECT count(*) FROM events WHERE {where}", QueryScope(sources=None)
    )
    return int(res.rows[0][0])


def write(path: Path, text: str, mode: str = "a") -> None:
    with path.open(mode, encoding="utf-8") as fh:
        fh.write(text)


# --- allowed roots ---------------------------------------------------------------


def test_path_inside_allowed_root(env: dict[str, Path]) -> None:
    f = env["logs"] / "auth.log"
    f.touch()
    assert resolve_source_path(f, [env["logs"]]) == f.resolve()


def test_path_outside_allowed_root_rejected(env: dict[str, Path]) -> None:
    other = env["root"] / "secrets.log"
    other.touch()
    with pytest.raises(SourceRejectedError, match="allowed roots"):
        resolve_source_path(other, [env["logs"]])


def test_symlink_escaping_root_rejected(env: dict[str, Path]) -> None:
    target = env["root"] / "secrets.log"
    target.touch()
    link = env["logs"] / "innocent.log"
    os.symlink(target, link)
    with pytest.raises(SourceRejectedError):
        resolve_source_path(link, [env["logs"]])


def test_no_allowed_roots_rejects_everything(env: dict[str, Path]) -> None:
    f = env["logs"] / "auth.log"
    f.touch()
    with pytest.raises(SourceRejectedError, match=r"paths\.allowed_roots"):
        resolve_source_path(f, [])


def test_missing_path_rejected(env: dict[str, Path]) -> None:
    with pytest.raises(SourceRejectedError, match="does not exist"):
        resolve_source_path(env["logs"] / "nope.log", [env["logs"]])


# --- tail / watch ------------------------------------------------------------------


def test_tail_only_reads_new_lines(env: dict[str, Path]) -> None:
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1) + LINE.format(2, 2))
    store.add(SourceConfig(source_id="linux_auth", format="syslog", path=str(f)))
    assert svc.run_once() == 2
    assert svc.run_once() == 0
    write(f, LINE.format(3, 3))
    assert svc.run_once() == 1
    assert count(env) == 3


def test_partial_line_is_held_until_complete(env: dict[str, Path]) -> None:
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1) + "<38>Oct  9 20:41:05 bastion sshd[5]: half")
    store.add(SourceConfig(source_id="linux_auth", format="syslog", path=str(f)))
    assert svc.run_once() == 1
    write(f, " a line\n")
    assert svc.run_once() == 1
    assert count(env, "message = 'half a line'") == 1


def test_rotation_by_rename_starts_new_file_at_zero(env: dict[str, Path]) -> None:
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1))
    store.add(SourceConfig(source_id="linux_auth", format="syslog", path=str(f)))
    svc.run_once()
    f.rename(env["logs"] / "auth.log.1")
    write(f, LINE.format(2, 2), mode="w")
    assert svc.run_once() == 1
    assert count(env) == 2


def test_copytruncate_restarts_at_zero(env: dict[str, Path]) -> None:
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1) + LINE.format(2, 2))
    store.add(SourceConfig(source_id="linux_auth", format="syslog", path=str(f)))
    svc.run_once()
    write(f, LINE.format(3, 3), mode="w")  # same inode, smaller than the checkpoint
    assert svc.run_once() == 1
    assert count(env) == 3


def test_folder_source_with_glob(env: dict[str, Path]) -> None:
    svc, store = service(env)
    host_a = env["logs"] / "host-a"
    host_a.mkdir()
    write(host_a / "auth.log", LINE.format(1, 1))
    write(env["logs"] / "notes.txt", "not a log\n")
    write(env["logs"] / "other.log", LINE.format(2, 2))
    store.add(
        SourceConfig(
            source_id="linux_auth", format="syslog", path=str(env["logs"]), glob="**/*.log"
        )
    )
    assert svc.run_once() == 2


def test_csv_header_survives_restarts(env: dict[str, Path]) -> None:
    svc, store = service(env)
    f = env["logs"] / "vpn.csv"
    write(f, "time,user\n2026-10-09T20:00:00Z,jordan\n")
    store.add(SourceConfig(source_id="vpn", format="csv", path=str(f)))
    svc.run_once()
    write(f, "2026-10-09T21:00:00Z,kelly\n")
    fresh, _ = service(env)  # new process, same checkpoints
    assert fresh.run_once() == 1
    assert count(env, "json_extract_string(unmapped, '$.user') = 'kelly'") == 1


def test_disabled_source_is_skipped(env: dict[str, Path]) -> None:
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1))
    store.add(SourceConfig(source_id="linux_auth", format="syslog", path=str(f), enabled=False))
    assert svc.run_once() == 0


def test_source_ids_unique(env: dict[str, Path]) -> None:
    _, store = service(env)
    f = env["logs"] / "auth.log"
    f.touch()
    store.add(SourceConfig(source_id="linux_auth", format="syslog", path=str(f)))
    with pytest.raises(SourceRejectedError, match="already exists"):
        store.add(SourceConfig(source_id="linux_auth", format="syslog", path=str(f)))


# --- API ---------------------------------------------------------------------------


def test_sources_api_create_list_delete(env: dict[str, Path]) -> None:
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1))
    config = load_config(
        Path("missing.yaml"),
        {"APP__PATHS__DATA_DIR": str(env["data"]), "APP__PATHS__ALLOWED_ROOTS": str(env["logs"])},
    )
    client = TestClient(create_app(config))
    bad = client.post(
        "/api/sources", json={"source_id": "x", "format": "syslog", "path": "/etc/passwd"}
    )
    assert bad.status_code == 400
    assert bad.json()["code"] == "source_rejected"
    ok = client.post(
        "/api/sources", json={"source_id": "linux_auth", "format": "syslog", "path": str(f)}
    )
    assert ok.status_code == 201
    listed = client.get("/api/sources").json()
    assert [s["source_id"] for s in listed] == ["linux_auth"]
    assert client.delete("/api/sources/linux_auth").status_code == 204
    assert client.get("/api/sources").json() == []


def test_server_lifespan_polls_sources(env: dict[str, Path]) -> None:
    import time

    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1))
    config = load_config(
        Path("missing.yaml"),
        {
            "APP__PATHS__DATA_DIR": str(env["data"]),
            "APP__PATHS__ALLOWED_ROOTS": str(env["logs"]),
            "APP__INGEST__POLL_INTERVAL_S": "0.2",
        },
    )
    with TestClient(create_app(config)) as client:
        client.post(
            "/api/sources", json={"source_id": "linux_auth", "format": "syslog", "path": str(f)}
        )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and count(env) == 0:
            time.sleep(0.1)
    assert count(env) == 1


def test_delete_unknown_source_is_404(env: dict[str, Path]) -> None:
    config = load_config(Path("missing.yaml"), {"APP__PATHS__DATA_DIR": str(env["data"])})
    res = TestClient(create_app(config)).delete("/api/sources/nope")
    assert res.status_code == 404
    assert res.json()["code"] == "not_found"


def test_allowed_roots_env_accepts_comma_list(env: dict[str, Path]) -> None:
    config = load_config(
        Path("missing.yaml"), {"APP__PATHS__ALLOWED_ROOTS": "/var/log/remote, /srv/logs"}
    )
    assert config.paths.allowed_roots == [Path("/var/log/remote"), Path("/srv/logs")]


# --- status and isolation ------------------------------------------------------------


def test_missing_folder_does_not_stop_other_sources(env: dict[str, Path]) -> None:
    svc, store = service(env)
    gone = env["logs"] / "gone"
    gone.mkdir()
    good = env["logs"] / "auth.log"
    write(good, LINE.format(1, 1))
    store.add(SourceConfig(source_id="a_gone", format="syslog", path=str(gone)))
    store.add(SourceConfig(source_id="b_good", format="syslog", path=str(good)))
    gone.rmdir()
    assert svc.run_once() == 1
    status = svc.status()
    assert status["a_gone"].error is not None
    assert "does not exist" in status["a_gone"].error
    assert status["b_good"].error is None
    assert status["b_good"].files == 1
    assert status["b_good"].events_last_pass == 1
    assert status["b_good"].last_event_at == NOW


def test_unreadable_file_does_not_stop_the_rest_of_the_source(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.ingest.watcher as watcher

    svc, store = service(env)
    for name in ("a.log", "b.log", "c.log"):
        write(env["logs"] / name, LINE.format(1, 1))
    store.add(SourceConfig(source_id="s", format="syslog", path=str(env["logs"]), glob="*.log"))
    real_open = watcher.open_regular

    def deny_b(path: Path, roots: list[Path]) -> object:
        if path.name == "b.log":
            raise PermissionError(13, "Permission denied")
        return real_open(path, roots)

    monkeypatch.setattr(watcher, "open_regular", deny_b)
    assert svc.run_once() == 2  # a.log and c.log, before and after the failing file
    st = svc.status()["s"]
    assert st.files == 3
    assert st.error == "Cannot read 1 of 3 files (b.log: Permission denied)"
    monkeypatch.setattr(watcher, "open_regular", real_open)
    assert svc.run_once() == 1  # b.log once it is readable; a and c are not read again
    assert svc.status()["s"].error is None


def test_file_rotated_away_mid_pass_is_not_an_error(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.ingest.watcher as watcher

    svc, store = service(env)
    write(env["logs"] / "a.log", LINE.format(1, 1))
    store.add(SourceConfig(source_id="s", format="syslog", path=str(env["logs"]), glob="*.log"))

    def gone(path: Path, roots: list[Path]) -> object:
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(watcher, "open_regular", gone)
    assert svc.run_once() == 0
    assert svc.status()["s"].error is None


def test_a_name_that_is_not_utf8_neither_stops_ingest_nor_the_api(env: dict[str, Path]) -> None:
    """Such a name used to raise past every handler and stop every source, every pass."""
    svc, store = service(env)
    a, b = env["logs"] / "a", env["logs"] / "b"
    a.mkdir()
    b.mkdir()
    with open(os.fsencode(a) + b"/host\xff.log", "w") as fh:
        fh.write(LINE.format(1, 1))
    write(b / "good.log", LINE.format(2, 2))
    store.add(SourceConfig(source_id="a_src", format="syslog", path=str(a), glob="*.log"))
    store.add(SourceConfig(source_id="b_src", format="syslog", path=str(b), glob="*.log"))
    assert svc.run_once() == 2
    assert svc.run_once() == 0  # checkpointed by its bytes: not read twice
    st = svc.status()
    assert st["a_src"].error is None and st["b_src"].error is None


def test_an_unexpected_error_in_one_file_is_reported_not_raised(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    svc, store = service(env)
    for name in ("a.log", "b.log"):
        write(env["logs"] / name, LINE.format(1, 1))
    store.add(SourceConfig(source_id="s", format="syslog", path=str(env["logs"]), glob="*.log"))
    real = svc._ingest_file

    def boom(source: SourceConfig, path: Path) -> int:
        if path.name == "a.log":
            raise ValueError("unexpected")
        return real(source, path)

    monkeypatch.setattr(svc, "_ingest_file", boom)
    assert svc.run_once() == 1
    assert svc.status()["s"].error == "Cannot read 1 of 2 files (a.log: ValueError)"


def test_sources_api_reports_status_and_roots(env: dict[str, Path]) -> None:
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1))
    config = load_config(
        Path("missing.yaml"),
        {"APP__PATHS__DATA_DIR": str(env["data"]), "APP__PATHS__ALLOWED_ROOTS": str(env["logs"])},
    )
    app = create_app(config)
    client = TestClient(app)
    client.post(
        "/api/sources", json={"source_id": "linux_auth", "format": "syslog", "path": str(f)}
    )
    before = client.get("/api/sources").json()[0]
    assert before["status"]["state"] == "waiting"
    app.state.ingest.run_once()
    after = client.get("/api/sources").json()[0]
    assert after["status"]["state"] == "reading"
    assert after["status"]["files"] == 1
    assert client.get("/api/sources/settings").json() == {"allowed_roots": [str(env["logs"])]}


# --- review findings (2026-10-10) ------------------------------------------------------


def test_oversized_line_is_truncated_and_never_stalls_the_source(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.ingest import watcher

    monkeypatch.setattr(watcher, "READ_LIMIT", 1024)
    svc, store = service(env)
    f = env["logs"] / "app.log"
    write(f, "A" * 5000 + "\n" + LINE.format(9, 9))
    store.add(SourceConfig(source_id="app_log", format="syslog", path=str(f)))
    for _ in range(10):  # several small reads: start of the big line, its tail, then the next line
        svc.run_once()
    assert count(env) == 2
    assert count(env, "parse_status = 'partial' AND starts_with(raw, 'AAAA')") == 1
    assert count(env, "message = 'Accepted publickey for jordan'") == 1
    write(f, LINE.format(10, 10))
    assert svc.run_once() == 1


def test_ingested_raw_is_exact_and_partitioned_by_source_and_day(env: dict[str, Path]) -> None:
    svc, store = service(env)
    f = env["logs"] / "auth.log"
    line = "<38>Oct  9 20:41:01 bastion sshd[1]:  two spaces, trailing space \n"
    write(f, line)
    store.add(SourceConfig(source_id="linux_auth", format="syslog", path=str(f)))
    svc.run_once()
    res = QueryEngine(env["data"] / "lake").run("SELECT raw FROM events", QueryScope(None))
    assert res.rows == [[line.rstrip("\n")]]
    parts = list((env["data"] / "lake").rglob("*.parquet"))
    assert [p.parent.parent.name + "/" + p.parent.name for p in parts] == [
        "source=linux_auth/day=2026-10-09"
    ]
