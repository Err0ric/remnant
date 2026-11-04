"""Saved-search parameters (SPEC 5.4).

`{{name}}` placeholders become DuckDB named parameters (`$name`) and values are bound by
the database driver. Values are never pasted into SQL text, so a parameter can change
what a query matches but never what the query is. `start` and `end` are always supplied
by the server from the requested time range.

Two more come from Identities at run time (ADR-0042 amendment 2026-11-04, D205), never
from the client: `{{person:<column>}}` is the person a name in that column belongs to
(the same key Investigate and AI usage use: lower case, `DOMAIN\\` removed, an
organization address reduced to its login, then the aliases an administrator set), and
`{{org_domains}}` is the list of organization email domains. The lookup tables are bound
as parameters, so a placeholder adds no text the guard has not seen; a name with no alias
is its own person, never guessed.
"""

import re
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.errors import ParamInvalidError, SearchInvalidError

PLACEHOLDER = re.compile(r"\{\{\s*([a-z_][a-z0-9_]{0,31})\s*\}\}")
PERSON = re.compile(r"\{\{\s*person:([a-z_][a-z0-9_]{0,63})\s*\}\}")
RESERVED = frozenset({"start", "end", "org_domains"})
# Bound by the server from Identities when a query uses {{person:...}} or {{org_domains}}.
IDENTITY_PARAMS = ("id_org", "id_from", "id_to")
MAX_STRING = 500

ParamType = Literal["int", "float", "string", "bool", "timestamp"]
ParamName = Annotated[str, StringConstraints(pattern=r"^[a-z_][a-z0-9_]{0,31}$")]


class ParamDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ParamName
    type: ParamType
    default: Any = None
    description: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def _check(self) -> "ParamDef":
        if self.name in RESERVED:
            raise ValueError(
                f"'{self.name}' is supplied by the time range and cannot be a parameter"
            )
        if self.default is not None:
            coerce(self, self.default)  # raises if the default does not fit the type
        return self


def placeholders(sql: str) -> set[str]:
    return set(PLACEHOLDER.findall(sql))


def uses_identities(sql: str) -> bool:
    """True when the query needs the Identities values (IDENTITY_PARAMS) bound."""
    return bool(PERSON.search(sql)) or "org_domains" in placeholders(sql)


def person_sql(column: str) -> str:
    """The person key of a name in `column`, in SQL over the bound Identities values:
    the deterministic key (as `identity.key_of`), then the administrator's aliases. A name
    with no alias is its own person; a blank name is NULL, never a person."""
    k = f"regexp_replace(lower(trim(CAST({column} AS VARCHAR))), '^[^\\\\@]*\\\\', '')"
    k = (
        f"(CASE WHEN list_contains($id_org, split_part({k}, '@', 2))"
        f" THEN split_part({k}, '@', 1) ELSE {k} END)"
    )
    return f"nullif(coalesce(list_extract($id_to, list_position($id_from, {k})), {k}), '')"


def compile_sql(sql: str) -> str:
    """Replace {{name}} with $name, {{person:col}} with the person key of that column, and
    {{org_domains}} with the bound domain list. Only names and columns that passed the
    patterns are ever emitted."""
    sql = PERSON.sub(lambda m: person_sql(m.group(1)), sql)
    return PLACEHOLDER.sub(
        lambda m: "$id_org" if m.group(1) == "org_domains" else f"${m.group(1)}", sql
    )


def check_definition(sql: str, params: list[ParamDef]) -> None:
    defined = {p.name for p in params}
    if len(defined) != len(params):
        raise SearchInvalidError("Parameter names must be unique")
    missing = placeholders(sql) - defined - RESERVED
    if missing:
        raise SearchInvalidError(f"Undefined placeholders: {', '.join(sorted(missing))}")


def coerce(defn: ParamDef, value: Any) -> Any:
    """Strict conversion; strings are accepted for every type (the CLI sends strings)."""
    try:
        if defn.type == "int":
            if isinstance(value, bool):
                raise ValueError
            out: Any = int(value) if isinstance(value, int | str) else None
            if out is None or not -(10**12) <= out <= 10**12:
                raise ValueError
            return out
        if defn.type == "float":
            if isinstance(value, bool) or not isinstance(value, int | float | str):
                raise ValueError
            return float(value)
        if defn.type == "bool":
            if isinstance(value, bool):
                return value
            if isinstance(value, str) and value.lower() in ("true", "false"):
                return value.lower() == "true"
            raise ValueError
        if defn.type == "timestamp":
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError
            return parsed.astimezone(UTC)
        if not isinstance(value, str) or len(value) > MAX_STRING:
            raise ValueError
        return value
    except (ValueError, TypeError) as exc:
        raise ParamInvalidError(f"Parameter '{defn.name}' must be a valid {defn.type}") from exc


def bind(
    defs: list[ParamDef], provided: dict[str, Any], start: datetime, end: datetime, sql: str
) -> dict[str, Any]:
    by_name = {d.name: d for d in defs}
    unknown = set(provided) - set(by_name)
    if unknown:
        raise ParamInvalidError(f"Unknown parameters: {', '.join(sorted(unknown))}")
    used = placeholders(sql)
    values: dict[str, Any] = {}
    for d in defs:
        if d.name not in used:
            continue
        if d.name in provided:
            values[d.name] = coerce(d, provided[d.name])
        elif d.default is not None:
            values[d.name] = coerce(d, d.default)
        else:
            raise ParamInvalidError(f"Parameter '{d.name}' is required")
    if "start" in used:
        values["start"] = start
    if "end" in used:
        values["end"] = end
    return values
