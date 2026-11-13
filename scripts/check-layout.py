#!/usr/bin/env python3
"""No page scrolls sideways (F54): open every page and tab at a desktop width, in the dark
and the light theme, and check that the page is no wider than the window and that no card
or table scrolls sideways inside it. Only elements marked `data-scroll-x` (the search
results grid, whose columns are the user's choice) may scroll.

    python3 scripts/check-layout.py --url http://127.0.0.1:8080 --data DIR [--width 1280]

Pages and tabs come from frontend/src/lib/route.ts and nav.ts, so a new page is checked
without editing this file. Run against a server with data (scripts/demo_lab.py), since most
overflow comes from real values: long source names, paths, and many hours. Needs the
`playwright` Python package; `--channel chrome` uses an installed Chrome (CI runners have
one) instead of a downloaded browser.
"""

from __future__ import annotations

import argparse
import contextlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import devauth  # noqa: E402  # sibling script, standard library only

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
    ap.add_argument(
        "--data",
        type=Path,
        required=True,
        help="the server's data folder, for the account demo_lab.py made (dev-account.json)",
    )
    ap.add_argument("--shots", type=Path, default=None, help="save a screenshot per failure")
    args = ap.parse_args()

    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright

    failures: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=args.channel) if args.channel else p.chromium.launch()
        for theme in ("dark", "light"):
            ctx = browser.new_context(
                viewport={"width": args.width, "height": 900}, color_scheme=theme
            )
            # Signed in, or every path would show the sign-in page and measure nothing.
            url = args.url.rstrip("/")
            signed = ctx.request.post(url + "/api/auth/login", data=devauth.account(args.data))
            who = ctx.request.get(url + "/api/auth/state").json().get("user")
            if not signed.ok or not who:
                print(f"could not sign in to {url} with {args.data / devauth.ACCOUNT_FILE}")
                return 2
            page = ctx.new_page()
            for path in pages():
                page.goto(args.url.rstrip("/") + path, wait_until="networkidle")
                page.wait_for_timeout(400)
                # Measure in the app's own fonts: a fallback font has other widths, so a
                # page could pass or fail here and do the opposite for a user.
                missing = page.evaluate(
                    """async () => {
                      await document.fonts.ready;
                      const want = ['14px Geist', '500 14px Geist', '600 14px Geist',
                        '13px "Geist Mono"'];
                      // A font file that fails to load rejects; the check below reports it.
                      await Promise.allSettled(want.map((f) => document.fonts.load(f)));
                      return want.filter((f) => !document.fonts.check(f));
                    }"""
                )
                if missing:
                    print(f"FONT {theme:<5} {path:<28} not loaded: {', '.join(missing)}")
                    failures.append(f"{path} ({theme}, fonts)")
                    continue
                # One h1 per page: the page header's title (DESIGN.md 6.0). The first page
                # of a run can still be loading its code when the network goes quiet (seen
                # on CI: 0 h1 on the first dark page), so wait for a title before counting.
                with contextlib.suppress(PlaywrightTimeout):
                    page.locator("h1").first.wait_for(state="attached", timeout=5000)
                headings = page.locator("h1").count()
                if headings != 1:
                    print(f"H1   {theme:<5} {path:<28} {headings} h1 elements, expected 1")
                    failures.append(f"{path} ({theme}, {headings} h1)")
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
                      // What makes a scroller wide: its table's column widths and the widest
                      // text that may not wrap.
                      const wide = (n) => {
                        const cols = [...n.querySelectorAll("thead th")]
                          .map((h) => Math.round(h.getBoundingClientRect().width));
                        const fixed = [...n.querySelectorAll("*")]
                          .filter((e) => getComputedStyle(e).whiteSpace === "nowrap"
                            && e.children.length === 0 && e.textContent.trim())
                          .sort((x, y) => y.getBoundingClientRect().width
                            - x.getBoundingClientRect().width)[0];
                        return (cols.length ? ` columns ${cols.join("/")}` : "") + (fixed
                          ? ` widest unwrapped text ${Math.round(fixed.offsetWidth)}px`
                            + ` "${fixed.textContent.trim().slice(0, 40)}"`
                          : "");
                      };
                      const inner = [...document.querySelectorAll("body *")].filter((n) =>
                        n.scrollWidth > n.clientWidth + 1 && n.clientWidth > 0
                        && ["auto", "scroll"].includes(getComputedStyle(n).overflowX)
                        && !n.closest("[data-scroll-x]")
                      ).map((n) => (n.closest("[aria-label]")?.getAttribute("aria-label") ?? n.tagName.toLowerCase())
                        + ` ${n.scrollWidth}/${n.clientWidth}px` + wide(n));
                      return [el.scrollWidth, el.clientWidth, widest, inner];
                    }"""
                )
                ok = doc <= view and not inner
                note = "" if doc <= view else f"; widest: {widest}"
                note += f"; scrolls inside: {', '.join(inner)}" if inner else ""
                mark = "ok  " if ok else "WIDE"
                print(f"{mark} {theme:<5} {path:<28} page {doc}px, window {view}px{note}")
                if not ok:
                    failures.append(f"{path} ({theme})")
                    if args.shots:
                        args.shots.mkdir(parents=True, exist_ok=True)
                        name = path.strip("/").replace("/", "_").replace("#", "-") or "root"
                        shot = args.shots / f"{name}-{theme}.png"
                        page.screenshot(path=str(shot), full_page=True)
            ctx.close()
        browser.close()
    if failures:
        print(f"\n{len(failures)} page(s) fail at {args.width}px: {', '.join(failures)}")
        return 1
    print(f"\nNo page scrolls sideways at {args.width}px in either theme.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
