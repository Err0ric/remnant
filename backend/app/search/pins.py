"""Pins (D259): each user's own short list of saved searches and dashboards, shown in the
rail's Pinned region. Kept on the server, so pins follow the user to any browser.

A pin names its target by kind and id only. Whether the caller may still see the target
is decided by the caller of this store from the targets' own stores (saved searches and
dashboards run with the caller's rights, CLAUDE.md rule 2.13); a pin whose target is gone
or hidden is pruned when the user pins something new, so it never holds a place.
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from datetime import datetime
from typing import Literal

from app.core.errors import ConflictError
from app.meta.db import MetaDB

PinKind = Literal["search", "dashboard"]
# The rail shows them all without scrolling (DESIGN.md 5): the same five as Recent.
MAX_PINS = 5


class PinStore:
    def __init__(self, meta: MetaDB, clock: Callable[[], datetime]) -> None:
        self._meta = meta
        self._clock = clock

    def list(self, user_id: str) -> list[tuple[PinKind, str]]:
        """The user's pins, oldest first: a new pin goes last."""
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT kind, target_id FROM pins WHERE user_id = ? ORDER BY pinned_at, rowid",
                (user_id,),
            ).fetchall()
        return [(r["kind"], r["target_id"]) for r in rows]

    def add(
        self, user_id: str, kind: PinKind, target_id: str, live: Collection[tuple[str, str]]
    ) -> bool:
        """Pins a target the caller may see (`live` holds every such target). False when it
        was pinned already. Pins of targets no longer in `live` are dropped first."""
        with self._meta.connect() as con:
            held = con.execute(
                "SELECT kind, target_id FROM pins WHERE user_id = ?", (user_id,)
            ).fetchall()
            for r in held:
                if (r["kind"], r["target_id"]) not in live:
                    con.execute(
                        "DELETE FROM pins WHERE user_id = ? AND kind = ? AND target_id = ?",
                        (user_id, r["kind"], r["target_id"]),
                    )
            kept = {(r["kind"], r["target_id"]) for r in held} & set(live)
            if (kind, target_id) in kept:
                return False
            if len(kept) >= MAX_PINS:
                raise ConflictError(f"At most {MAX_PINS} pins. Unpin one first.")
            con.execute(
                "INSERT INTO pins (user_id, kind, target_id, pinned_at) VALUES (?, ?, ?, ?)",
                (user_id, kind, target_id, self._clock().isoformat()),
            )
        return True

    def remove(self, user_id: str, kind: PinKind, target_id: str) -> bool:
        with self._meta.connect() as con:
            cur = con.execute(
                "DELETE FROM pins WHERE user_id = ? AND kind = ? AND target_id = ?",
                (user_id, kind, target_id),
            )
        return cur.rowcount > 0
