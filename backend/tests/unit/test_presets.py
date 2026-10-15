"""Suspicious presets ship valid (ADR-0016 row 3)."""

from pathlib import Path

import pytest

from app.core.errors import SearchInvalidError
from app.search.presets import load_presets


def test_shipped_presets_load_and_compile() -> None:
    presets = load_presets()
    assert len(presets) >= 10
    assert all(chr(0x2014) not in p.name + p.description for p in presets)  # no em dashes


def test_a_broken_preset_fails_loudly(tmp_path: Path) -> None:
    bad = tmp_path / "p.yaml"
    bad.write_text("- {id: x1, name: X, text: 'user:(('}\n")
    with pytest.raises(SearchInvalidError):
        load_presets(bad)
    dup = tmp_path / "d.yaml"
    dup.write_text("- {id: x1, name: X, text: a}\n- {id: x1, name: Y, text: b}\n")
    with pytest.raises(ValueError, match="unique"):
        load_presets(dup)
