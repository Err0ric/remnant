"""Which sources a caller may read (CLAUDE.md rule 13, SPEC 3.6, ADR-0004).

Every query surface (UI, CLI, saved searches, Ask, the LLM gate) builds its scope from
this function. Admins read every source; everyone else reads the union of the sources
in their groups, and nothing when they have no groups. A client-supplied source list is
only ever a filter inside this scope, never a grant.
"""

from app.auth.users import User
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
