"""Catalog answers are kept between changes (owner re-time, 2026-11-01: AI Watch opened
the database 22 times per load), and a change through the catalog shows at once."""

from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.ai.catalog import Catalog
from app.meta.db import MetaDB


def test_reads_are_kept_and_changes_show_at_once(tmp_path: Path) -> None:
    meta = MetaDB(tmp_path / "meta.sqlite")
    opened = []
    real = meta.connect

    @contextmanager
    def counted() -> Any:
        opened.append(1)
        with real() as con:
            yield con

    meta.connect = counted  # type: ignore[method-assign]  # count database opens
    cat = Catalog(meta)
    sid = cat.services()[0].id
    for _ in range(5):
        cat.services()
        cat.domain_table()
        cat.mcp_rules()
    assert len(opened) == 2  # services once, MCP rules once
    cat.set_status(sid, "approved", "", "admin")
    assert next(s for s in cat.services() if s.id == sid).status == "approved"
    cat.set_mcp_rule("filesystem", "not_approved", "", "admin")
    assert cat.mcp_status("filesystem") == "not_approved"
