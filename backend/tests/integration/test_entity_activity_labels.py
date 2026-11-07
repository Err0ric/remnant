"""Person page "How it connects": activities carry plain names. Palo Alto User-ID lines
read as "User-ID login", and a line whose message is a whole delimited record (or empty)
is named by its template, never by the record with its digits masked."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from app.core.schema import COLUMN_NAMES, arrow_schema
from app.engine.duckdb import QueryEngine, QueryScope
from app.ingest.normalizer import SourceSpec
from app.ingest.records import DecodedLine
from app.meta.db import MetaDB
from app.search.entities import entity_graph
from app.templates.registry import STARTER_DIR, TemplateRegistry
from app.templates.router import AutoNormalizer

NOW = datetime(2026, 10, 9, 21, 0, tzinfo=UTC)
REGISTRY = TemplateRegistry(STARTER_DIR, Path("/nonexistent"))
NAMES = {t.id: t.name for t in REGISTRY.all()}

HEAD = "<14>Oct  9 20:4{m}:00 pa-fw01 1,2026/10/09 20:4{m}:00,012345678901,USERID,"
USERID = [
    # A GlobalProtect mapping: no data source name, the case seen on a real install.
    HEAD.format(m=1) + "login,2561,2026/10/09 20:41:00,vsys1,192.168.10.20,alice,,0,1,2700,0,0,"
    "globalprotect,,7290000404,0x8000000000000000,0,0,0,0,,pa-fw01,1,,,,,,,,,",
    HEAD.format(m=2) + "logout,2561,2026/10/09 20:42:00,vsys1,192.168.10.20,alice,,0,1,0,0,0,"
    "globalprotect,,7290000405,0x0,0,0,0,0,,pa-fw01,1,,,,,,,,,",
    HEAD.format(m=3) + "login,2561,2026/10/09 20:43:00,vsys1,10.20.1.5,alice,"
    "dc01.example.internal,0,1,2700,0,0,ad-dc,syslog,7290000406,0x0,0,0,0,0,,pa-fw01",
]


def _row(**values: Any) -> dict[str, Any]:
    row: dict[str, Any] = dict.fromkeys(COLUMN_NAMES)
    row.update(
        event_id=f"e-{values['raw'][-8:]}",
        source_id="fw",
        template_version="1",
        time=NOW,
        time_observed=NOW,
        raw_bytes_invalid=False,
        parse_status="ok",
        classification="local_only",
        owner_id="system",
    )
    row.update(values)
    return row


def _lake(root: Path) -> None:
    auto = AutoNormalizer(
        SourceSpec(source_id="fw", format="syslog"),
        REGISTRY.all(),
        REGISTRY.starter_ids,
        clock=lambda: NOW,
        tables=REGISTRY.tables,
    )
    rows = [
        auto.normalize(DecodedLine(text=t, bytes_invalid=False, truncated=False)) for t in USERID
    ]
    parsed = [r for r in rows if r is not None]
    assert all(r["template_id"] == "paloalto_userid" for r in parsed)
    # A template that mapped no message: the payload record stands in for it.
    record = "1,2026/10/09 20:44:00,012345678901,TRAFFIC,end,2561,x,y,z,alice,a,b,c"
    parsed.append(
        _row(
            template_id="paloalto_traffic",
            class_uid=4001,
            actor_user_name="alice",
            message=record,
            raw=f"<14>Oct  9 20:44:00 pa-fw01 {record}",
        )
    )
    parsed.append(
        _row(
            template_id="generic_syslog",
            actor_user_name="alice",
            message=None,
            raw="<14>Oct  9 20:45:00 pa-fw01 -",
        )
    )
    parsed.append(
        _row(
            template_id="generic_syslog",
            actor_user_name="alice",
            message="session opened for alice by (uid=0)",
            raw="<14>Oct  9 20:46:00 h x",
        )
    )
    out = root / "source=fw" / "day=2026-10-09"
    out.mkdir(parents=True)
    schema = arrow_schema()
    table = pa.Table.from_pylist(parsed, schema=schema)
    pq.write_table(table, out / "part-0.parquet")


def test_activities_have_plain_names_and_searches_that_find_them(tmp_path: Path) -> None:
    _lake(tmp_path / "lake")
    engine = QueryEngine(tmp_path / "lake")
    meta = MetaDB(tmp_path / "meta.sqlite")
    g = entity_graph(engine, meta, None, QueryScope(None), "user", "alice", None, NAMES)
    acts = {c.label: c for c in g.cards if c.lane == 2}
    assert set(acts) == {
        "User-ID login",
        "User-ID logout",
        "Palo Alto Networks traffic",
        "Other event",
        "session opened for alice by (uid=#)",
    }, set(acts)
    assert not any("#,#" in label for label in acts)  # no masked record anywhere
    assert acts["User-ID login"].events == 2 and acts["User-ID login"].sublabel == "Authentication"
    # Each card's search finds exactly the events it counts.
    for card in acts.values():
        assert card.search_sql
        res = engine.run(card.search_sql, QueryScope(None))
        assert len(res.rows) == card.events, card.label


def test_without_template_names_the_class_names_the_activity(tmp_path: Path) -> None:
    _lake(tmp_path / "lake")
    engine = QueryEngine(tmp_path / "lake")
    g = entity_graph(
        engine, MetaDB(tmp_path / "meta.sqlite"), None, QueryScope(None), "user", "alice"
    )
    labels = {c.label for c in g.cards if c.lane == 2}
    assert "Network activity event" in labels and "Other event" in labels
