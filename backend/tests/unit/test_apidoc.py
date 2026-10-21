"""docs/api.md is generated from the server's OpenAPI spec and must stay current."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_api_reference_is_current() -> None:
    spec = importlib.util.spec_from_file_location("apidoc", ROOT / "scripts" / "apidoc.py")
    assert spec and spec.loader
    apidoc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(apidoc)
    current = (ROOT / "docs" / "api.md").read_text(encoding="utf-8")
    assert apidoc.build() == current, (
        "docs/api.md is out of date: cd backend && uv run python ../scripts/apidoc.py"
    )
