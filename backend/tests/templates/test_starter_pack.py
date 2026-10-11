"""Every starter template against its fixtures (CLAUDE.md section 6, Templates row).

For each template in templates/starter/: the inline tests pass, sample.log (50+ lines)
parses at 95% or better, the first 10 lines match expected.jsonl, and pathological.log
never raises and never alters `raw`.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.ingest.records import DecodedLine
from app.templates.loader import load_dir
from app.templates.registry import STARTER_DIR
from app.templates.runtime import TemplateNormalizer
from app.templates.tables import load_tables
from app.templates.tester import _same, parse_rate
from app.templates.validator import Template

pytestmark = pytest.mark.templates
FIXTURES = Path(__file__).parent.parent / "fixtures" / "logs"
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
TABLES, TABLE_PROBLEMS = load_tables(STARTER_DIR / "maps")
TEMPLATES, PROBLEMS = load_dir(STARTER_DIR, TABLES)


def test_every_starter_template_loads() -> None:
    assert TABLE_PROBLEMS == []
    assert PROBLEMS == []
    assert TEMPLATES, "no starter templates found"


@pytest.fixture(params=sorted(TEMPLATES), ids=str)
def template(request: pytest.FixtureRequest) -> Template:
    return TEMPLATES[request.param]


def _lines(path: Path) -> list[str]:
    return path.read_text("utf-8").splitlines()


def _normalizer(t: Template) -> TemplateNormalizer:
    return TemplateNormalizer(t, "fixture", clock=lambda: NOW, tables=TABLES)


def test_fixture_folder_is_complete(template: Template) -> None:
    folder = FIXTURES / template.id
    for name in ("sample.log", "expected.jsonl", "pathological.log", "README.md"):
        assert (folder / name).is_file(), f"{template.id}: missing {name}"
    assert len(_lines(folder / "sample.log")) >= 50


def test_sample_parse_rate_at_least_95_percent(template: Template) -> None:
    rate = parse_rate(template, _lines(FIXTURES / template.id / "sample.log"), TABLES)
    assert rate.rate >= 0.95, (rate.rate, rate.errors)


def test_first_ten_lines_match_expected(template: Template) -> None:
    norm = _normalizer(template)
    lines = _lines(FIXTURES / template.id / "sample.log")[:10]
    wanted = [json.loads(x) for x in _lines(FIXTURES / template.id / "expected.jsonl")]
    assert len(wanted) == 10
    for i, (text, expect) in enumerate(zip(lines, wanted, strict=True)):
        row = norm.normalize(DecodedLine(text=text, bytes_invalid=False, truncated=False))
        for column, value in expect.items():
            assert _same(row[column], value), f"line {i + 1} {column}: {row[column]!r} != {value!r}"


def test_pathological_lines_never_raise(template: Template) -> None:
    norm = _normalizer(template)
    for text in _lines(FIXTURES / template.id / "pathological.log"):
        row = norm.normalize(DecodedLine(text=text, bytes_invalid=False, truncated=False))
        assert row["raw"] == text
        assert "internal:" not in (row["parse_errors"] or "")
