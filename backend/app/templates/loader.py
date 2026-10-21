"""Load and validate template files (SPEC 4).

Starter templates ship in the repository; user templates live in data/templates/. Drafts
(data/templates/drafts/) are never loaded here. A file that fails validation, or whose
inline tests fail, is reported with a readable message and left out; it never stops the
other templates from loading.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError
from pydantic_core import ErrorDetails

from app.core import safeyaml
from app.templates.tables import LookupTable
from app.templates.tester import run_tests
from app.templates.validator import Template

MAX_TEMPLATE_BYTES = 256 * 1024


@dataclass(frozen=True, slots=True)
class LoadProblem:
    file: str
    message: str


def parse_template(text: str) -> Template:
    """Validate one template document; raises ValueError with readable messages."""
    try:
        doc = safeyaml.load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"not valid YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError("a template is one YAML mapping")
    try:
        return Template.model_validate(doc)
    except ValidationError as exc:
        raise ValueError("; ".join(_readable(e) for e in exc.errors()[:10])) from exc


def load_dir(
    directory: Path, tables: Mapping[str, LookupTable] | None = None
) -> tuple[dict[str, Template], list[LoadProblem]]:
    templates: dict[str, Template] = {}
    problems: list[LoadProblem] = []
    tables = tables or {}
    if not directory.is_dir():
        return templates, problems
    for path in sorted(directory.glob("*.yaml")):
        name = path.name
        try:
            if path.stat().st_size > MAX_TEMPLATE_BYTES:
                raise ValueError(f"larger than {MAX_TEMPLATE_BYTES // 1024} KB")
            template = parse_template(path.read_text("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            problems.append(LoadProblem(name, str(exc)))
            continue
        if path.stem != template.id:
            problems.append(LoadProblem(name, f"file name must be {template.id}.yaml"))
            continue
        lookup = template.mapping.lookup
        if lookup is not None and lookup.table not in tables:
            problems.append(LoadProblem(name, f"lookup table {lookup.table} is not available"))
            continue
        try:
            failed = [t for t in run_tests(template, tables) if not t.passed]
        except Exception as exc:  # a broken template must not stop the others loading
            problems.append(LoadProblem(name, f"tests could not run: {type(exc).__name__}"))
            continue
        if failed:
            first = failed[0]
            problems.append(
                LoadProblem(name, f"test {first.name!r} failed: {'; '.join(first.problems)}")
            )
            continue
        templates[template.id] = template
    return templates, problems


def load_all(
    starter: Path, user: Path, tables: Mapping[str, LookupTable] | None = None
) -> tuple[dict[str, Template], list[LoadProblem]]:
    """Starter and user templates; an id may exist in only one place."""
    found, problems = load_dir(starter, tables)
    mine, more = load_dir(user, tables)
    problems.extend(more)
    for template_id, template in mine.items():
        if template_id in found:
            problems.append(
                LoadProblem(f"{template_id}.yaml", "id already used by a starter template")
            )
            continue
        found[template_id] = template
    return found, problems


def _readable(error: ErrorDetails) -> str:
    loc = ".".join(str(p) for p in error["loc"] if p != "json_")
    msg = str(error["msg"]).removeprefix("Value error, ")
    return f"{loc}: {msg}" if loc else msg
