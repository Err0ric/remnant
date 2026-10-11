"""Shared lookup tables for templates, such as the Windows event id map (SPEC 4.4).

One table maps a key (for Windows, "<channel>:<event id>") to the OCSF class, activity,
status, and severity, so NXLog, Snare, Winlogbeat, and EVTX templates classify the same
event the same way. Tables live in templates/starter/maps/ and are validated at load.
"""

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from app.core import safeyaml

OcsfId = Annotated[int, Field(ge=0, le=999_999)]
SmallId = Annotated[int, Field(ge=0, le=99)]


class LookupEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    class_uid: OcsfId
    activity_id: SmallId | None = None
    status_id: SmallId | None = None
    severity_id: Literal[0, 1, 2, 3, 4, 5, 6, 99] | None = None
    label: Annotated[str, StringConstraints(max_length=200)] = ""
    # Which user acted: the one in Subject* fields, or (logons) the one in Target*.
    actor: Literal["subject", "target"] = "subject"


class LookupTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    id: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,63}$")]
    description: Annotated[str, StringConstraints(max_length=2000)] = ""
    entries: dict[Annotated[str, StringConstraints(max_length=200)], LookupEntry] = Field(
        max_length=5000
    )


def load_tables(directory: Path) -> tuple[dict[str, LookupTable], list[tuple[str, str]]]:
    tables: dict[str, LookupTable] = {}
    problems: list[tuple[str, str]] = []
    if not directory.is_dir():
        return tables, problems
    for path in sorted(directory.glob("*.yaml")):
        try:
            table = LookupTable.model_validate(safeyaml.load(path.read_text("utf-8")))
        except (OSError, UnicodeDecodeError, yaml.YAMLError, ValidationError) as exc:
            problems.append((path.name, str(exc).splitlines()[0][:300]))
            continue
        if path.stem != table.id:
            problems.append((path.name, f"file name must be {table.id}.yaml"))
            continue
        tables[table.id] = table
    return tables, problems
