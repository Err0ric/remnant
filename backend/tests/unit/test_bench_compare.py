"""The speed check's lake options (scripts/bench_compare.py): `--real-days` reaches the
real-shaped generator and the kept lake's record, and decides whether a kept lake is fresh;
the lake holds AI Watch alerts that name machines. No lake is built here."""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import bench_compare as bc

NOW = 1_800_000_000.0
KEPT = {"events": 1, "loggen": 400_000, "shape": 0.313, "days": 30, "version": bc.LAKE_VERSION}


def test_a_kept_lake_is_fresh_only_for_the_days_asked() -> None:
    kept = KEPT | {"at": NOW - 60}
    assert bc.is_fresh(kept, 400_000, 0.313, 30, NOW)
    assert not bc.is_fresh(kept, 400_000, 0.313, 7, NOW)
    assert not bc.is_fresh(kept | {"at": NOW - 86_401}, 400_000, 0.313, 30, NOW)
    assert not bc.is_fresh(kept, 400_000, 0.5, 30, NOW)


def test_a_lake_is_stale_after_midnight_utc() -> None:
    midnight = 1_800_057_600.0  # 2027-01-16 00:00 UTC
    kept = KEPT | {"at": midnight - 60}
    assert bc.is_fresh(kept, 400_000, 0.313, 30, midnight - 1)
    # A new closed day with no rollup: built again.
    assert not bc.is_fresh(kept, 400_000, 0.313, 30, midnight + 60)
    # The default lake keeps its rollups too (owner, 2026-11-14): the same rule.
    small = {"events": 1, "loggen": 400_000, "shape": 0.0, "version": bc.LAKE_VERSION}
    assert bc.is_fresh(small | {"at": midnight - 60}, 400_000, 0.0, 7, midnight - 1)
    assert not bc.is_fresh(small | {"at": midnight - 60}, 400_000, 0.0, 7, midnight + 60)
    # A default lake kept before it had rollups (version 3) is built again once.
    assert not bc.is_fresh(
        small | {"at": midnight - 60, "version": 3}, 400_000, 0.0, 7, midnight - 1
    )


def test_days_count_only_with_a_real_shaped_part() -> None:
    small = {"events": 1, "loggen": 400_000, "shape": 0.0, "days": 0, "version": bc.LAKE_VERSION}
    assert bc.is_fresh(small | {"at": NOW}, 400_000, 0.0, 30, NOW)
    # A lake kept before --real-days has 7 days and no version: rebuilt for the alerts.
    old = {"events": 1, "loggen": 400_000, "shape": 0.313, "at": NOW}
    assert not bc.is_fresh(old, 400_000, 0.313, 7, NOW)
    assert bc.is_fresh(old | {"version": bc.LAKE_VERSION}, 400_000, 0.313, 7, NOW)


def test_the_days_reach_the_generator() -> None:
    cmd = bc.real_shape_cmd(Path("/lake"), 0.313, 30)
    assert cmd[1].endswith("scripts/fixtures/real_shape.py")
    assert cmd[2:] == ["--lake", "/lake", "--scale", "0.313", "--days", "30"]


GOOD_CHECK = [{"step": s, "ok": True, "detail": None} for s in ("events", "agents", "review")]


def alert(sid: str, devices: list[str]) -> dict[str, Any]:
    return {"kind": "ai_watch", "subject": f"service:{sid}", "devices": devices}


GOOD_ALERTS = [alert(s, ["10.20.1.5", "ws-0040", "ws-0060"]) for s in bc.AI_SERVICES]


class FakeApi:
    calls: ClassVar[list[tuple[str, str, Any]]] = []
    alerts: ClassVar[list[dict[str, Any]]] = GOOD_ALERTS
    check: ClassVar[Any] = GOOD_CHECK

    def __init__(self, base: str, pid: int | None = None) -> None:
        pass

    def call(self, method: str, path: str, body: Any = None, **kw: Any) -> Any:
        FakeApi.calls.append((method, path, body))
        if path == "/api/sources" and body.get("kind") == "otlp":
            return {"otlp_token": "bench-token"}
        if path == "/api/ai/watch/check":
            return FakeApi.check
        if path.startswith("/api/alerts"):
            return {"items": FakeApi.alerts}
        return [] if method == "GET" else {}


