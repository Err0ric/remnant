#!/usr/bin/env python3
"""No page scrolls sideways (F54): open every page and tab at a desktop width, in the dark
and the light theme, and check that the page is no wider than the window and that no card
or table scrolls sideways inside it. Only elements marked `data-scroll-x` (the search
results grid, whose columns are the user's choice) may scroll.

Every page also keeps the page pattern's limits (ADR-0052, DESIGN.md 6.0): one `h1`, at
most 10 rail entries (pages, not the current page's tab rows, D268; the Recent and Pinned
regions apart hold at most 5 links each, D258, D259), at most 5 tabs, and at most one filled button. Every card header
drawn by the shared `Card` (`data-card-header`, D254) on a page has the same height and no
fill of its own, and the pages on that anatomy have no card with a header drawn by hand.

    python3 scripts/check-layout.py --url http://127.0.0.1:8080 --data DIR [--width 1280]

Pages and tabs come from frontend/src/lib/route.ts, so a new page is checked without
editing this file. Run against a server with data (scripts/demo_lab.py), since most
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


# Record pages (an entity is named in the fragment): a person, an address, and a host.
RECORDS = ("user=alice", "ip=203.0.113.9", "host=ws-0042")
MAX_RAIL, MAX_TABS, MAX_FILLED = 10, 5, 1
MAX_RECENT = 5  # the rail's Recent region, apart from its pages (D258)
MAX_PINNED = 5  # the rail's Pinned region, apart from its pages (D259)

# What the page shows of the pattern: rail entries, the longest tab strip, and the labels
# of the filled buttons (a button or link in the page body drawn in the accent color).
COUNT_JS = """() => {
  const probe = document.createElement("span");
  probe.style.background = "var(--accent)";
  document.body.append(probe);
  const fill = getComputedStyle(probe).backgroundColor;
  probe.remove();
  const seen = (n) => {
    const r = n.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(n).visibility !== "hidden";
  };
  return {
    // Entries, not the current page's tab rows under its entry (D268).
    rail: document.querySelectorAll('nav[aria-label="Primary"] [data-rail-entry]').length,
    recent: document.querySelectorAll('nav[aria-label="Recent"] a').length,
    pinned: document.querySelectorAll('nav[aria-label="Pinned"] a').length,
    // The page header's strip, or a strip a page draws itself (`role="tablist"`).
    tabs: Math.max(0,
      ...[...document.querySelectorAll('nav[aria-label$=" tabs"]')]
        .map((n) => n.querySelectorAll("a").length),
      ...[...document.querySelectorAll('[role="tablist"]')]
        .map((n) => n.querySelectorAll('[role="tab"]').length)),
    filled: [...document.querySelectorAll("main button, main a")]
      .filter((n) => seen(n) && getComputedStyle(n).backgroundColor === fill)
      .map((n) => n.textContent.trim().slice(0, 24)),
  };
}"""


# Every pager button: drawn, inside the window, and its text not the color behind it.
PAGER_JS = """() => {
  const out = [];
  const behind = (n) => {
    for (; n; n = n.parentElement) {
      const c = getComputedStyle(n).backgroundColor;
      if (c && c !== "rgba(0, 0, 0, 0)" && c !== "transparent") return c;
    }
    return "";
  };
  for (const b of document.querySelectorAll("[data-pager] button")) {
    const r = b.getBoundingClientRect();
    const name = b.textContent.trim();
    if (r.width < 24 || r.height < 24) out.push(`pager button ${name} is ${r.width}x${r.height}px`);
    else if (r.left < 0 || r.right > document.documentElement.clientWidth)
      out.push(`pager button ${name} is off screen sideways`);
    else if (getComputedStyle(b).color === behind(b))
      out.push(`pager button ${name} has the color of what is behind it`);
  }
  return out;
}"""


# Every drawn card header: its card's name, its height, and its fill against the card's.
CARDS_JS = """() => [...document.querySelectorAll("[data-card-header]")]
  .filter((n) => n.getBoundingClientRect().height > 0)
  .map((n) => {
    const card = n.closest("[data-card]") ?? n.parentElement;
    return {
      name: card?.getAttribute("aria-label") ?? "",
      height: Math.round(n.getBoundingClientRect().height * 10) / 10,
      fill: getComputedStyle(n).backgroundColor,
      card: card ? getComputedStyle(card).backgroundColor : "",
    };
  })"""

# A card drawn by hand: a bordered, rounded box in `main` that is not a `Card`, whose first
# row has a bottom border and a heading. Its heading's text, for the message.
HAND_JS = """() => {
  const out = [];
  for (const n of document.querySelectorAll("main *")) {
    const cs = getComputedStyle(n);
    const r = n.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const bordered = ["Top", "Right", "Bottom", "Left"].every((s) => parseFloat(cs[`border${s}Width`]) >= 1)
      && parseFloat(cs.borderTopLeftRadius) > 0;
    if (!bordered || n.matches("[data-card]")) continue;
    const first = n.firstElementChild;
    if (!first || !first.matches("div, header, h2, h3, h4")) continue;
    if (first.matches("[data-card-header]")) continue;
    if (parseFloat(getComputedStyle(first).borderBottomWidth) < 1) continue;
    const heading = first.matches("h2, h3, h4") ? first : first.querySelector(":scope > h2, :scope > h3, :scope > h4");
    if (!heading) continue;
    out.push(heading.textContent.trim().slice(0, 40));
  }
  return out;
}"""

# The pages already on the one card anatomy (D254); the others move to it page by page.
CARD_PAGES = ("/dashboard", "/ai", "/agents", "/investigate/people")

CLEAR = {"rgba(0, 0, 0, 0)", "transparent", ""}


def card_headers(headers: list[dict[str, object]]) -> list[str]:
    """What a page breaks of the card anatomy (D254), in words: card headers of more than
    one height, or a header with a fill other than its card's."""
    out = []
    heights = sorted({float(str(h["height"])) for h in headers})
    if heights and heights[-1] - heights[0] > 0.5:
        by = ", ".join(f"{h['name']} {h['height']}px" for h in headers)
        out.append(f"card headers of {len(heights)} heights ({by})")
    for h in headers:
        if h["fill"] not in CLEAR and h["fill"] != h["card"]:
            out.append(f"card header of {h['name']} has a fill ({h['fill']})")
    return out


