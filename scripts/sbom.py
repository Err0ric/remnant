#!/usr/bin/env python3
"""Write a CycloneDX 1.5 SBOM for what ships: runtime Python packages, the web UI's
production npm packages, and the container base images.

Built from the lockfiles (backend/uv.lock, frontend/pnpm-lock.yaml) and the Dockerfile,
so it needs no network and gives the same output for the same commit. Development-only
packages (pytest, vitest, linters) are left out because they are not in the image.

    cd backend && uv run python ../scripts/sbom.py --out ../sbom.cdx.json
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

ROOT = Path(__file__).resolve().parent.parent
_PEERS = re.compile(r"\(.*\)$")


def pypi_purl(name: str, version: str) -> str:
    return f"pkg:pypi/{name.lower().replace('_', '-')}@{version}"


def npm_purl(name: str, version: str) -> str:
    if name.startswith("@"):
        scope, _, base = name[1:].partition("/")
        return f"pkg:npm/{quote('@' + scope, safe='')}/{base}@{version}"
    return f"pkg:npm/{name}@{version}"


def python_components(
    lock_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (root, components, dependencies) for the non-dev closure of the project."""
    lock = tomllib.loads(lock_path.read_text())
    by_name: dict[str, list[dict[str, Any]]] = {}
    for pkg in lock["package"]:
        by_name.setdefault(pkg["name"], []).append(pkg)
    root = next(p for p in lock["package"] if "editable" in p["source"] or "virtual" in p["source"])

    def resolve(dep: dict[str, Any]) -> list[dict[str, Any]]:
        candidates = by_name.get(dep["name"], [])
        if "version" in dep:
            candidates = [p for p in candidates if p["version"] == dep["version"]]
        return candidates

    seen: dict[str, dict[str, Any]] = {}
    edges: dict[str, set[str]] = {}
    stack = [root]
    while stack:
        pkg = stack.pop()
        ref = pypi_purl(pkg["name"], pkg["version"])
        if ref in seen:
            continue
        seen[ref] = pkg
        deps = list(pkg.get("dependencies", []))
        for dep in deps:
            # Extras pulled in by a parent ("uvicorn[standard]") are listed per extra.
            for extra in dep.get("extra", []):
                for target in resolve(dep):
                    deps.extend(target.get("optional-dependencies", {}).get(extra, []))
        children = {pypi_purl(t["name"], t["version"]) for d in deps for t in resolve(d)}
        edges[ref] = children
        stack.extend(t for d in deps for t in resolve(d))

    root_ref = pypi_purl(root["name"], root["version"])
    components = []
    for ref, pkg in sorted(seen.items()):
        if ref == root_ref:
            continue
        comp: dict[str, Any] = {
            "type": "library",
            "bom-ref": ref,
            "name": pkg["name"],
            "version": pkg["version"],
            "purl": ref,
            "scope": "required",
        }
        sdist = pkg.get("sdist", {})
        if isinstance(sdist, dict) and str(sdist.get("hash", "")).startswith("sha256:"):
            comp["hashes"] = [{"alg": "SHA-256", "content": sdist["hash"].split(":", 1)[1]}]
            comp["externalReferences"] = [{"type": "distribution", "url": sdist["url"]}]
        components.append(comp)
    dependencies = [{"ref": r, "dependsOn": sorted(c)} for r, c in sorted(edges.items())]
    return root, components, dependencies


