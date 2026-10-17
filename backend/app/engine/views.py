"""Which sources a caller may read (CLAUDE.md rule 13, SPEC 3.6, ADR-0004).

Every query surface (UI, CLI, saved searches, Ask, the LLM gate) builds its scope from
this function. Admins read every source; everyone else reads the union of the sources
in their groups, and nothing when they have no groups. A client-supplied source list is
only ever a filter inside this scope, never a grant.
"""

from app.auth.users import User
from app.core.ids import RESERVED_SOURCE_PREFIX
from app.engine.duckdb import QueryEngine, QueryScope
from app.meta.db import MetaDB


def permitted_sources(meta: MetaDB, user: User) -> list[str] | None:
    """None means every source (admins). A list, possibly empty, is the exact allowance."""
    if user.role == "admin":
        return None
    with meta.connect() as con:
        rows = con.execute(
            "SELECT DISTINCT gs.source_id FROM user_groups ug"
            " JOIN group_sources gs ON gs.group_id = ug.group_id"
            " JOIN users u ON u.user_id = ug.user_id"
            " WHERE ug.user_id = ? AND u.disabled = 0 ORDER BY gs.source_id",
            (user.user_id,),
        ).fetchall()
    return [r[0] for r in rows]


def scope_sources(allowed: list[str] | None, requested: list[str] | None) -> list[str] | None:
    """Narrow the allowance by a client filter. The result never exceeds the allowance."""
    if allowed is None:
        return requested
    if requested is None:
        return list(allowed)
    permitted = set(allowed)
    return [s for s in requested if s in permitted]


def not_cloud_allowed(meta: MetaDB, engine: QueryEngine, scope: QueryScope) -> list[str]:
    """Sources in scope that may not leave for a model outside the internal network: not
    marked cloud_allowed now, or holding any event that was not cloud_allowed at ingest,
    or a draft sample. When the lake cannot be checked, every source in scope counts."""
    sources = engine.sources_in(scope)
    if not sources:
        return []
    with meta.connect() as con:
        labels = {
            r[0]: r[1]
            for r in con.execute("SELECT source_id, classification FROM sources").fetchall()
        }
    by_config = {
        s
        for s in sources
        if labels.get(s, "local_only") != "cloud_allowed" or s.startswith(RESERVED_SOURCE_PREFIX)
    }
    try:
        by_events = set(engine.local_only_sources(scope))
    except Exception:  # cannot prove the data is cloud_allowed: treat it as not
        by_events = set(sources)
    return sorted(by_config | by_events)