def hand_built(path: str, titles: list[str]) -> list[str]:
    """Cards with a header drawn by hand on a page that is on the card anatomy (D254)."""
    base = path.split("#")[0]
    if not any(base == p or base.startswith(p + "/") for p in CARD_PAGES):
        return []
    return [f"card {t!r} has a header drawn by hand, not by Card" for t in titles]


def pages() -> list[str]:
    """Every page path, then every tab (`/alerts/rules`, `/ai/people`), then the Record
    pages. A page's first tab is the page's own path."""
    route = (SRC / "route.ts").read_text()
    block = route[route.index("const PATHS") : route.index("};", route.index("const PATHS"))]
    paths = dict(re.findall(r'^\s+(\w+): "(/[^"]*)"', block, re.M))
    out = [p for page, p in paths.items() if page not in SKIP]
    at = route.index("export const PAGE_TABS")
    for page, tabs in re.findall(
        r"^\s+(\w+): \[([^\]]*)\]", route[at : route.index("};", at)], re.M
    ):
        out += [f"{paths[page]}/{tab}" for tab in re.findall(r'"([\w-]+)"', tabs)[1:]]
    return out + [f"{paths['investigate']}#{entity}" for entity in RECORDS]


def tabbed() -> set[str]:
    """The paths of pages that have tabs: each must show a tab strip."""
    bases = _tab_bases()
    return bases | {p for p in pages() if any(p.startswith(b + "/") for b in bases)}


def _tab_bases() -> set[str]:
    route = (SRC / "route.ts").read_text()
    block = route[route.index("const PATHS") : route.index("};", route.index("const PATHS"))]
    paths = dict(re.findall(r'^\s+(\w+): "(/[^"]*)"', block, re.M))
    at = route.index("export const PAGE_TABS")
    return {
        paths[page]
        for page in re.findall(r"^\s+(\w+): \[", route[at : route.index("};", at)], re.M)
    }


def limits(counts: dict[str, object], has_tabs: bool = False) -> list[str]:
    """What a page breaks of the pattern's limits, in words; empty when it keeps them.
    A count of nothing where something must be is a failure too (a renamed label would
    otherwise read 0 and pass): every page has a rail, and a page with tabs (`has_tabs`)
    shows its strip."""
    out = []
    rail, tabs, filled = counts["rail"], counts["tabs"], counts["filled"]
    assert isinstance(rail, int) and isinstance(tabs, int) and isinstance(filled, list)
    if rail < 1:
        out.append("no rail entries found")
    if has_tabs and tabs < 2:
        out.append("no tab strip found on a page that has tabs")
    if rail > MAX_RAIL:
        out.append(f"{rail} rail entries, at most {MAX_RAIL}")
    recent = counts.get("recent", 0)  # Recent is drawn only once something was opened
    assert isinstance(recent, int)
    if recent > MAX_RECENT:
        out.append(f"{recent} Recent links, at most {MAX_RECENT}")
    pinned = counts.get("pinned", 0)  # Pinned is drawn only once something is pinned
    assert isinstance(pinned, int)
    if pinned > MAX_PINNED:
        out.append(f"{pinned} Pinned links, at most {MAX_PINNED}")
    if tabs > MAX_TABS:
        out.append(f"{tabs} tabs, at most {MAX_TABS}")
    if len(filled) > MAX_FILLED:
        out.append(f"{len(filled)} filled buttons ({', '.join(filled)}), at most {MAX_FILLED}")
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
            with_tabs = tabbed()
            for path in pages():
                if "#" in path:
                    # Only the fragment differs from the page before: load it as a new
                    # document, or the count would be of a page still changing.
                    page.goto("about:blank")
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
                for broken in limits(page.evaluate(COUNT_JS), path in with_tabs):
                    print(f"PAGE {theme:<5} {path:<28} {broken}")
                    failures.append(f"{path} ({theme}: {broken})")
                for broken in card_headers(page.evaluate(CARDS_JS)) + hand_built(
                    path, page.evaluate(HAND_JS)
                ):
                    print(f"CARD {theme:<5} {path:<28} {broken}")
                    failures.append(f"{path} ({theme}: {broken})")
                # A results pager is drawn and readable in this theme (owner, 2026-11-13):
                # on screen, with text that stands out from what is behind it.
                for broken in page.evaluate(PAGER_JS):
                    print(f"PAGE {theme:<5} {path:<28} {broken}")
                    failures.append(f"{path} ({theme}: {broken})")
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
    print(f"\nNo page scrolls sideways at {args.width}px in either theme, and every page keeps")
    print("the pattern's limits (one h1, 10 rail entries, 5 tabs, one filled button, one")
    print("card header height and no header fill).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
