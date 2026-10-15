"""Suspicious presets (ADR-0016 row 3): named Simple searches shipped with the app.

They are only text for the search bar. Picking one fills the bar, where the analyst can
read and change it; the search runs through compile, the guard, and the caller's view
like any other.
"""

from functools import cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.search.simple import compile_search

PRESETS_FILE = Path(__file__).resolve().parents[1] / "content" / "presets" / "suspicious.yaml"


class Preset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=200)
    text: str = Field(min_length=1, max_length=2048)


def load_presets(path: Path = PRESETS_FILE) -> list[Preset]:
    """Every preset in the file, each checked to compile; a broken file is an error."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    presets = [Preset.model_validate(item) for item in data]
    ids = [p.id for p in presets]
    if len(ids) != len(set(ids)):
        raise ValueError("Preset ids must be unique")
    for p in presets:
        compile_search(p.text)  # raises SearchInvalidError on a bad entry
    return presets


@cache
def presets() -> tuple[Preset, ...]:
    return tuple(load_presets())
