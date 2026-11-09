"""Which templates read each Automatic source's lines recently (ADR-0012), for suggested
source groups (SPEC 3.6, D22). Fixed SQL on the full events view, through the guard; it
returns template ids and source ids only, never event content."""

from __future__ import annotations

from datetime import timedelta

from app.core import clock
from app.engine.duckdb import QueryEngine, QueryScope

SEEN_DAYS = 30  # as the query library reads it
SQL = "SELECT source_id, template_id FROM events WHERE template_id IS NOT NULL GROUP BY 1, 2"


def templates_by_source(engine: QueryEngine, source_ids: list[str]) -> dict[str, set[str]]:
    if not source_ids:
        return {}
    now = clock.now()
    res = engine.run(
        SQL,
        QueryScope(sorted(source_ids), now - timedelta(days=SEEN_DAYS), now),
        timeout_s=20,
        intel=False,
        name="groups.templates",
    )
    out: dict[str, set[str]] = {}
    for source_id, template_id in res.rows:
        out.setdefault(str(source_id), set()).add(str(template_id))
    return out