@pytest.fixture
def fake_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    got: dict[str, list[Any]] = {"ran": [], "served": [], "waited": []}
    monkeypatch.setattr(bc.subprocess, "run", lambda cmd, **kw: got["ran"].append(list(map(str, cmd))))  # fmt: skip
    monkeypatch.setattr(bc, "serve", lambda *a, **kw: got["served"].append(kw) or object())
    monkeypatch.setattr(bc, "stop", lambda proc: None)
    monkeypatch.setattr(bc, "settle", lambda *a: 42)
    monkeypatch.setattr(bc, "Api", FakeApi)
    monkeypatch.setattr(bc, "built_rollups", lambda api: got["waited"].append(api) or True)
    monkeypatch.setattr(FakeApi, "alerts", GOOD_ALERTS)
    monkeypatch.setattr(FakeApi, "check", GOOD_CHECK)
    FakeApi.calls = []
    return got


def test_build_passes_the_days_and_records_them(
    tmp_path: Path, fake_build: dict[str, list[Any]]
) -> None:
    lake = tmp_path / "lake"
    assert bc.build(tmp_path, lake, 400_000, 1, tmp_path / "log", 0.313, 30) == 42
    (gen,) = [c for c in fake_build["ran"] if c[1].endswith("real_shape.py")]
    assert gen[-2:] == ["--days", "30"]
    kept = json.loads((lake / "built.json").read_text())
    assert (kept["days"], kept["shape"], kept["version"]) == (30, 0.313, bc.LAKE_VERSION)
    # The real-shaped rows are sources of the install, as the Dashboard reads them.
    added = {b["source_id"] for m, p, b in FakeApi.calls if p == "/api/sources" and m == "POST"}
    assert {"win_auth", "win_dns", "hooks"} <= added
    # AI Watch checks once everything is in, and its alerts are read back.
    paths = [p for _, p, _ in FakeApi.calls]
    assert paths.index("/api/ai/watch/check") < paths.index("/api/alerts?state=open")
    # Every lake is kept compacted and rolled up, the default one too (owner, 2026-11-14).
    assert fake_build["served"][0]["extra"] == bc.BUILD_ENV and len(fake_build["waited"]) == 1
    fake_build["served"].clear()
    assert bc.build(tmp_path, tmp_path / "small", 400_000, 1, tmp_path / "log") == 42
    assert fake_build["served"][0]["extra"] == bc.BUILD_ENV and len(fake_build["waited"]) == 2


@pytest.mark.parametrize(
    ("alerts", "check"),
    [
        ([], GOOD_CHECK),  # no alert raised
        (
            [alert(s, ["10.20.1.5", "10.20.1.6"]) for s in bc.AI_SERVICES],
            GOOD_CHECK,
        ),  # addresses only
        (GOOD_ALERTS[:2], GOOD_CHECK),  # one service missing
        (GOOD_ALERTS, [{"step": "review", "ok": False, "detail": "timeout"}]),  # a step failed
    ],
)
def test_no_lake_is_kept_without_the_ai_watch_alerts(
    tmp_path: Path, fake_build: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch,
    alerts: list[dict[str, Any]], check: Any,
) -> None:  # fmt: skip
    monkeypatch.setattr(FakeApi, "alerts", alerts)
    monkeypatch.setattr(FakeApi, "check", check)
    with pytest.raises(RuntimeError, match="AI Watch"):
        bc.build(tmp_path, tmp_path / "lake", 400_000, 1, tmp_path / "log")
    assert not (tmp_path / "lake" / "built.json").exists()


