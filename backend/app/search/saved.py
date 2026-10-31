"""Saved searches (SPEC 5.4): stored SQL with typed parameters, private or shared.

A saved search is only SQL plus metadata. It always runs as the person running it,
with their source scope (CLAUDE.md rule 13); the author's access never travels with it.
"""

import json
import re
import sqlite3
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.auth.users import User
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.engine.guard import guard
from app.meta.db import MetaDB
from app.search.params import ParamDef, check_definition, compile_sql

SearchId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
SourceId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_]{0,63}$")]
Visibility = Literal["private", "shared"]


# simple_text: the Simple search the SQL was compiled from (ADR-0009 row 7).
# library: the query library entry it was copied from, "<pack>/<id>@<version>" (ADR-0033).
OriginKey = Literal["ask_prompt", "llm_audit_id", "simple_text", "library"]
OriginValue = Annotated[str, StringConstraints(max_length=2_000)]


class SavedSearchIn(BaseModel):
    """What a user may set. Owner and timestamps come from the server."""

    model_config = ConfigDict(extra="forbid")

    id: SearchId
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    description: str = Field(default="", max_length=1000)
    tags: list[Tag] = Field(default_factory=list, max_length=20)
    visibility: Visibility = "private"
    sources: list[SourceId] | None = Field(default=None, max_length=200)
    mode: Literal["query", "ask"] = "query"
    sql: str = Field(min_length=1, max_length=20_000)
    params: list[ParamDef] = Field(default_factory=list, max_length=20)
    # Informational only (SPEC 5.4): where the SQL came from. Never executed or parsed.
    origin: dict[OriginKey, OriginValue] | None = Field(default=None, max_length=3)


class SavedSearch(SavedSearchIn):
    owner_id: str
    verified: bool = False
    created_at: str
    updated_at: str


def validate_definition(spec: SavedSearchIn) -> None:
    """Reject at save time what could never run: undefined placeholders, non-SELECT SQL."""
    check_definition(spec.sql, spec.params)
    guard(compile_sql(spec.sql), frozenset({"events"}), 100, 1000)


class SavedSearchStore:
    def __init__(self, meta: MetaDB, clock: Callable[[], datetime]) -> None:
        self._meta = meta
        self._clock = clock

    def visible(self, user: User, tag: str | None = None) -> list[SavedSearch]:
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT * FROM saved_searches WHERE owner_id = ? OR visibility = 'shared'"
                " ORDER BY name COLLATE NOCASE",
                (user.user_id,),
            ).fetchall()
        found = [_from_row(r) for r in rows]
        return [s for s in found if tag is None or tag in s.tags]

    def get(self, search_id: str, user: User) -> SavedSearch:
        """A private search of someone else is indistinguishable from a missing one."""
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT * FROM saved_searches WHERE search_id = ?", (search_id,)
            ).fetchone()
        if row is None or (row["visibility"] != "shared" and row["owner_id"] != user.user_id):
            raise NotFoundError("No such saved search")
        return _from_row(row)

    def create(self, spec: SavedSearchIn, owner: User) -> SavedSearch:
        validate_definition(spec)
        now = self._clock().isoformat()
        with self._meta.connect() as con:
            try:
                con.execute(
                    "INSERT INTO saved_searches"
                    " (search_id, name, description, owner_id, visibility,"
                    " tags, sources, mode, sql, params, origin, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        spec.id,
                        spec.name,
                        spec.description,
                        owner.user_id,
                        spec.visibility,
                        json.dumps(spec.tags),
                        None if spec.sources is None else json.dumps(spec.sources),
                        spec.mode,
                        spec.sql,
                        json.dumps([p.model_dump() for p in spec.params]),
                        None if spec.origin is None else json.dumps(spec.origin),
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError(f"A saved search with id {spec.id} already exists") from exc
        return self.get(spec.id, owner)

    def update(self, search_id: str, spec: SavedSearchIn, user: User) -> SavedSearch:
        current = self.get(search_id, user)
        if current.owner_id != user.user_id:
            raise ForbiddenError("Only the owner can edit a saved search")
        if spec.id != search_id:
            raise ConflictError("The id of a saved search cannot change")
        validate_definition(spec)
        with self._meta.connect() as con:
            con.execute(
                # Any edit clears verification: an admin vouched for the old definition.
                "UPDATE saved_searches SET name = ?, description = ?, visibility = ?, tags = ?,"
                " sources = ?, mode = ?, sql = ?, params = ?, origin = ?, updated_at = ?,"
                " verified = 0 WHERE search_id = ?",
                (
                    spec.name,
                    spec.description,
                    spec.visibility,
                    json.dumps(spec.tags),
                    None if spec.sources is None else json.dumps(spec.sources),
                    spec.mode,
                    spec.sql,
                    json.dumps([p.model_dump() for p in spec.params]),
                    None if spec.origin is None else json.dumps(spec.origin),
                    self._clock().isoformat(),
                    search_id,
                ),
            )
        return self.get(search_id, user)

    def set_verified(self, search_id: str, verified: bool, admin: User) -> SavedSearch:
        """Admins vouch for shared searches; verified ones become Ask examples (SPEC 5.7)."""
        current = self.get(search_id, admin)
        if verified and current.visibility != "shared":
            raise ConflictError("Share a search before marking it verified")
        if verified and _PLACEHOLDER.search(current.sql):
            raise ConflictError("Searches with parameters cannot be Ask examples")
        with self._meta.connect() as con:
            con.execute(
                "UPDATE saved_searches SET verified = ? WHERE search_id = ?",
                (int(verified), search_id),
            )
        return self.get(search_id, admin)

    def examples(self, user: User, question: str, limit: int = 3) -> list[SavedSearch]:
        """Verified searches this user can see, most similar to the question first."""
        words = _words(question)
        scored = []
        for s in self.visible(user):
            if not s.verified or _PLACEHOLDER.search(s.sql):
                continue
            origin = s.origin or {}
            text = " ".join(
                [s.name, s.description, origin.get("ask_prompt", ""), origin.get("simple_text", "")]
            )
            overlap = len(words & _words(text))
            if overlap:
                scored.append((overlap, s.name.lower(), s))
        scored.sort(key=lambda t: (-t[0], t[1]))
        return [s for _, _, s in scored[:limit]]

    def delete(self, search_id: str, user: User) -> SavedSearch:
        current = self.get(search_id, user)
        if current.owner_id != user.user_id and user.role != "admin":
            raise ForbiddenError("Only the owner or an administrator can delete a saved search")
        with self._meta.connect() as con:
            con.execute("DELETE FROM saved_searches WHERE search_id = ?", (search_id,))
        return current


_PLACEHOLDER = re.compile(r"\{\{")
_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "a an and are by for from in is of on or show me the to what which who with all".split()
)


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1}


def _from_row(r: sqlite3.Row) -> SavedSearch:
    return SavedSearch(
        id=r["search_id"],
        name=r["name"],
        description=r["description"],
        tags=json.loads(r["tags"]),
        visibility=r["visibility"],
        sources=None if r["sources"] is None else json.loads(r["sources"]),
        mode=r["mode"],
        sql=r["sql"],
        params=[ParamDef(**p) for p in json.loads(r["params"])],
        origin=None if r["origin"] is None else json.loads(r["origin"]),
        owner_id=r["owner_id"],
        verified=bool(r["verified"]),
        created_at=r["created_at"],
        updated_at=r["updated_at"],
    )
