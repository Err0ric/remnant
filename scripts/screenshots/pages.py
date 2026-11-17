#!/usr/bin/env python3
"""Before and after screenshots of changed pages, for the owner's UI gate (development only).

A pull request that changes the UI shows each changed page before and after, in both themes
at 1440px wide. Run this against a throwaway server of your own on a copy of the demo's
synthetic data (never the shared demo, never real data), once on the branch before the
change and once after:

    python3 scripts/screenshots/pages.py --url http://127.0.0.1:8093 \\
        --data data/tmp/<copy>/ --out <folder> --label before \\
        --page "inventory=/ai/inventory|open:Status" \\
        --page "sources=/sources|click:Add source|open:Reads from"

A page is `<name>=<path>` with optional steps after `|`, run in order:
`click:<button name>` clicks a button; `check:<checkbox name>` ticks a checkbox;
`open:<control name>` opens that select (the themed select's list, or focuses a native
select, whose list a screenshot cannot show). Opening a
themed select fails the run when it scrolls the page or when the list does not share its
trigger's left edge (or right edge, when flipped) within 1 px and at least its width. A page with
an `open:` step is taken twice, closed and open. Each shot is full page at 1440x900 in UTC
(`--width 1280` for another width, with its own page names),
dark then light (`localStorage` key `app.theme`), named `<label>-<name>[-open]-<theme>.png`.
It waits for content and fonts as `capture.py` does. Needs Python Playwright with Chromium.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import devauth  # noqa: E402  # sibling script, standard library only
from capture import WAIT_MS, ShotError, settled  # noqa: E402

SIZE = {"width": 1440, "height": 900}


@dataclass
class Shot:
    name: str
    path: str
    clicks: list[tuple[str, str]] = field(default_factory=list)
    open: str | None = None


def parse(spec: str) -> Shot:
    """`name=/path|click:Button|open:Control` as a Shot."""
    head, *steps = spec.split("|")
    name, sep, path = head.partition("=")
    if not sep or not path.startswith("/"):
        raise SystemExit(f"--page wants name=/path[|step...], not {spec!r}")
    shot = Shot(name.strip(), path.strip())
    for step in steps:
        kind, _, arg = step.partition(":")
        if kind in ("click", "check"):
            shot.clicks.append((kind, arg))
        elif kind == "open":
            shot.open = arg
        else:
            raise SystemExit(
                f"unknown step {step!r}: use click:<button>, check:<checkbox>, or open:<control>"
            )
    return shot


def open_control(page: Page, name: str) -> None:
    """Opens the select named `name`: the themed one shows its list, a native one is focused."""
    control = page.get_by_role("combobox", name=name, exact=True).first
    control.scroll_into_view_if_needed(timeout=WAIT_MS)
    if control.evaluate("el => el.tagName") == "SELECT":
        control.focus()
        return
    before = page.evaluate("window.scrollY")
    control.click()
    page.get_by_role("listbox").first.wait_for(timeout=WAIT_MS)
    page.wait_for_timeout(200)
    after = page.evaluate("window.scrollY")
    if after != before:
        raise ShotError(f"opening {name!r} scrolled the page from {before} to {after}")
    edges = control.evaluate(
        """el => {
          const t = el.getBoundingClientRect();
          const list = document.getElementById(el.getAttribute("aria-controls"));
          const l = list.getBoundingClientRect();
          return [t.left, t.right, t.width, l.left, l.right, l.width];
        }"""
    )
    t_left, t_right, t_width, l_left, l_right, l_width = edges
    aligned = abs(l_left - t_left) <= 1 or abs(l_right - t_right) <= 1
    if not aligned or l_width + 1 < t_width:
        raise ShotError(
            f"the list of {name!r} is not on its trigger: trigger {edges[:3]}, list {edges[3:]}"
        )
    print(
        f"  {name}: scrollY {before} -> {after}; "
        f"trigger x {t_left:.0f}-{t_right:.0f}, list x {l_left:.0f}-{l_right:.0f}"
    )


def take(page: Page, url: str, shot: Shot, out: Path, label: str, theme: str) -> list[str]:
    page.goto(url + shot.path)
    settled(page, shot.name)
    for kind, name in shot.clicks:
        role = "checkbox" if kind == "check" else "button"
        page.get_by_role(role, name=name, exact=True).first.click()
        settled(page, shot.name)
    files = [f"{label}-{shot.name}-{theme}.png"]
    print(f"  {shot.path[:60]} ended at {page.url.removeprefix(url)[:80]}")  # redirects show
    page.screenshot(path=str(out / files[0]), full_page=True)
    if shot.open:
        open_control(page, shot.open)
        files.append(f"{label}-{shot.name}-open-{theme}.png")
        page.screenshot(path=str(out / files[1]), full_page=True)
    return files


def run(
    url: str, data: Path, out: Path, label: str, shots: list[Shot], width: int = SIZE["width"]
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    login = devauth.account(data)
    if login is None:
        sys.exit(f"no {devauth.ACCOUNT_FILE} in {data}: point --data at the server's data folder")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for theme in ("dark", "light"):
            ctx = browser.new_context(
                viewport={**SIZE, "width": width}, color_scheme=theme, timezone_id="UTC"
            )  # type: ignore[arg-type]
            ctx.add_init_script(f"localStorage.setItem('app.theme', '{theme}')")
            signed = ctx.request.post(url + "/api/auth/login", data=login)
            if not signed.ok:
                sys.exit(f"could not sign in at {url} ({signed.status})")
            for shot in shots:
                page = ctx.new_page()
                try:
                    for name in take(page, url, shot, out, label, theme):
                        print(name)
                except PlaywrightError as e:
                    page.screenshot(path=str(out / f"failed-{label}-{shot.name}-{theme}.png"))
                    raise ShotError(f"{shot.name} ({theme}): {e.message.splitlines()[0]}") from e
                finally:
                    page.close()
            ctx.close()
        browser.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--url", required=True, help="your own server, never the shared demo")
    ap.add_argument("--data", type=Path, required=True, help="that server's data folder")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--label", choices=("before", "after"), required=True)
    ap.add_argument("--page", action="append", required=True, help="name=/path[|step...]")
    ap.add_argument("--width", type=int, default=SIZE["width"], help="viewport width in px")
    args = ap.parse_args()
    try:
        run(
            args.url.rstrip("/"),
            args.data,
            args.out,
            args.label,
            [parse(s) for s in args.page],
            args.width,
        )
    except ShotError as e:
        sys.exit(f"screenshot failed: {e}")


if __name__ == "__main__":
    main()