def npm_components(lock_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Return (components, dependencies, direct refs) for the production closure."""
    lock = yaml.safe_load(lock_path.read_text())
    packages = lock.get("packages", {})
    snapshots = lock.get("snapshots", {})

    def key(name: str, version: str) -> str:
        return f"{name}@{version}"

    def ref_of(snapshot_key: str) -> tuple[str, str]:
        base = _PEERS.sub("", snapshot_key)
        name, _, version = base.rpartition("@")
        return name, version

    direct = [
        key(name, str(spec["version"]))
        for name, spec in lock["importers"]["."].get("dependencies", {}).items()
    ]
    seen: dict[str, tuple[str, str]] = {}
    edges: dict[str, set[str]] = {}
    stack = list(direct)
    while stack:
        snap = stack.pop()
        name, version = ref_of(snap)
        ref = npm_purl(name, version)
        if snap in seen:
            continue
        seen[snap] = (name, version)
        entry = snapshots.get(snap) or {}
        children = [
            key(n, str(v))
            for section in ("dependencies", "optionalDependencies")
            for n, v in (entry.get(section) or {}).items()
        ]
        edges.setdefault(ref, set()).update(npm_purl(*ref_of(c)) for c in children)
        stack.extend(children)

    components: dict[str, dict[str, Any]] = {}
    for name, version in seen.values():
        ref = npm_purl(name, version)
        comp: dict[str, Any] = {
            "type": "library",
            "bom-ref": ref,
            "name": name,
            "version": version,
            "purl": ref,
            "scope": "required",
        }
        integrity = (
            (packages.get(f"{name}@{version}") or {}).get("resolution", {}).get("integrity", "")
        )
        if integrity.startswith("sha512-"):
            digest = base64.b64decode(integrity[len("sha512-") :]).hex()
            comp["hashes"] = [{"alg": "SHA-512", "content": digest}]
        components[ref] = comp
    dependencies = [{"ref": r, "dependsOn": sorted(c)} for r, c in sorted(edges.items())]
    direct_refs = sorted({npm_purl(*ref_of(d)) for d in direct})
    return [components[r] for r in sorted(components)], dependencies, direct_refs


def base_images(dockerfile: Path) -> list[dict[str, Any]]:
    """Every FROM image: build stages get scope "excluded", the last (runtime) "required"."""
    images = []
    for line in dockerfile.read_text().splitlines():
        m = re.match(r"\s*FROM\s+(\S+)", line, re.IGNORECASE)
        if not m:
            continue
        image = m.group(1)
        name, _, digest = image.partition("@")
        repo, _, tag = name.rpartition(":") if ":" in name.split("/")[-1] else (name, "", "")
        comp: dict[str, Any] = {
            "type": "container",
            "bom-ref": f"image:{image}",
            "name": repo,
            "version": tag or "latest",
            "scope": "excluded",
        }
        if digest.startswith("sha256:"):
            comp["hashes"] = [{"alg": "SHA-256", "content": digest.split(":", 1)[1]}]
        images.append(comp)
    if images:
        images[-1]["scope"] = "required"
    return images


def build(root: Path = ROOT) -> dict[str, Any]:
    from app.core.branding import PRODUCT_NAME

    py_root, py_components, py_deps = python_components(root / "backend" / "uv.lock")
    js_components, js_deps, js_direct = npm_components(root / "frontend" / "pnpm-lock.yaml")
    images = base_images(root / "Dockerfile")
    app_ref = pypi_purl(py_root["name"], py_root["version"])
    for entry in py_deps:
        if entry["ref"] == app_ref:
            entry["dependsOn"] = sorted(
                {*entry["dependsOn"], *js_direct, *(i["bom-ref"] for i in images)}
            )
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "bom-ref": app_ref,
                "name": PRODUCT_NAME,
                "version": py_root["version"],
                "licenses": [{"license": {"id": "Apache-2.0"}}],
            },
            "tools": {"components": [{"type": "application", "name": "scripts/sbom.py"}]},
        },
        "components": [*py_components, *js_components, *images],
        "dependencies": [*py_deps, *js_deps],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--out", type=Path, help="Write here instead of standard output")
    args = p.parse_args(argv)
    text = json.dumps(build(), indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(text)
        bom = json.loads(text)
        kinds: dict[str, int] = {}
        for c in bom["components"]:
            kind = c["purl"].split("/")[0] if "purl" in c else "container"
            kinds[kind] = kinds.get(kind, 0) + 1
        print(
            f"{args.out}: " + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())),
            file=sys.stderr,
        )
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
