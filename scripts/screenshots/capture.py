#!/usr/bin/env python3
"""README screenshots from the demo install (`make demo`), at 1600x1000, in both themes.

    DEMO_DETACH=1 bash scripts/demo/run.sh      # or `make demo` in another terminal
    python3 scripts/screenshots/capture.py [--url http://127.0.0.1:8090] [--out docs/images]

Captures Dashboard, Logs (a Simple search with one row open), Ask AI (question, SQL, rows,
and a summary citing events), the Microsoft 365 admin view of Logs, AI usage, Agents >
Sessions with the busiest session open, Health, and the command palette. Each is taken in
dark as `<name>.png` and in light as `<name>-light.png`. Needs Python Playwright with
Chromium. A shot that cannot find what it waits for, or shows a loading or error state,
stops the run with the shot's name.

Ask needs a model. This starts `stand_in_model.py`, a scripted stand-in that is not an
LLM, and adds it as a provider named "Scripted demo model (not an LLM)", so the
screenshot says what answered. Everything else on the pages is the demo's synthetic data.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SIZE = {"width": 1600, "height": 1000}
PROVIDER = "Scripted demo model (not an LLM)"
MODEL_PORT = 8091
WAIT_MS = 30_000
SEARCH = 'sshd "failed password" src_ip:203.0.113.*'
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import devauth  # noqa: E402  # sibling script, standard library only
from stand_in_model import QUESTION  # noqa: E402

# The demo's administrator (made by scripts/demo/load.py through the setup link).
DATA = ROOT / "data" / "demo" / "state"
SESSION: dict[str, str] = {}

# Loading and error states no shot may show (Skeleton.tsx, InlineError.tsx, ErrorBoundary).
BUSY = "[aria-busy='true'], [data-skeleton]"
FAILED = ("did not load", "Could not load", "Something went wrong")


class ShotError(RuntimeError):
    pass


def call(url: str, method: str, path: str, body: object = None) -> object:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url + path, data=data, method=method)  # noqa: S310  # loopback demo URL
    req.add_header("Content-Type", "application/json")
    for name, value in SESSION.items():
        req.add_header(name, value)
    with urllib.request.urlopen(req, timeout=60) as res:  # noqa: S310  # same
        raw = res.read()
    return json.loads(raw) if raw else None


def add_model(url: str) -> subprocess.Popen[bytes]:
    proc = subprocess.Popen([sys.executable, str(HERE / "stand_in_model.py"), "--port", str(MODEL_PORT)])  # fmt: skip
    for _ in range(50):
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{MODEL_PORT}/v1/models", timeout=1
            )  # loopback stand-in
            break
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.1)
    have = call(url, "GET", "/api/providers")
    mine = [p for p in have if p.get("name") == PROVIDER]  # type: ignore[union-attr]
    if not mine:
        mine = [call(url, "POST", "/api/providers", {"name": PROVIDER, "base_url": f"http://127.0.0.1:{MODEL_PORT}/v1", "model": "scripted-demo"})]  # fmt: skip
    call(url, "PATCH", f"/api/providers/{mine[0]['provider_id']}", {"enabled": True})  # type: ignore[index]
    return proc


def busiest_session(url: str) -> str:
    """The Claude Code session of the last 7 days with the most steps."""
    rows = call(url, "GET", "/api/ai/sessions")
    best, most = "", -1
    for row in rows:  # type: ignore[union-attr]
        sid = str(row["session_id"])
        steps = len(call(url, "GET", f"/api/ai/sessions/{sid}")["steps"])  # type: ignore[index]
        if steps > most:
            best, most = sid, steps
    if not best:
        raise ShotError("agents: the demo has no Claude Code sessions in the last 7 days")
    return best


def settled(page: Page, name: str) -> None:
    """Waits until the page has drawn: no request in flight, no skeleton, fonts loaded;
    fails with the shot's name on an error state."""
    page.wait_for_load_state("networkidle")
    page.locator("main h1").first.wait_for(timeout=WAIT_MS)
    page.wait_for_function(f"() => !document.querySelector({json.dumps(BUSY)})", timeout=WAIT_MS)
    page.evaluate("document.fonts.ready")
    for text in FAILED:
        shown = page.get_by_text(text, exact=False)
        if shown.count() and shown.first.is_visible():
            raise ShotError(f"{name}: the page shows an error: {shown.first.inner_text()!r}")
    page.wait_for_timeout(300)  # one more frame for layout after the last data arrived


def dashboard(page: Page, url: str) -> None:
    page.goto(url + "/dashboard")
    page.get_by_role("heading", name="Dashboard", exact=True).wait_for(timeout=WAIT_MS)


def search(page: Page, url: str) -> None:
    page.goto(url + "/investigate/logs")
    page.get_by_role("group", name="Time").get_by_role("button", name="7 days").click()
    box = page.get_by_role("searchbox", name="Search text")
    box.fill(SEARCH)
    page.get_by_role("button", name="Run", exact=True).click()
    page.get_by_text("203.0.113.", exact=False).first.wait_for(timeout=WAIT_MS)
    page.wait_for_load_state("networkidle")
    page.locator("[role=treegrid] [aria-expanded=false]").first.click()
    page.locator("[role=treegrid] [aria-expanded=true]").first.wait_for(timeout=WAIT_MS)


