#!/usr/bin/env python3
"""No page scrolls sideways (F54): open every page and tab at a desktop width and check
that the page is no wider than the window and that no card or table scrolls sideways
inside it. Only elements marked `data-scroll-x` (the search results grid, whose columns are
the user's choice) may scroll.

    python3 scripts/check-layout.py --url http://127.0.0.1:8080 [--width 1280] [--shots DIR]

Pages and tabs come from frontend/src/lib/route.ts and nav.ts, so a new page is checked
without editing this file. Run against a server with data (scripts/demo_lab.py), since most
overflow comes from real values: long source names, paths, and many hours. Needs the
`playwright` Python package; `--channel chrome` uses an installed Chrome (CI runners have
one) instead of a downloaded browser.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src" / "lib"
SKIP = {"account", "setup", "home"}  # sign-in links, first-run setup, and a redirect


def pages() -> list[str]:
    """Every page path, then every tab (`/ai#agents`)."""
    route = (SRC / "route.ts").read_text()
    block = route[route.index("const PATHS") : route.index("};", route.index("const PATHS"))]
    paths = dict(re.findall(r'^\s+(\w+): "(/[^"]*)"', block, re.M))
    out = [p for page, p in paths.items() if page not in SKIP]
    page = None
    for line in (SRC / "nav.ts").read_text().splitlines():
        found = re.search(r'\bpage: "(\w+)"', line)
        if found:
            page = found.group(1)
        tab = re.search(r'\{ id: "(\w+)", label:', line)
        if tab and page in paths and "page:" not in line:
            out.append(f"{paths[page]}#{tab.group(1)}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--channel", default=None, help="browser channel, e.g. chrome")
    ap.add_argument("--shots", type=Path, default=None, help="save a screenshot per failure")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    failures: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=args.channel) if args.channel else p.chromium.launch()
        for theme in ("dark",):
            page = browser.new_page(
                viewport={"width": args.width, "height": 900}, color_scheme=theme
            )
            for path in pages():
                page.goto(args.url.rstrip("/") + path, wait_until="networkidle")
                page.wait_for_timeout(400)
                doc, view, widest, inner = page.evaluate(
                    """() => {
                      const el = document.documentElement;
                      let widest = "";
                      let right = el.clientWidth;
                      for (const n of document.querySelectorAll("body *")) {
                        const r = n.getBoundingClientRect();
                        if (r.right > right + 1 && r.width > 0) {
                          right = r.right;
                          widest = n.tagName.toLowerCase() + (n.getAttribute("aria-label")
                            ? `[aria-label="${n.getAttribute("aria-label")}"]`
                            : n.className && typeof n.className === "string"
                              ? "." + n.className.trim().split(/\\s+/).slice(0, 3).join(".")
                              : "");
                        }
                      }
                      const inner = [...document.querySelectorAll("body *")].filter((n) =>
                        n.scrollWidth > n.clientWidth + 1 && n.clientWidth > 0
                        && ["auto", "scroll"].includes(getComputedStyle(n).overflowX)
                        && !n.closest("[data-scroll-x]")
                      ).map((n) => (n.closest("[aria-label]")?.getAttribute("aria-label") ?? n.tagName.toLowerCase())
                        + ` ${n.scrollWidth}/${n.clientWidth}px`);
                      return [el.scrollWidth, el.clientWidth, widest, inner];
                    }"""
                )
                ok = doc <= view and not inner
                note = "" if doc <= view else f"; widest: {widest}"
                note += f"; scrolls inside: {', '.join(inner)}" if inner else ""
                print(f"{'ok  ' if ok else 'WIDE'} {path:<28} page {doc}px, window {view}px{note}")
                if not ok:
                    failures.append(path)
                    if args.shots:
                        args.shots.mkdir(parents=True, exist_ok=True)
                        name = path.strip("/").replace("/", "_").replace("#", "-") or "root"
                        page.screenshot(path=str(args.shots / f"{name}.png"), full_page=True)
            page.close()
        browser.close()
    if failures:
        print(f"\n{len(failures)} page(s) scroll sideways at {args.width}px: {', '.join(failures)}")
        return 1
    print(f"\nNo page scrolls sideways at {args.width}px.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