@pytest.mark.parametrize("shape", [0.313, 0.0])
def test_no_lake_is_kept_when_its_rollups_did_not_finish(
    tmp_path: Path, fake_build: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch, shape: float
) -> None:
    monkeypatch.setattr(bc, "built_rollups", lambda api: False)
    with pytest.raises(RuntimeError, match="rollups not built"):
        bc.build(tmp_path, tmp_path / "lake", 400_000, 1, tmp_path / "log", shape, 30)
    assert not (tmp_path / "lake" / "built.json").exists()


def test_the_alert_feed_names_machines_and_who_used_them(tmp_path: Path) -> None:
    FakeApi.calls = []
    api: Any = FakeApi("")
    n = bc.ai_alert_feed(api, tmp_path, datetime(2026, 11, 13, 12, tzinfo=UTC))
    lines = (tmp_path / "bench_ai_proxy" / "proxy.log").read_text().splitlines()
    assert n == len(lines) == 6 * len(bc.AI_PROXY_HOSTS) * len(bc.AI_SITES)
    # Named machines, no person and no address: an item keeps 20 devices, addresses first.
    assert all("shost=ws-" in line and "suser=" not in line for line in lines)
    assert not any("|src=" in line or " src=" in line for line in lines)
    otlp = [b for m, p, b in FakeApi.calls if p == "/api/otlp/v1/logs"]
    hosts = {
        a["value"]["stringValue"]
        for b in otlp
        for a in b["resourceLogs"][0]["resource"]["attributes"]
        if a["key"] == "host.name"
    }
    assert hosts == set(bc.AI_HOOK_PEOPLE)
    added = [b["source_id"] for m, p, b in FakeApi.calls if p == "/api/sources"]
    assert added == ["bench_hooks", "bench_ai_proxy"]


T0 = datetime(2027, 1, 15, 8, tzinfo=UTC)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def test_rollups_count_only_after_a_compaction_that_saw_every_file() -> None:
    # A run just after the start, or one run past the settle time: its compaction may
    # have left files younger than 60 s, so not yet.
    assert not bc.rolled_up([at(5)], 0, T0)
    assert not bc.rolled_up([at(5), at(65)], 0, T0)
    # Two runs past it: the second's compaction started after the first ended.
    assert bc.rolled_up([at(5), at(65), at(125)], 0, T0)
    assert not bc.rolled_up([at(65), at(125)], 3, T0)  # days still to build
    assert not bc.rolled_up([at(125), at(125)], 0, T0)  # one run, read twice


def test_the_lake_waits_for_every_rollup(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [T0]

    class Clock(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> "Clock":
            return now[0]  # type: ignore[return-value]  # a datetime is all the code uses

    monkeypatch.setattr(bc, "datetime", Clock)
    # Not checked yet; a run before the start; days left; then done, twice past the settle.
    states = iter([(None, None), (0, at(-30)), (3, at(50)), (0, at(130)), (0, at(190))])

    class Health:
        def call(self, method: str, path: str, body: Any = None, **kw: Any) -> Any:
            assert (method, path) == ("GET", "/api/health-checks")
            n, t = next(states)
            done = {"name": "x", "pending": 0, "last_run": at(130 + len(seen)).isoformat()}
            seen.append(1)
            last = t.isoformat() if t else None
            return {"rollups": [{"name": "ai_rollup", "pending": n, "last_run": last}, done]}

    seen: list[int] = []
    monkeypatch.setattr(bc.time, "sleep", lambda s: None)
    api: Any = Health()
    assert bc.built_rollups(api)
    assert next(states, "used") == "used"
    # Never built: False after the limit, not waited on for ever.
    states = iter([(5, at(70))] * 10_000)
    clock = iter(range(0, 10_000_000, 100))
    monkeypatch.setattr(bc.time, "monotonic", lambda: float(next(clock)))
    assert not bc.built_rollups(api, limit_s=1000)
