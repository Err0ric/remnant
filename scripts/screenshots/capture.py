#!/usr/bin/env python3
"""README screenshots from the demo install (`make demo`), at 1600x1000.

    DEMO_DETACH=1 bash scripts/demo/run.sh      # or `make demo` in another terminal
    python3 scripts/screenshots/capture.py [--url http://127.0.0.1:8090] [--out docs/images]

Captures Dashboard, Ask (question, SQL, and an explanation with cited events), Search,
Microsoft 365 > Admin, AI usage, Agents > Sessions, Health, and the command palette in dark, and the
Dashboard in light. Needs Python Playwright with Chromium.

Ask and Explain need a model. This starts `stand_in_model.py`, a scripted stand-in that
is not an LLM, and adds it as a provider named "Scripted demo model (not an LLM)", so the
screenshot says what answered. Everything else on the pages is the demo's synthetic data.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SIZE = {"width": 1600, "height": 1000}
PROVIDER = "Scripted demo model (not an LLM)"
MODEL_PORT = 8091
sys.path.insert(0, str(HERE))
from stand_in_model import QUESTION  # noqa: E402


def call(url: str, method: str, path: str, body: object = None) -> object:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url + path, data=data, method=method)  # noqa: S310  # loopback demo URL
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as res:  # noqa: S310  # same
        raw = res.read()
    return json.loads(raw) if raw else None


def add_model(url: str) -> subprocess.Popen[bytes]:
    proc = subprocess.Popen([sys.executable, str(HERE / "stand_in_model.py"), "--port", str(MODEL_PORT)])  # fmt: skip
    time.sleep(1)
    have = call(url, "GET", "/api/providers")
    mine = [p for p in have if p.get("name") == PROVIDER]  # type: ignore[union-attr]
    if not mine:
        mine = [call(url, "POST", "/api/providers", {"name": PROVIDER, "base_url": f"http://127.0.0.1:{MODEL_PORT}/v1", "model": "scripted-demo"})]  # fmt: skip
    call(url, "PATCH", f"/api/providers/{mine[0]['provider_id']}", {"enabled": True})  # type: ignore[index]
    return proc


def settle(page: Page, ms: int = 2500) -> None:
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(ms)


def shot(page: Page, url: str, path: str, out: Path, name: str) -> None:
    page.goto(url + path)
    settle(page)
    page.screenshot(path=str(out / name))
    print(name)


def capture(url: str, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for theme in ("dark", "light"):
            ctx = browser.new_context(viewport=SIZE, color_scheme=theme, timezone_id="UTC")  # type: ignore[arg-type]
            ctx.add_init_script(f"localStorage.setItem('app.theme', '{theme}')")
            page = ctx.new_page()
            if theme == "light":
                shot(page, url, "/dashboard", out, "dashboard-light.png")
                ctx.close()
                continue
            shot(page, url, "/dashboard", out, "dashboard.png")
            shot(page, url, "/m365/admin", out, "m365-admin.png")
            shot(page, url, "/ai", out, "ai-usage.png")
            page.goto(url + "/agents/sessions")
            settle(page, 1500)
            page.get_by_role("button").filter(has_text="dave@example.com").first.click()
            settle(page, 1500)
            page.screenshot(path=str(out / "agents.png"))
            print("agents.png")
            shot(page, url, "/health", out, "health.png")

            page.goto(url + "/investigate/search")
            settle(page, 1500)
            page.get_by_role("combobox").first.select_option(label="Last 7 days")
            box = page.get_by_placeholder('Words, "phrases"', exact=False)
            box.fill('sshd "failed password" src_ip:203.0.113.*')
            box.press("Enter")
            settle(page)
            page.screenshot(path=str(out / "search.png"))
            print("search.png")

            page.goto(url + "/investigate/search")
            settle(page, 1500)
            page.get_by_role("combobox").first.select_option(label="Last 7 days")
            page.get_by_role("button", name="Ask in plain English").click()
            page.locator("#ask-question").fill(QUESTION)
            page.get_by_role("button", name="Ask", exact=True).click()
            page.get_by_label("Generated SQL").wait_for(timeout=60_000)
            page.get_by_role("button", name="Run", exact=True).click()
            settle(page, 1500)
            page.get_by_role("button", name="Explain", exact=True).first.click()
            page.get_by_label("Explain events").get_by_role(
                "button", name="Explain", exact=True
            ).click()
            page.get_by_label("Claims").wait_for(timeout=60_000)
            settle(page, 1000)
            page.get_by_label("Explain events").scroll_into_view_if_needed()
            page.screenshot(path=str(out / "ask.png"), full_page=False)
            print("ask.png")

            page.goto(url + "/dashboard")
            settle(page, 1500)
            page.keyboard.press("Control+k")
            page.keyboard.type("frank", delay=60)
            settle(page, 1500)
            page.screenshot(path=str(out / "command-palette.png"))
            print("command-palette.png")
            ctx.close()
        browser.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", default="http://127.0.0.1:8090")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "images")
    args = ap.parse_args()
    url = args.url.rstrip("/")
    try:
        call(url, "GET", "/api/auth/state")
    except (urllib.error.URLError, ConnectionError):
        sys.exit(f"no demo server at {url}: run `make demo` first")
    model = add_model(url)
    try:
        capture(url, args.out)
    finally:
        model.terminate()


if __name__ == "__main__":
    main()
