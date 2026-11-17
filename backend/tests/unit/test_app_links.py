"""Every link the server builds into the app (alert messages, the setup link) opens a page
of today, never an old address that only redirects (owner, 2026-11-16, D267).

The links are collected from the source of `app/`: an f-string `{self._link}/<path>`, the
setup link, and the relative paths (`"health#source=..."`) the detection-stop messages are
given. The app's routes and old addresses are read from `frontend/src/lib/route.ts`, as
`scripts/smoke.py` does, so a renamed page fails here until the server's link follows.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "backend" / "app"
ROUTE_TS = ROOT / "frontend" / "src" / "lib" / "route.ts"

# `{self._link}/alerts#item=...`, `{base.rstrip('/')}/setup#...`: the app path after the base.
BASED = re.compile(r"\{(?:self\._link|base\.rstrip\('/'\))\}/([a-z][\w/\-]*(?:#[\w\-]*=?)?)")
# A relative path given to the detection-stop messages: `"health#source=..."`.
RELATIVE = re.compile(
    r"[\"']((?:health|alerts|sources|audit|system|ai|agents)(?:/[\w\-]+)?#[\w\-]+=?)"
)


def _block(src: str, name: str) -> str:
    at = src.index(name)
    return src[at : src.index("\n};", at)]


def routes() -> set[str]:
    """Every page path and tab path of today."""
    src = ROUTE_TS.read_text(encoding="utf-8")
    paths = dict(re.findall(r'^\s*(\w+): "(/[^"]*)"', _block(src, "const PATHS"), re.M))
    out = set(paths.values())
    for page, tabs in re.findall(r"^\s*(\w+): \[([^\]]*)\]", _block(src, "const PAGE_TABS"), re.M):
        out |= {f"{paths[page]}/{t}" for t in re.findall(r'"([^"]+)"', tabs)[1:]}
    return out


def old_addresses() -> set[str]:
    """The keys of `OLD_ADDRESSES`, the helper-built ones included."""
    block = _block(ROUTE_TS.read_text(encoding="utf-8"), "const OLD_ADDRESSES")
    keys = set(re.findall(r'^\s*"(/[^"]+)": \{', block, re.M))
    for helper, base in (("healthTab", "/health"), ("m365Tab", "/m365")):
        for word in re.findall(rf'\.\.\.{helper}\("([\w-]+)"', block):
            keys |= {f"{base}/{word}", f"{base}#{word}"}
    return keys


def server_links() -> dict[str, set[str]]:
    """App links by source file (relative to `app/`), as `/path` or `/path#word` (a bare
    fragment word) or `/path#name=` (named state)."""
    out: dict[str, set[str]] = {}
    for py in APP.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        found = {"/" + m for m in BASED.findall(text) + RELATIVE.findall(text)}
        # `{self._link}/{path}` is the stop messages' own: their paths are found above.
        found.discard("/")
        if found:
            out[str(py.relative_to(APP))] = found
    return out


def test_the_route_table_and_old_addresses_are_read() -> None:
    assert {"/alerts", "/investigate/logs", "/audit/integrity", "/health"} <= routes()
    assert {"/investigate", "/settings", "/search", "/health#integrity", "/m365/apps"} <= (
        old_addresses()
    )


def test_each_known_link_points_at_its_page() -> None:
    links = server_links()
    assert links["ops/integrity.py"] == {"/audit/integrity"}  # Audit log > Integrity
    assert links["search/handoff.py"] == {"/investigate/logs"}  # Logs, not /search
    assert links["enrich/updater.py"] == {"/health#type="}  # Enrichment feeds on Health
    assert links["auth/setup.py"] == {"/setup#"}
    assert "/alerts#item=" in links["alerts/external.py"]
    assert "/health#source=" in links["ingest/watcher.py"]


def test_every_server_built_link_is_a_page_of_today_not_an_old_address() -> None:
    pages, old = routes(), old_addresses()
    links = server_links()
    assert len(links) >= 10  # the collector still finds them
    for where, found in links.items():
        for link in found:
            path, _, frag = link.partition("#")
            assert path in pages, f"{where}: {link} is not a page of today"
            assert path not in old, f"{where}: {link} is an old address"
            word = frag if frag and not frag.endswith("=") else ""
            assert not word or f"{path}#{word}" not in old, f"{where}: {link} is an old address"
