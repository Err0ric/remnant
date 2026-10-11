"""Ask vocabulary: analyst terms mapped to SQL predicates over the events view (SPEC 5.7).

The vocabulary is trusted configuration (shipped in the repo, later extended by approved
templates). Every predicate must pass the query guard as a WHERE clause; a bad entry stops
startup instead of reaching a model.
"""

from functools import cache
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core import safeyaml
from app.core.errors import ConfigError, QueryRejectedError
from app.engine.guard import guard

BASE = Path(__file__).parent / "base.v1.yaml"
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class Term(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term: Text
    aliases: list[Text] = Field(default_factory=list, max_length=20)
    sql: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    note: Annotated[str, StringConstraints(max_length=300)] = ""


class Vocabulary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(ge=1, le=1)
    terms: list[Term] = Field(max_length=500)

    def for_prompt(self) -> list[dict[str, Any]]:
        return [t.model_dump(exclude_defaults=True) for t in self.terms]


def load_vocabulary(path: Path = BASE) -> Vocabulary:
    try:
        vocab = Vocabulary.model_validate(safeyaml.load(path.read_text("utf-8")))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise ConfigError(f"Ask vocabulary {path.name} is invalid: {exc}") from exc
    for t in vocab.terms:
        try:
            guard(f"SELECT 1 FROM events WHERE {t.sql}", frozenset({"events"}))  # noqa: S608  # repo-shipped predicate, checked here by the guard
        except QueryRejectedError as exc:
            raise ConfigError(f"Ask vocabulary term {t.term!r}: {exc}") from exc
    return vocab


@cache
def base_vocabulary() -> Vocabulary:
    return load_vocabulary()
