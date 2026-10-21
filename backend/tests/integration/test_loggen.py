"""The demo generator's output must ingest cleanly, so homelab tests start from a known-good state."""

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

from app.engine.duckdb import QueryEngine, QueryScope
from app.ingest.sources import SourceConfig, SourceStore
from app.ingest.watcher import IngestService
from app.meta.db import MetaDB

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "loggen.py"


def load_loggen() -> ModuleType:
    spec = importlib.util.spec_from_file_location("loggen", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["loggen"] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


def test_generated_logs_ingest_with_times_and_no_failures(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    assert (
        load_loggen().main(["--out", str(logs), "--backfill", "400", "--rate", "0", "--seed", "7"])
        == 0
    )

    meta = MetaDB(tmp_path / "meta.sqlite")
    store = SourceStore(meta, [logs])
    store.add(
        SourceConfig(
            source_id="demo_syslog", format="syslog", path=str(logs / "syslog"), glob="**/*.log"
        )
    )
    store.add(
        SourceConfig(source_id="demo_web", format="json", path=str(logs / "apps"), glob="*.jsonl")
    )
    store.add(
        SourceConfig(source_id="demo_vpn", format="csv", path=str(logs / "vpn"), glob="*.csv")
    )
    written = IngestService(store, meta, tmp_path / "lake").run_once()

    lines = (
        sum(len(p.read_text().splitlines()) for p in logs.rglob("*") if p.is_file()) - 1
    )  # CSV header
    assert written == lines

    res = QueryEngine(tmp_path / "lake").run(
        "SELECT source_id, count(*), count(time), count_if(parse_status = 'failed'), max(time) "
        "FROM events GROUP BY source_id ORDER BY source_id",
        QueryScope(None),
    )
    for source_id, total, with_time, failed, latest in res.rows:
        assert total > 0, source_id
        assert with_time == total, f"{source_id}: events without a parsed time"
        assert failed == 0, source_id
        assert datetime.fromisoformat(latest) <= datetime.now(UTC)
    assert [r[0] for r in res.rows] == ["demo_syslog", "demo_vpn", "demo_web"]


GUIDE = Path(__file__).resolve().parents[3] / "docs" / "install" / "homelab-test.md"


def guide_queries() -> list[str]:
    """The SQL in Part 3 of the homelab guide, one statement each, exactly as printed."""
    part3 = GUIDE.read_text().split("## Part 3", 1)[1].split("## Part 4", 1)[0]
    block = part3.split("```sql", 1)[1].split("```", 1)[0]
    return [q.strip() for q in block.split(";") if q.strip()]


def test_homelab_guide_queries_return_rows_on_demo_data(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    load_loggen().main(["--out", str(logs), "--backfill", "3000", "--rate", "0", "--seed", "7"])
    meta = MetaDB(tmp_path / "meta.sqlite")
    store = SourceStore(meta, [logs])
    for source_id, fmt, folder, glob in (
        ("demo_syslog", "syslog", "syslog", "**/*.log"),
        ("demo_web", "json", "apps", "*.jsonl"),
        ("demo_vpn", "csv", "vpn", "*.csv"),
    ):
        store.add(SourceConfig(source_id=source_id, format=fmt, path=str(logs / folder), glob=glob))
    IngestService(store, meta, tmp_path / "lake").run_once()
    queries = guide_queries()
    assert len(queries) == 3
    engine = QueryEngine(tmp_path / "lake")
    for sql in queries:
        rows = engine.run(sql, QueryScope(None)).rows
        assert rows, f"no rows for guide query:\n{sql}"
        assert all(r[0] not in (None, "") for r in rows), sql
