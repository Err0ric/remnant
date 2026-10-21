"""Run a template's inline tests and measure its parse rate on sample lines (SPEC 4.1, 4.5).

Expected values compare by meaning: numbers as numbers, timestamps as instants, anything
else as text. A template is usable only when every inline test passes.
"""

import reprlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.ingest.records import DecodedLine
from app.templates.runtime import TemplateNormalizer
from app.templates.tables import LookupTable
from app.templates.validator import Template

FIXED_NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


@dataclass(slots=True)
class TestOutcome:
    name: str
    passed: bool
    problems: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ParseRate:
    lines: int
    ok: int
    partial: int
    failed: int
    errors: dict[str, int]

    @property
    def rate(self) -> float:
        """Share of lines parsed fully or partly (the >= 95% starter-pack bar)."""
        return (self.ok + self.partial) / self.lines if self.lines else 0.0


def run_tests(
    template: Template, tables: Mapping[str, LookupTable] | None = None
) -> list[TestOutcome]:
    norm = TemplateNormalizer(template, "template_test", clock=lambda: FIXED_NOW, tables=tables)
    outcomes = []
    for t in template.tests:
        row = norm.normalize(DecodedLine(text=t.input, bytes_invalid=False, truncated=False))
        problems = []
        if "internal:" in (row["parse_errors"] or ""):
            problems.append(f"the template crashed: {row['parse_errors']}")
        if row["parse_status"] != t.expect.parse_status:
            problems.append(
                f"parse_status is {row['parse_status']}, expected {t.expect.parse_status}"
                + (f" ({row['parse_errors']})" if row["parse_errors"] else "")
            )
        if t.expect.class_uid is not None and row["class_uid"] != t.expect.class_uid:
            problems.append(f"class_uid is {row['class_uid']}, expected {t.expect.class_uid}")
        for column, want in t.expect.fields.items():
            if not _same(row.get(column), want):
                problems.append(f"{column} is {_short(row.get(column))}, expected {_short(want)}")
        outcomes.append(TestOutcome(t.name, not problems, problems))
    return outcomes


def parse_rate(
    template: Template, lines: list[str], tables: Mapping[str, LookupTable] | None = None
) -> ParseRate:
    norm = TemplateNormalizer(template, "template_test", clock=lambda: FIXED_NOW, tables=tables)
    counts = {"ok": 0, "partial": 0, "envelope_only": 0, "failed": 0}
    errors: dict[str, int] = {}
    for text in lines:
        row = norm.normalize(DecodedLine(text=text, bytes_invalid=False, truncated=False))
        counts[row["parse_status"]] += 1
        for code in (row["parse_errors"] or "").split(","):
            if code:
                errors[code] = errors.get(code, 0) + 1
    return ParseRate(
        lines=len(lines),
        ok=counts["ok"],
        partial=counts["partial"],
        failed=counts["failed"] + counts["envelope_only"],
        errors=errors,
    )


def _short(value: Any) -> str:
    """A bounded repr for messages: expected values come from user YAML."""
    text = reprlib.Repr(maxstring=120, maxother=120, maxlist=10, maxdict=10, maxlevel=3).repr(value)
    return text[:300]


def _same(actual: Any, expected: Any) -> bool:
    if actual is None or expected is None:
        return actual is expected
    if isinstance(actual, datetime):
        try:
            other = datetime.fromisoformat(str(expected).replace("Z", "+00:00"))
        except ValueError:
            return False
        if other.tzinfo is None:
            other = other.replace(tzinfo=UTC)
        return actual == other
    if isinstance(actual, bool) or isinstance(expected, bool):
        return str(actual).lower() == str(expected).lower()
    if isinstance(actual, int) and not isinstance(expected, str):
        return bool(actual == expected)
    return str(actual) == str(expected)
