"""Query library (ADR-0033): shipped query packs, read at start and never fetched.

A pack is `library/<pack>/pack.yaml`: queries in the saved-search format (SPEC 5.4) plus
`requires` (template ids, any one is enough; empty means any source), `group`, `why`,
`normal`, `suggested_schedule`, `flag`, and `expect` (checked in CI on the template
fixtures). Library SQL is ordinary SQL from a file: it runs through the guard on the
caller's `events` view like anything typed (rules 7 and 13). `why` and `normal` are
display text only and never go to a model.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

import structlog
import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from app.auth.users import User
from app.core import safeyaml
from app.core.errors import ConfigError, ConflictError
from app.engine.duckdb import QueryEngine, QueryScope
from app.search.params import RESERVED, ParamDef, placeholders
from app.search.saved import (
    SavedSearch,
    SavedSearchIn,
    SearchId,
    Tag,
    validate_definition,
)

log = structlog.get_logger(__name__)

LIBRARY_DIR = Path(__file__).resolve().parents[3] / "library"
PackId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_]{0,40}$")]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400)]
FLAG = re.compile(r"^(above|below) \d+$|^change \d+%$")
SEEN_DAYS = 30  # which templates the viewer's sources have used, for what is offered


class Expect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: int | None = Field(default=None, ge=0)
    rows_at_least: int | None = Field(default=None, ge=0)
    first_row: dict[str, Any] | None = None


class LibraryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: SearchId
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    description: str = Field(default="", max_length=1000)
    tags: list[Tag] = Field(default_factory=list, max_length=20)
    sql: str = Field(min_length=1, max_length=20_000)
    params: list[ParamDef] = Field(default_factory=list, max_length=20)
    group: Text
    requires: list[Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{1,64}$")]] = Field(
        default_factory=list, max_length=20
    )
    why: Text
    normal: Text
    suggested_schedule: Literal["hourly", "daily"] | None = None
    flag: str | None = None
    expect: Expect | None = None

    def spec(self, origin: str) -> SavedSearchIn:
        return SavedSearchIn(
            id=self.id, name=self.name, description=self.description,
            tags=[*self.tags, "library"][:20], visibility="private", mode="query",
            sql=self.sql, params=self.params, origin={"library": origin},
        )  # fmt: skip


class Pack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    id: PackId
    name: Text
    version: Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+$")]
    description: str = Field(default="", max_length=1000)
    queries: list[LibraryQuery] = Field(min_length=1, max_length=100)

    def origin(self, q: LibraryQuery) -> str:
        return f"{self.id}/{q.id}@{self.version}"


def check(pack: Pack) -> None:
    """What the schema cannot say: SQL that passes the guard, placeholders other than start
    and end only with a default (the Library loads the query with the default written in),
    a valid flag, unique ids."""
    ids = [q.id for q in pack.queries]
    if len(ids) != len(set(ids)):
        raise ConfigError(f"Pack {pack.id}: query ids repeat")
    for q in pack.queries:
        validate_definition(q.spec(pack.origin(q)))
        defaults = {p.name for p in q.params if p.default is not None}
        missing = placeholders(q.sql) - RESERVED - defaults
        if missing:
            raise ConfigError(f"{pack.id}/{q.id}: give a default for {', '.join(sorted(missing))}")
        if q.flag is not None and not FLAG.match(q.flag):
            raise ConfigError(
                f"{pack.id}/{q.id}: flag must be 'above N', 'below N', or 'change N%'"
            )


def load(path: Path) -> Pack:
    try:
        raw = safeyaml.load(path.read_text(encoding="utf-8"))
        pack = Pack.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ConfigError(f"{path.parent.name}: {str(exc)[:400]}") from exc
    if pack.id != path.parent.name:
        raise ConfigError(f"{path}: pack id {pack.id} does not match its folder")
    check(pack)
    return pack


def load_dir(root: Path) -> list[Pack]:
    """Every valid pack under `root`; a broken pack is logged and left out."""
    out = []
    for path in sorted(root.glob("*/pack.yaml")) if root.is_dir() else []:
        try:
            out.append(load(path))
        except ConfigError as exc:
            log.warning("library.pack_rejected", pack=path.parent.name, reason=str(exc)[:300])
    return out


def literal(value: Any) -> str:
    """A parameter default written into SQL for the editor: text quoted, numbers as is."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def editor_sql(q: LibraryQuery) -> str:
    """The SQL the Search editor gets: `{{start}}` and `{{end}}` stay (the range fills
    them); other placeholders get their default written in, to edit in place."""
    sql = q.sql
    for p in q.params:
        if p.default is not None:
            sql = sql.replace("{{" + p.name + "}}", literal(p.default))
    return sql


class Library:
    def __init__(self, packs: list[Pack]) -> None:
        self.packs = packs

    def find(self, pack_id: str, query_id: str) -> tuple[Pack, LibraryQuery] | None:
        for p in self.packs:
            if p.id == pack_id:
                for q in p.queries:
                    if q.id == query_id:
                        return p, q
        return None

    def templates_seen(self, engine: QueryEngine, allowed: list[str] | None) -> set[str]:
        """Templates the viewer's sources produced recently (row 3: from template_id
        counts, so a template with no events offers nothing)."""
        now = datetime.now(UTC)
        res = engine.run(
            "SELECT DISTINCT template_id FROM events WHERE template_id IS NOT NULL",
            QueryScope(allowed, now - timedelta(days=SEEN_DAYS), now),
            timeout_s=20, intel=False, name="library.templates",
        )  # fmt: skip
        return {str(r[0]) for r in res.rows}

    @staticmethod
    def offered(q: LibraryQuery, seen: set[str]) -> bool:
        return not q.requires or bool(seen & set(q.requires))


def copy(store: Any, pack: Pack, q: LibraryQuery, user: User) -> SavedSearch:
    """Save as my own: a private saved search, the user's from now on (row 7)."""
    spec = q.spec(pack.origin(q))
    for n in range(1, 50):
        try:
            made: SavedSearch = store.create(spec, user)
            return made
        except ConflictError:
            spec = spec.model_copy(update={"id": f"{q.id}_{n + 1}"[:64]})
    raise ConflictError("Too many copies of this query; rename one")


def copies(searches: list[SavedSearch], user: User) -> dict[str, SavedSearch]:
    """The user's own copies, keyed by "<pack>/<id>", newest first wins."""
    out: dict[str, SavedSearch] = {}
    for s in sorted(searches, key=lambda s: s.updated_at):
        lib = (s.origin or {}).get("library")
        if lib and s.owner_id == user.user_id:
            out[lib.split("@", 1)[0]] = s
    return out


def threshold(
    flag: str | None,
) -> tuple[Literal["above", "below", "change_pct"] | None, float | None]:
    """A pack's flag as a schedule threshold: "above 0", "below 5", "change 100%"."""
    if not flag:
        return None, None
    word, _, number = flag.partition(" ")
    value = float(number.rstrip("%"))
    if word == "change":
        return "change_pct", value
    return ("above" if word == "above" else "below"), value
