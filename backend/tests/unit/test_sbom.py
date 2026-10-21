"""scripts/sbom.py: runtime packages only, valid references, stable output."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sbom", ROOT / "scripts" / "sbom.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_packages_in_dev_tools_out() -> None:
    bom = _load().build(ROOT)
    names = {c["name"] for c in bom["components"]}
    assert {"duckdb", "fastapi", "pysigma", "react", "@tanstack/react-query"} <= names
    assert not names & {"pytest", "ruff", "mypy", "vitest", "typescript", "vite", "eslint"}


def test_every_reference_resolves_and_output_is_stable() -> None:
    sbom = _load()
    bom = sbom.build(ROOT)
    refs = {c["bom-ref"] for c in bom["components"]} | {bom["metadata"]["component"]["bom-ref"]}
    assert len(refs) == len(bom["components"]) + 1
    for entry in bom["dependencies"]:
        assert entry["ref"] in refs
        assert set(entry["dependsOn"]) <= refs
    assert json.dumps(bom, sort_keys=True) == json.dumps(sbom.build(ROOT), sort_keys=True)


def test_purls_and_images() -> None:
    sbom = _load()
    assert (
        sbom.npm_purl("@tanstack/react-query", "5.0.0") == "pkg:npm/%40tanstack/react-query@5.0.0"
    )
    assert sbom.pypi_purl("PyYAML", "6.0.2") == "pkg:pypi/pyyaml@6.0.2"
    images = sbom.base_images(ROOT / "Dockerfile")
    assert [i["scope"] for i in images][-1] == "required"
    assert all(i["scope"] == "excluded" for i in images[:-1])
