"""Person page "What it did": a Palo Alto USERID row reads as a plain summary (who, the
address, how the mapping was learned), never the raw CSV record. Lines stored before the
template mapped a plain message (#425) still carry the record as their message."""

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from app.core.schema import arrow_schema
from app.engine.duckdb import QueryEngine, QueryScope
from app.engine.lookups import Lookups
from app.ingest.normalizer import SourceSpec
from app.ingest.records import DecodedLine
from app.search.entity_summary import entity_summary
from app.templates.router import AutoNormalizer
from tests.integration.test_entity_activity_labels import NAMES, NOW, REGISTRY

RECORD = (
    "1,2026/10/09 20:41:00,012345678901,USERID,login,2561,2026/10/09 20:41:00,vsys1,"
    "192.0.2.20,alice,,0,1,2700,0,0,globalprotect,,7290000404,0x8000000000000000,0,0,0,0,,"
    "fw01.example.internal,1,,,,,,,,,"
)
LINE = f"<14>Oct  9 20:41:00 fw01.example.internal {RECORD}"


def _engine(root: Path, *, stored_before_425: bool) -> QueryEngine:
    auto = AutoNormalizer(
        SourceSpec(source_id="fw", format="syslog"),
        REGISTRY.all(),
        REGISTRY.starter_ids,
        clock=lambda: NOW,
        tables=REGISTRY.tables,
    )
    row = auto.normalize(DecodedLine(text=LINE, bytes_invalid=False, truncated=False))
    assert row is not None and row["template_id"] == "paloalto_userid"
    if stored_before_425:
        row["message"] = RECORD  # the payload stood in for an unmapped message
    out = root / "source=fw" / "day=2026-10-09"
    out.mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist([row], schema=arrow_schema()), out / "part-0.parquet")
    engine = QueryEngine(root)
    engine.set_lookups(Lookups(geo=lambda _v: None, internal=lambda: lambda _v: False))
    return engine


def test_a_stored_userid_record_reads_as_a_plain_summary(tmp_path: Path) -> None:
    engine = _engine(tmp_path / "lake", stored_before_425=True)
    s = entity_summary(engine, QueryScope(None), "user", "alice", None, NAMES)
    (act,) = s.activities
    assert act.example == (
        "Palo Alto Networks User-ID: alice at 192.0.2.20, learned from globalprotect"
    )
    assert "USERID" not in act.example and RECORD not in act.example
    # View in Logs still finds the row.
    assert len(engine.run(act.search_sql, QueryScope(None)).rows) == 1


def test_a_new_userid_line_keeps_its_plain_message(tmp_path: Path) -> None:
    engine = _engine(tmp_path / "lake", stored_before_425=False)
    s = entity_summary(engine, QueryScope(None), "user", "alice", None, NAMES)
    (act,) = s.activities
    assert act.example == "User-ID login"


def test_without_template_names_the_summary_has_no_name(tmp_path: Path) -> None:
    engine = _engine(tmp_path / "lake", stored_before_425=True)
    (act,) = entity_summary(engine, QueryScope(None), "ip", "192.0.2.20").activities
    assert act.example == "alice at 192.0.2.20, learned from globalprotect"
