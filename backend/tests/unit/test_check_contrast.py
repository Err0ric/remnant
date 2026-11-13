"""scripts/check-contrast.py: the token pairs meet WCAG AA and match DESIGN.md section 11."""

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_contrast", ROOT / "scripts/check-contrast.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_shipped_tokens_pass_and_match_the_design_document() -> None:
    script = _script()
    css = script.TOKENS.read_text(encoding="utf-8")
    lines, failures = script.check(css)
    assert len(lines) >= 160
    assert failures == []
    assert script.drift(css, script.DESIGN.read_text(encoding="utf-8")) == []


def test_a_faint_input_edge_fails_in_the_theme_that_has_it() -> None:
    script = _script()
    css = script.TOKENS.read_text(encoding="utf-8").replace("#808896", "#868e9b")
    _, failures = script.check(css)
    assert failures
    assert all(f.startswith("light border-control on ") for f in failures)
    assert any("on inset" in f for f in failures)


def test_a_translucent_token_is_composited_before_it_is_measured() -> None:
    script = _script()
    white, black = (255.0, 255.0, 255.0, 1.0), (0.0, 0.0, 0.0, 1.0)
    assert round(script.ratio(white, black), 1) == 21.0
    half = (255.0, 255.0, 255.0, 0.5)
    assert script.ratio(half, black) < 6


def test_a_value_that_differs_from_the_design_document_is_reported() -> None:
    script = _script()
    css = script.TOKENS.read_text(encoding="utf-8").replace("--ok: #58c29a", "--ok: #58c29b")
    assert script.drift(css, script.DESIGN.read_text(encoding="utf-8")) == [
        "dark --ok: tokens.css has #58c29b, DESIGN.md has #58C29A"
    ]


def test_a_value_the_script_cannot_read_never_counts_as_a_match() -> None:
    script = _script()
    css = script.TOKENS.read_text(encoding="utf-8").replace("--ok: #58c29a", "--ok: #5c9")
    assert len(script.drift(css, script.DESIGN.read_text(encoding="utf-8"))) == 1