def ask(page: Page, url: str) -> None:
    page.goto(url + "/ask-ai")
    page.get_by_role("combobox", name="Time").select_option(label="7 days")
    page.get_by_role("combobox", name="Model").select_option(label=PROVIDER)
    page.get_by_role("textbox", name="Question").fill(QUESTION)
    page.get_by_role("button", name="Ask", exact=True).click()
    turn = page.get_by_role("region", name=f"Question: {QUESTION}")
    turn.get_by_role("table", name="Results").wait_for(timeout=60_000)
    turn.get_by_role("list", name="Summary").wait_for(timeout=60_000)
    turn.locator("details summary").first.click()
    turn.get_by_label("Generated SQL").wait_for(timeout=WAIT_MS)
    page.wait_for_load_state("networkidle")
    # The answer from its question down to the model's name, under the sticky top bar.
    turn.evaluate(
        "el => { el.style.scrollMarginTop = '64px'; el.scrollIntoView({block: 'start'}) }"
    )


def m365_admin(page: Page, url: str) -> None:
    page.goto(url + "/investigate/views/admin")
    page.get_by_text("Admin changes", exact=True).wait_for(timeout=WAIT_MS)


def ai_usage(page: Page, url: str) -> None:
    page.goto(url + "/ai")
    page.get_by_role("heading", name="AI usage", exact=True).wait_for(timeout=WAIT_MS)


def agents(page: Page, url: str, session: str) -> None:
    page.goto(f"{url}/agents/sessions#session={session}")
    pane = page.get_by_role("region", name="Session detail")
    pane.wait_for(timeout=WAIT_MS)
    pane.get_by_label("This session in numbers").wait_for(timeout=WAIT_MS)
    pane.locator("[data-session-bar]").wait_for(timeout=WAIT_MS)
    pane.get_by_role("list", name="Session steps").wait_for(timeout=WAIT_MS)
    page.wait_for_load_state("networkidle")
    page.get_by_role("region", name="The open session").evaluate(
        "el => { el.style.scrollMarginTop = '56px'; el.scrollIntoView({block: 'start'}) }"
    )


def health(page: Page, url: str) -> None:
    page.goto(url + "/health")
    page.get_by_role("heading", name="Health", exact=True).wait_for(timeout=WAIT_MS)


def palette(page: Page, url: str) -> None:
    dashboard(page, url)
    settled(page, "command-palette")
    page.keyboard.press("Control+k")
    dialog = page.get_by_role("dialog", name="Command palette")
    dialog.wait_for(timeout=WAIT_MS)
    page.keyboard.type("frank", delay=60)
    dialog.get_by_role("option").filter(has_text="frank").first.wait_for(timeout=WAIT_MS)
    page.wait_for_load_state("networkidle")


def capture(url: str, out: Path, only: list[str] | None = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    session = busiest_session(url)
    shots: list[tuple[str, Callable[[Page, str], None]]] = [
        ("dashboard", dashboard),
        ("search", search),
        ("ask", ask),
        ("m365-admin", m365_admin),
        ("ai-usage", ai_usage),
        ("agents", lambda page, u: agents(page, u, session)),
        ("health", health),
        ("command-palette", palette),
    ]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for theme in ("dark", "light"):
            ctx = browser.new_context(viewport=SIZE, color_scheme=theme, timezone_id="UTC")  # type: ignore[arg-type]
            ctx.add_init_script(f"localStorage.setItem('app.theme', '{theme}')")
            signed = ctx.request.post(url + "/api/auth/login", data=devauth.account(DATA))
            if not signed.ok:
                sys.exit(f"could not sign in to the demo ({signed.status}); run `make demo` again")
            for base, take in shots:
                if only and base not in only:
                    continue
                name = f"{base}.png" if theme == "dark" else f"{base}-light.png"
                page = ctx.new_page()
                errors: list[str] = []
                page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
                page.on(
                    "console",
                    lambda m, errors=errors: errors.append(m.text) if m.type == "error" else None,
                )
                try:
                    take(page, url)
                    settled(page, name)
                    if errors:
                        raise ShotError(f"{name}: console error: {errors[0]}")
                    page.screenshot(path=str(out / name))
                except PlaywrightError as e:
                    page.screenshot(path=str(Path(tempfile.gettempdir()) / f"failed-{name}"))
                    raise ShotError(f"{name}: {e.message.splitlines()[0]}") from e
                finally:
                    page.close()
                print(name)
            ctx.close()
        browser.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", default="http://127.0.0.1:8090")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "images")
    ap.add_argument("--only", action="append", help="take only this shot (repeatable): ask")
    args = ap.parse_args()
    url = args.url.rstrip("/")
    try:
        call(url, "GET", "/api/auth/state")
    except (urllib.error.URLError, ConnectionError):
        sys.exit(f"no demo server at {url}: run `make demo` first")
    session = devauth.sign_in(url, DATA)
    if session is not None:
        SESSION.update(session.headers())
    model = add_model(url)
    try:
        capture(url, args.out, args.only)
    except ShotError as e:
        sys.exit(f"screenshot failed: {e}")
    finally:
        model.terminate()


if __name__ == "__main__":
    main()
