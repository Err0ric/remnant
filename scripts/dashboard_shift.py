#!/usr/bin/env python3
"""No layout shift on the Dashboard (fix list 2026-11-16 item 27): load it in headless
Chromium with every API answer held back for a different time (so the answers arrive out of
order, as on a large install), record the boxes of the KPI strip, each of its tiles, each
card and section header, where each card's first content row and each tile's value start,
on every frame, and fail when any of them moves, changes size, appears, or goes away after
the strip's first paint. The strip's tile count is checked the same way: it never grows or
shrinks.

    cd backend && uv run python ../scripts/dashboard_shift.py --url http://127.0.0.1:8104 \\
        --data ../data/tmp/<copy> [--width 1280 --width 1440]

`scripts/smoke.py` runs it as the Admin at 1280 and 1440 px, so the queue does. Needs
Python Playwright with Chromium.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import devauth  # noqa: E402  # sibling script, standard library only

WIDTHS = (1280, 1440)
# Each answer is held 200 to 1,500 ms, by a hash of its path and query.
HOLD_MS = (200, 1500)
# Answers the app needs before it draws any page: never held.
NOT_HELD = ("/api/auth/", "/api/branding", "/api/version")
LIMIT_S = 60

# Every frame: the strip, its tiles, and the header of every top-level card and section in
# the main region, as page coordinates; and whether anything in the main region is still loading.
TRACE_JS = r"""
(() => {
  const T = (window.__shift = { frames: [], busy: true, paint: null });
  const box = (el) => {
    const b = el.getBoundingClientRect();
    const y = b.y + window.scrollY;
    return [b.x, y, b.width, b.height].map(Math.round);
  };
  const read = () => {
    const main = document.querySelector('main');
    if (!main) return {};
    const out = {};
    const strip = main.querySelector('section[aria-label="Key numbers"]');
    if (strip) {
      out['strip'] = box(strip);
      strip.querySelectorAll('[data-kpi]').forEach((el, i) => { out['tile ' + i] = box(el); });
    }
    // Where each tile's value starts, in the strip and in the sections (not AI Watch, whose
    // card labels come with its answer): a label that wraps once loaded would move it.
    main.querySelectorAll('[data-kpi]').forEach((el) => {
      if (el.closest('[data-slot^="ai_watch"]')) return;
      const sec = el.closest('section[aria-label]');
      const where = sec ? sec.getAttribute('aria-label') : '';
      const value = el.children[1];
      if (value) out['value ' + where + ' / ' + el.getAttribute('data-kpi')] = [box(value)[1]];
    });
    const seen = {};
    main.querySelectorAll('[data-card-header], h2').forEach((el) => {
      const sec = el.closest('section');
      // A card inside a section (AI Watch's chart) is inside its box, which is checked.
      if (sec && sec.parentElement && sec.parentElement.closest('section')) return;
      // A title inside a card's header row moves with the row, which is checked.
      if (el.tagName === 'H2' && el.closest('[data-card-header]')) return;
      const name = (sec && sec.getAttribute('aria-label')) || el.textContent.trim().slice(0, 40);
      seen[name] = (seen[name] || 0) + 1;
      const label = name + (seen[name] > 1 ? ' ' + seen[name] : '');
      out['header ' + label] = box(el);
      // The first row of the card's body (a note, the KPI cards, an empty state): where its
      // content starts must not move either.
      const first = el.matches('[data-card-header]') && el.nextElementSibling?.firstElementChild;
      if (first) out['first row ' + label] = [box(first)[1]];
    });
    return out;
  };
  let last = '';
  const step = () => {
    const now = read();
    const text = JSON.stringify(now);
    if (text !== last) {
      T.frames.push({ at: Math.round(performance.now()), boxes: now });
      last = text;
    }
    T.busy = !!document.querySelector('main [aria-busy="true"]');
    requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
})();
"""


def hold_ms(url: str) -> int:
    low, high = HOLD_MS
    digest = int(hashlib.sha256(url.encode()).hexdigest()[:8], 16)
    return low + digest % (high - low)


def moves(frames: list[dict[str, Any]]) -> list[str]:
    """What changed after the strip first showed: one line per box that moved, changed
    size, came, or went, with the boxes as [x, y, width, height]."""
    start = next((i for i, f in enumerate(frames) if "strip" in f["boxes"]), None)
    if start is None:
        return ["the KPI strip never showed"]
    first = frames[start]["boxes"]
    found: dict[str, str] = {}
    for f in frames[start + 1 :]:
        now = f["boxes"]
        for key in first.keys() | now.keys():
            if key in found or first.get(key) == now.get(key):
                continue
            was, then = first.get(key), now.get(key)
            what = "came" if was is None else "went" if then is None else f"{was} -> {then}"
            found[key] = f"{key}: {what} at {f['at']} ms"
    return list(found.values())


def load(ctx: Any, base: str, path: str = "/dashboard") -> list[dict[str, Any]]:
    """The frames of one Dashboard load with the answers held back."""
    page = ctx.new_page()
    due: list[tuple[float, Any, Any]] = []

    def hold(route: Any) -> None:
        url = route.request.url
        if any(p in url for p in NOT_HELD):
            route.continue_()
            return
        answer = route.fetch()
        due.append((time.monotonic() + hold_ms(url.removeprefix(base)) / 1000, route, answer))

    page.route("**/api/**", hold)
    page.add_init_script(TRACE_JS)
    page.goto(base + path)
    deadline = time.monotonic() + LIMIT_S
    quiet_since: float | None = None
    while time.monotonic() < deadline:
        now = time.monotonic()
        for item in [d for d in due if d[0] <= now]:
            due.remove(item)
            item[1].fulfill(response=item[2])
        page.wait_for_timeout(20)
        idle = not due and not page.evaluate("window.__shift.busy")
        quiet_since = (quiet_since or now) if idle else None
        if quiet_since is not None and now - quiet_since > 1.5:
            break
    frames: list[dict[str, Any]] = page.evaluate("window.__shift.frames")
    page.close()
    return frames


def check(
    browser: Any, base: str, login: dict[str, str], widths: tuple[int, ...] = WIDTHS
) -> list[str]:
    """Problems, as "dashboard shift <width>px: <box>: <change>"; none when nothing moved."""
    problems: list[str] = []
    for width in widths:
        ctx = browser.new_context(viewport={"width": width, "height": 900}, timezone_id="UTC")
        try:
            if not ctx.request.post(base + "/api/auth/login", data=login).ok:
                problems.append(f"dashboard shift {width}px: login failed")
                continue
            # A first visit, then a returning one, whose boxes are the heights kept from
            # the first (`frontend/src/features/dashboard/slot.tsx`).
            for visit in ("first visit", "returning visit"):
                found = moves(load(ctx, base))
                problems += [f"dashboard shift {width}px, {visit}: {m}" for m in found]
        finally:
            ctx.close()
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--url", required=True, help="your own throwaway server")
    ap.add_argument("--data", type=Path, required=True, help="that server's data folder")
    ap.add_argument(
        "--width", type=int, action="append", help="viewport widths (default 1280, 1440)"
    )
    args = ap.parse_args()
    login = devauth.account(args.data)
    if login is None:
        print(f"no {devauth.ACCOUNT_FILE} in {args.data}", file=sys.stderr)
        return 2
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        problems = check(browser, args.url.rstrip("/"), login, tuple(args.width or WIDTHS))
        browser.close()
    for p in problems:
        print(f"FAIL {p}")
    print(json.dumps({"shift": "none" if not problems else len(problems)}))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
