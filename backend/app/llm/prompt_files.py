"""Versioned system prompts (CLAUDE.md security rule 2).

Each prompt is a file in `llm/prompts/` named `<name>.v<N>.md`. A changed prompt is a
new file with a new version, never an edit, so the hash recorded in `llm_calls` always
points at text that can be read back from the repository.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

PROMPT_DIR = Path(__file__).parent / "prompts"
_NAME = re.compile(r"^[a-z][a-z0-9_]*\.v[0-9]+$")


@dataclass(frozen=True, slots=True)
class Prompt:
    name: str
    text: str
    sha256: str

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.sha256[:12]}"


def load_prompt(name: str, directory: Path = PROMPT_DIR) -> Prompt:
    if not _NAME.fullmatch(name):
        raise ValueError(f"Prompt names look like ask.v1, not {name!r}")
    raw = (directory / f"{name}.md").read_bytes()
    return Prompt(name=name, text=raw.decode("utf-8"), sha256=hashlib.sha256(raw).hexdigest())
