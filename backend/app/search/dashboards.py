"""Dashboards (ADR-0034): named, personal or shared pages of schedule panels.

A dashboard holds panels; a panel is a schedule shown with a section, a position, and a
size. Who sees what is unchanged (SPEC 5.5): a viewer sees a dashboard they own, a shared
one, or any as an admin, and a panel's numbers only when they may read every source its
run read (the API marks the rest Restricted). Flagged runs collect in Needs attention
until acknowledged; an acknowledgement holds until the next flagged run.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from app.auth.users import User
from app.core.errors import ForbiddenError, NotFoundError, ParamInvalidError
from app.core.ids import new_id
from app.meta.db import MetaDB

PanelSize = Literal["tile", "third", "half", "full"]
PanelView = Literal["table", "bars"]
MAX_DASHBOARDS_PER_USER = 50
MAX_PANELS = 200
DEFAULT_NAME = "My dashboard"


@dataclass(frozen=True, slots=True)
class Panel:
    schedule_id: str
    section: str
    position: int
    size: PanelSize
    view: PanelView


@dataclass(frozen=True, slots=True)
class Dashboard:
    dashboard_id: str
    name: str
    owner_id: str
    shared: bool
    created_at: str
    updated_at: str
    panels: list[Panel]
    acks: dict[str, str]  # schedule id -> run id acknowledged
    sections: list[str] = field(default_factory=list)  # in their stored order


def can_edit(d: Dashboard, user: User) -> bool:
    return user.role == "admin" or d.owner_id == user.user_id


def sees(d: Dashboard, user: User) -> bool:
    return user.role == "admin" or d.owner_id == user.user_id or d.shared


class DashboardStore:
    def __init__(self, meta: MetaDB, clock: Callable[[], datetime]) -> None:
        self._meta = meta
        self._clock = clock

    def _now(self) -> str:
        return self._clock().isoformat()

    # --- reading ---------------------------------------------------------------------

    def _load(self, con: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[Dashboard]:
        out = []
        for r in rows:
            did = r["dashboard_id"]
            panels = [
                Panel(p["schedule_id"], p["section"], p["position"], p["size"], p["view"])
                for p in con.execute(
                    "SELECT * FROM dashboard_panels WHERE dashboard_id = ?"
                    " ORDER BY position, schedule_id",
                    (did,),
                )
            ]
            sections = [
                r2["name"]
                for r2 in con.execute(
                    "SELECT name FROM dashboard_sections WHERE dashboard_id = ?"
                    " ORDER BY position, name",
                    (did,),
                )
            ]
            acks = {
                a["schedule_id"]: a["run_id"]
                for a in con.execute(
                    "SELECT schedule_id, run_id FROM dashboard_acks WHERE dashboard_id = ?",
                    (did,),
                )
            }
            out.append(
                Dashboard(
                    did,
                    r["name"],
                    r["owner_id"],
                    bool(r["shared"]),
                    r["created_at"],
                    r["updated_at"],
                    panels,
                    acks,
                    sections,
                )
            )
        return out

    def visible(self, user: User) -> list[Dashboard]:
        """The viewer's own first (oldest first), then shared ones, then (admins) the rest."""
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT * FROM dashboards ORDER BY owner_id <> ?, shared, created_at, name",
                (user.user_id,),
            ).fetchall()
            return [d for d in self._load(con, rows) if sees(d, user)]

    def get(self, dashboard_id: str, user: User) -> Dashboard:
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT * FROM dashboards WHERE dashboard_id = ?", (dashboard_id,)
            ).fetchall()
            found = self._load(con, rows)
        if not found or not sees(found[0], user):
            raise NotFoundError("No such dashboard")
        return found[0]

    def _editable(self, dashboard_id: str, user: User) -> Dashboard:
        d = self.get(dashboard_id, user)
        if not can_edit(d, user):
            raise ForbiddenError("Only the owner or an administrator can change this dashboard")
        return d

    # --- dashboards ------------------------------------------------------------------

    def create(self, user: User, name: str, shared: bool) -> Dashboard:
        with self._meta.connect() as con:
            (n,) = con.execute(
                "SELECT count(*) FROM dashboards WHERE owner_id = ?", (user.user_id,)
            ).fetchone()
            if n >= MAX_DASHBOARDS_PER_USER:
                raise ParamInvalidError(f"At most {MAX_DASHBOARDS_PER_USER} dashboards each")
            did, now = new_id(), self._now()
            con.execute(
                "INSERT INTO dashboards (dashboard_id, name, owner_id, shared, created_at,"
                " updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (did, name, user.user_id, int(shared), now, now),
            )
        return self.get(did, user)

    def default_for(self, user: User) -> Dashboard:
        """The user's first own dashboard, made ("My dashboard") when they have none."""
        own = [d for d in self.visible(user) if d.owner_id == user.user_id]
        return own[0] if own else self.create(user, DEFAULT_NAME, False)

    def update(
        self, dashboard_id: str, user: User, name: str | None, shared: bool | None
    ) -> tuple[Dashboard, Dashboard]:
        before = self._editable(dashboard_id, user)
        with self._meta.connect() as con:
            con.execute(
                "UPDATE dashboards SET name = coalesce(?, name), shared = coalesce(?, shared),"
                " updated_at = ? WHERE dashboard_id = ?",
                (name, None if shared is None else int(shared), self._now(), dashboard_id),
            )
        return before, self.get(dashboard_id, user)

    def delete(self, dashboard_id: str, user: User) -> Dashboard:
        d = self._editable(dashboard_id, user)
        with self._meta.connect() as con:
            con.execute("DELETE FROM dashboards WHERE dashboard_id = ?", (dashboard_id,))
        return d

    # --- panels ----------------------------------------------------------------------

    def set_panel(
        self,
        dashboard_id: str,
        user: User,
        schedule_id: str,
        section: str | None = None,
        position: int | None = None,
        size: PanelSize | None = None,
        view: PanelView | None = None,
    ) -> tuple[bool, Dashboard]:
        """Add the schedule's panel (at the end of its section) or change it. The caller
        checks that the user may see the schedule. Returns (added, dashboard)."""
        d = self._editable(dashboard_id, user)
        existing = {p.schedule_id: p for p in d.panels}
        now = self._now()
        with self._meta.connect() as con:
            if schedule_id not in existing:
                if len(d.panels) >= MAX_PANELS:
                    raise ParamInvalidError(f"At most {MAX_PANELS} panels on a dashboard")
                last = max((p.position for p in d.panels), default=0)
                con.execute(
                    "INSERT INTO dashboard_panels (dashboard_id, schedule_id, section,"
                    " position, size, view) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        dashboard_id,
                        schedule_id,
                        section or "",
                        position if position is not None else last + 1,
                        size or "third",
                        view or "table",
                    ),
                )
            else:
                con.execute(
                    "UPDATE dashboard_panels SET section = coalesce(?, section),"
                    " position = coalesce(?, position), size = coalesce(?, size),"
                    " view = coalesce(?, view) WHERE dashboard_id = ? AND schedule_id = ?",
                    (section, position, size, view, dashboard_id, schedule_id),
                )
            if section:
                _ensure_section(con, dashboard_id, section)
            con.execute(
                "UPDATE dashboards SET updated_at = ? WHERE dashboard_id = ?", (now, dashboard_id)
            )
        return schedule_id not in existing, self.get(dashboard_id, user)

    def remove_panel(self, dashboard_id: str, user: User, schedule_id: str) -> None:
        d = self._editable(dashboard_id, user)
        if schedule_id not in {p.schedule_id for p in d.panels}:
            raise NotFoundError("That panel is not on this dashboard")
        with self._meta.connect() as con:
            con.execute(
                "DELETE FROM dashboard_panels WHERE dashboard_id = ? AND schedule_id = ?",
                (dashboard_id, schedule_id),
            )
            con.execute(
                "DELETE FROM dashboard_acks WHERE dashboard_id = ? AND schedule_id = ?",
                (dashboard_id, schedule_id),
            )

    def reorder(self, dashboard_id: str, user: User, order: list[str]) -> Dashboard:
        """Positions 1..n in the given order; panels not listed keep theirs after them."""
        d = self._editable(dashboard_id, user)
        on = {p.schedule_id for p in d.panels}
        if set(order) - on or len(order) != len(set(order)):
            raise ParamInvalidError("Give each panel on this dashboard once")
        rest = [p.schedule_id for p in d.panels if p.schedule_id not in set(order)]
        with self._meta.connect() as con:
            for i, sid in enumerate([*order, *rest], start=1):
                con.execute(
                    "UPDATE dashboard_panels SET position = ? WHERE dashboard_id = ?"
                    " AND schedule_id = ?",
                    (i, dashboard_id, sid),
                )
        return self.get(dashboard_id, user)

    def set_layout(
        self, dashboard_id: str, user: User, layout: list[tuple[str, list[str]]]
    ) -> tuple[Dashboard, Dashboard]:
        """The whole arrangement at once (drag and drop, keyboard moves, section order and
        delete): sections in order, each with its panels in order; "" is no section. Every
        panel on the dashboard appears exactly once. Returns (before, after)."""
        before = self._editable(dashboard_id, user)
        on = [p.schedule_id for p in before.panels]
        given = [sid for _, ids in layout for sid in ids]
        if sorted(given) != sorted(on):
            raise ParamInvalidError("Give each panel on this dashboard once")
        names = [name for name, _ in layout]
        if len(names) != len(set(names)):
            raise ParamInvalidError("Each section once")
        for name in names:
            _check_section_name(name, allow_empty=True)
        with self._meta.connect() as con:
            con.execute("DELETE FROM dashboard_sections WHERE dashboard_id = ?", (dashboard_id,))
            pos = 0
            for rank, (name, ids) in enumerate(layout, start=1):
                if name:
                    con.execute(
                        "INSERT INTO dashboard_sections (dashboard_id, name, position)"
                        " VALUES (?, ?, ?)",
                        (dashboard_id, name, rank),
                    )
                for sid in ids:
                    pos += 1
                    con.execute(
                        "UPDATE dashboard_panels SET section = ?, position = ?"
                        " WHERE dashboard_id = ? AND schedule_id = ?",
                        (name, pos, dashboard_id, sid),
                    )
            con.execute(
                "UPDATE dashboards SET updated_at = ? WHERE dashboard_id = ?",
                (self._now(), dashboard_id),
            )
        return before, self.get(dashboard_id, user)

    def rename_section(self, dashboard_id: str, user: User, old: str, new: str) -> Dashboard:
        d = self._editable(dashboard_id, user)
        _check_section_name(new)
        if old not in d.sections:
            raise NotFoundError("No such section on this dashboard")
        if new != old and new in d.sections:
            raise ParamInvalidError("There is already a section with that name")
        with self._meta.connect() as con:
            con.execute(
                "UPDATE dashboard_sections SET name = ? WHERE dashboard_id = ? AND name = ?",
                (new, dashboard_id, old),
            )
            con.execute(
                "UPDATE dashboard_panels SET section = ? WHERE dashboard_id = ? AND section = ?",
                (new, dashboard_id, old),
            )
        return self.get(dashboard_id, user)

    def acknowledge(self, dashboard_id: str, user: User, schedule_id: str, run_id: str) -> None:
        """Clear a flagged run from Needs attention until the next flagged run. Anyone who
        sees the dashboard and may read the run (checked by the caller) may acknowledge."""
        d = self.get(dashboard_id, user)
        if schedule_id not in {p.schedule_id for p in d.panels}:
            raise NotFoundError("That panel is not on this dashboard")
        with self._meta.connect() as con:
            con.execute(
                "INSERT INTO dashboard_acks (dashboard_id, schedule_id, run_id, user_id,"
                " acked_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT (dashboard_id, schedule_id)"
                " DO UPDATE SET run_id = excluded.run_id, user_id = excluded.user_id,"
                " acked_at = excluded.acked_at",
                (dashboard_id, schedule_id, run_id, user.user_id, self._now()),
            )


MAX_SECTION = 60


def _check_section_name(name: str, allow_empty: bool = False) -> None:
    if (not name and not allow_empty) or len(name) > MAX_SECTION or name != name.strip():
        raise ParamInvalidError(f"A section name is 1 to {MAX_SECTION} characters")


def _ensure_section(con: sqlite3.Connection, dashboard_id: str, name: str) -> None:
    """A section a panel names exists, after the others."""
    _check_section_name(name)
    con.execute(
        "INSERT INTO dashboard_sections (dashboard_id, name, position)"
        " SELECT ?, ?, coalesce(max(position), 0) + 1 FROM dashboard_sections"
        " WHERE dashboard_id = ? ON CONFLICT (dashboard_id, name) DO NOTHING",
        (dashboard_id, name, dashboard_id),
    )
