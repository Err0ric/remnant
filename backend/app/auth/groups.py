"""Source groups: named sets of sources granted to users (SPEC 3.6, ADR-0004).

Groups are per installation and never created or granted automatically. Every change
is audited with what it was before and after.
"""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.auth.users import User
from app.core.errors import ConflictError, NotFoundError, SourceRejectedError
from app.core.ids import new_id
from app.meta.audit import AuditLog
from app.meta.db import MetaDB


@dataclass(frozen=True, slots=True)
class Group:
    group_id: str
    name: str
    description: str
    source_ids: list[str]
    user_ids: list[str]


class GroupStore:
    def __init__(self, meta: MetaDB, audit: AuditLog, clock: Callable[[], datetime]) -> None:
        self._meta = meta
        self._audit = audit
        self._clock = clock

    def all(self) -> list[Group]:
        with self._meta.connect() as con:
            groups = con.execute(
                "SELECT group_id, name, description FROM source_groups ORDER BY name COLLATE NOCASE"
            ).fetchall()
            return [self._load(con, g["group_id"], g["name"], g["description"]) for g in groups]

    def create(self, name: str, description: str, actor: User, ip: str | None) -> Group:
        group_id = new_id()
        with self._meta.connect() as con:
            try:
                con.execute(
                    "INSERT INTO source_groups (group_id, name, description, created_at)"
                    " VALUES (?, ?, ?, ?)",
                    (group_id, name, description, self._clock().isoformat()),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError(f"A group named {name} already exists") from exc
        self._log("group.create", actor, ip, {"group_id": group_id, "name": name})
        return Group(group_id, name, description, [], [])

    def update(
        self, group_id: str, actor: User, ip: str | None, name: str | None, description: str | None
    ) -> Group:
        with self._meta.connect() as con:
            row = self._row(con, group_id)
            try:
                con.execute(
                    "UPDATE source_groups SET name = ?, description = ? WHERE group_id = ?",
                    (
                        name or row["name"],
                        row["description"] if description is None else description,
                        group_id,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError(f"A group named {name} already exists") from exc
        self._log(
            "group.update",
            actor,
            ip,
            {
                "group_id": group_id,
                "before": row["name"],
                "after": name or row["name"],
                "description_before": row["description"],
                "description_after": row["description"] if description is None else description,
            },
        )
        return self.get(group_id)

    def delete(self, group_id: str, actor: User, ip: str | None) -> None:
        with self._meta.connect() as con:
            row = self._row(con, group_id)
            before = self._load(con, group_id, row["name"], row["description"])
            con.execute("DELETE FROM source_groups WHERE group_id = ?", (group_id,))
        self._log(
            "group.delete",
            actor,
            ip,
            {
                "group_id": group_id,
                "name": before.name,
                "sources": before.source_ids,
                "users": before.user_ids,
            },
        )

    def set_sources(
        self, group_id: str, source_ids: list[str], actor: User, ip: str | None
    ) -> Group:
        wanted = sorted(set(source_ids))
        with self._meta.connect() as con:
            self._row(con, group_id)
            known = {r[0] for r in con.execute("SELECT source_id FROM sources")}
            unknown = [s for s in wanted if s not in known]
            if unknown:
                raise SourceRejectedError(f"Unknown sources: {', '.join(unknown[:5])}")
            before = [
                r[0]
                for r in con.execute(
                    "SELECT source_id FROM group_sources WHERE group_id = ? ORDER BY source_id",
                    (group_id,),
                )
            ]
            con.execute("DELETE FROM group_sources WHERE group_id = ?", (group_id,))
            con.executemany(
                "INSERT INTO group_sources (group_id, source_id) VALUES (?, ?)",
                [(group_id, s) for s in wanted],
            )
        self._log(
            "group.sources_set",
            actor,
            ip,
            {"group_id": group_id, "before": before, "after": wanted},
        )
        return self.get(group_id)

    def set_members(self, group_id: str, user_ids: list[str], actor: User, ip: str | None) -> Group:
        wanted = sorted(set(user_ids))
        with self._meta.connect() as con:
            self._row(con, group_id)
            known = {r[0] for r in con.execute("SELECT user_id FROM users")}
            unknown = [u for u in wanted if u not in known]
            if unknown:
                raise SourceRejectedError(f"Unknown users: {len(unknown)}")
            before = [
                r[0]
                for r in con.execute(
                    "SELECT user_id FROM user_groups WHERE group_id = ? ORDER BY user_id",
                    (group_id,),
                )
            ]
            con.execute("DELETE FROM user_groups WHERE group_id = ?", (group_id,))
            con.executemany(
                "INSERT INTO user_groups (user_id, group_id) VALUES (?, ?)",
                [(u, group_id) for u in wanted],
            )
        self._log(
            "group.members_set",
            actor,
            ip,
            {"group_id": group_id, "before": before, "after": wanted},
        )
        return self.get(group_id)

    def get(self, group_id: str) -> Group:
        with self._meta.connect() as con:
            row = self._row(con, group_id)
            return self._load(con, group_id, row["name"], row["description"])

    # --- helpers ---------------------------------------------------------------------

    @staticmethod
    def _row(con: sqlite3.Connection, group_id: str) -> sqlite3.Row:
        row = con.execute(
            "SELECT name, description FROM source_groups WHERE group_id = ?", (group_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError("No such group")
        return row  # type: ignore[no-any-return]  # sqlite3 rows are untyped

    @staticmethod
    def _load(con: sqlite3.Connection, group_id: str, name: str, description: str) -> Group:
        sources = [
            r[0]
            for r in con.execute(
                "SELECT source_id FROM group_sources WHERE group_id = ? ORDER BY source_id",
                (group_id,),
            )
        ]
        users = [
            r[0]
            for r in con.execute(
                "SELECT user_id FROM user_groups WHERE group_id = ? ORDER BY user_id", (group_id,)
            )
        ]
        return Group(group_id, name, description, sources, users)

    def _log(self, action: str, actor: User, ip: str | None, detail: dict[str, Any]) -> None:
        self._audit.write(action, "success", actor.user_id, ip, detail)
