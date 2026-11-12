#!/usr/bin/env python3
"""Smoke test (owner rule, 2026-11-08): open every page in headless Chromium as an Admin,
an Analyst, and an Auditor, and fail on any console error, any 4xx or 5xx response the
role is not expected to get, and any blank panel.

    cd backend && uv run python ../scripts/smoke.py --url http://127.0.0.1:8090  # a demo install
    cd backend && uv run python ../scripts/smoke.py --lake ../data/bench/lake    # this checkout
        # on a copy of the bench lake (bench_compare.py); Playwright is a backend dev dependency

Pages come from the app's route table (frontend/src/lib/route.ts: every path and tab). On
an install with no accounts (the demo, open mode) it first adds three synthetic accounts,
alice (Admin), bob (Analyst), and carol (Auditor); use it only on a throwaway install.
With `--lake` it serves frontend/dist, so build the frontend first.

The three roles run at once, one browser each.

A blank panel is: the page's main region showing under 40 characters of text, a loading
placeholder (aria-busy, "Loading...") still there 20 s after the page loaded, or a page or
card that says it could not be shown. Needs Python Playwright with Chromium.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import bench_compare as bc  # noqa: E402  # sibling script, standard library only
import devauth  # noqa: E402  # same

PASSWORD = "smoke-test-password-1"  # noqa: S105  # synthetic accounts on a throwaway install only
ROLES = (("alice", "admin"), ("bob", "analyst"), ("carol", "auditor"))
# Refusals a role is expected to get and the UI handles (it hides or explains the part).
# (role, method, path prefix). Keep this short; anything else is a failure.
EXPECTED: tuple[tuple[str, str, str], ...] = ()
# A person's page is the same route with a fragment, and one of the heaviest pages.
EXTRA = ["/investigate/people#user=alice"]
SETTLE_S = 20
MIN_TEXT = 40
BUSY = "main [aria-busy='true']"
BROKEN = ("could not be shown", "Something went wrong on this page")


def routes(route_ts: Path) -> list[str]:
    """Every page path and tab path in the route table, except the signed-out account page
    and the old Overview address (it redirects)."""
    src = route_ts.read_text(encoding="utf-8")
    block = re.search(r"const PATHS[^{]*\{(.*?)\n\};", src, re.S)
    tabs_block = re.search(r"PAGE_TABS[^{]*\{(.*?)\n\};", src, re.S)
    if not block or not tabs_block:
        raise RuntimeError(f"route table not found in {route_ts}")
    paths = dict(re.findall(r"^\s*(\w+): \"(/[^\"]*)\"", block.group(1), re.M))
    out = [p for k, p in paths.items() if k not in ("account", "overview")]
    for page, tabs in re.findall(r"^\s*(\w+): \[([^\]]*)\]", tabs_block.group(1), re.M):
        names = re.findall(r"\"([^\"]+)\"", tabs)
        out += [f"{paths[page]}/{t}" for t in names[1:]]
    return out + EXTRA


def accounts(base: str, data: Path) -> None:
    """One account per role, made by the install's administrator (the first account, which
    `devauth` makes through the one-time setup link when the server has none)."""
    if base not in bc.SESSIONS:
        session = devauth.sign_in(base, data)
        if session is None:
            raise RuntimeError(f"{base} runs without accounts: a server from before D245")
        bc.SESSIONS[base] = session
    api = bc.Api(base)
    have = {u["username"] for u in api.call("GET", "/api/users")}
    for name, role in ROLES:
        if name in have:
            continue  # made on an earlier run
        made = api.call("POST", "/api/users", {"username": name, "role": role})
        body = {"token": str(made["invite_token"]), "password": PASSWORD}
        req = urllib.request.Request(
            base + "/api/account/password", data=json.dumps(body).encode(), method="POST"
        )  # noqa: S310  # loopback
        req.add_header("Content-Type", "application/json")
        urllib.request.urlopen(req, timeout=60).close()  # noqa: S310  # loopback


def expected(role: str, method: str, url: str) -> bool:
    path = "/" + url.split("/", 3)[-1] if "://" in url else url
    return any(r == role and m == method and path.startswith(p) for r, m, p in EXPECTED)


def main_text(page) -> str:  # type: ignore[no-untyped-def]  # a Playwright page
    """The page's main region as a reader sees it; empty when there is none."""
    return str(page.inner_text("main")) if page.locator("main").count() else ""


def check(base: str, roles: tuple[tuple[str, str], ...] = ROLES) -> list[str]:
    from playwright.sync_api import sync_playwright

    problems: list[str] = []
    pages = routes(ROOT / "frontend" / "src" / "lib" / "route.ts")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for name, role in roles:
            ctx = browser.new_context()
            res = ctx.request.post(base + "/api/auth/login", data={"username": name, "password": PASSWORD})  # fmt: skip
            if not res.ok:
                problems.append(f"{role}: login failed ({res.status})")
                ctx.close()
                continue
            page = ctx.new_page()
            seen: list[str] = []
            refused: set[str] = set()

            def on_response(r, role: str = role, seen: list[str] = seen, refused: set[str] = refused) -> None:  # type: ignore[no-untyped-def]  # fmt: skip
                if r.status >= 400:
                    method = r.request.method
                    if expected(role, method, r.url):
                        refused.add(r.url)
                    else:
                        seen.append(f"{method} {r.url.replace(base, '')} {r.status}")

            def on_console(m, seen: list[str] = seen, refused: set[str] = refused) -> None:  # type: ignore[no-untyped-def]  # fmt: skip
                if m.type == "error" and (m.location or {}).get("url") not in refused:
                    if not m.text.startswith("Failed to load resource"):  # counted as a response
                        seen.append(f"console: {m.text[:200]}")

            page.on("response", on_response)
            page.on("console", on_console)
            page.on("pageerror", lambda e, seen=seen: seen.append(f"page error: {str(e)[:200]}"))
            for path in pages:
                seen.clear()
                page.goto(base + path)
                try:
                    page.wait_for_load_state("networkidle", timeout=SETTLE_S * 1000)
                except Exception:  # noqa: S110  # a page that polls never goes idle
                    pass
                deadline = time.monotonic() + SETTLE_S
                while time.monotonic() < deadline and (
                    page.locator(BUSY).count() or "Loading…" in main_text(page)
                ):
                    page.wait_for_timeout(500)
                text = main_text(page)
                if len(text.strip()) < MIN_TEXT:
                    seen.append("blank: the main region has almost no text")
                if page.locator(BUSY).count() or "Loading…" in text:
                    seen.append(f"blank: still loading after {SETTLE_S} s")
                seen += [f"blank: says '{b}'" for b in BROKEN if b in text]
                problems += [f"{role} {path}: {s}" for s in dict.fromkeys(seen)]
            ctx.close()
        browser.close()
    return problems


def parallel(base: str) -> list[str]:
    """The three roles at once, one browser process each (owner, 2026-11-08)."""
    kids = [
        subprocess.Popen(  # noqa: S603  # this script, fixed arguments
            [sys.executable, __file__, "--url", base, "--role", role],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        for _, role in ROLES
    ]  # fmt: skip
    problems: list[str] = []
    for kid, (_, role) in zip(kids, ROLES, strict=True):
        out, _ = kid.communicate()
        problems += [x[5:] for x in out.splitlines() if x.startswith("FAIL ")]
        if kid.returncode != 0:
            problems.append(f"{role}: the browser run stopped: {out.strip()[-300:]}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    where = ap.add_mutually_exclusive_group(required=True)
    where.add_argument("--url", help="a running throwaway install, for example the demo")
    where.add_argument("--lake", type=Path, help="a bench lake (scripts/bench_compare.py)")
    ap.add_argument("--data", type=Path, default=ROOT / "data" / "demo" / "state",
                    help="with --url: that server's data folder (default: the demo's)")  # fmt: skip
    ap.add_argument("--role", choices=[r for _, r in ROLES], help=argparse.SUPPRESS)  # one child
    ap.add_argument("--python", default=str(ROOT / "backend" / ".venv" / "bin" / "python"))
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="smoke-"))
    proc = None
    try:
        base = (args.url or "").rstrip("/")
        if args.lake:
            lake = args.lake.resolve()
            if not (lake / "built.json").is_file():
                print(f"no bench lake at {lake}; run scripts/bench_compare.py first", file=sys.stderr)  # fmt: skip
                return 2
            shutil.copytree(lake / "data", tmp / "data")
            port = bc.free_port()
            dist = ROOT / "frontend" / "dist"
            proc = bc.serve(ROOT, tmp / "data", lake, port, tmp / "server.log", args.python, dist)
            base = f"http://127.0.0.1:{port}"
        if args.role:  # one of the parallel children below
            for p in check(base, tuple(x for x in ROLES if x[1] == args.role)):
                print(f"FAIL {p}")
            return 0
        accounts(base, tmp / "data" if args.lake else args.data)
        t = time.monotonic()
        problems = parallel(base)
        n = len(routes(ROOT / "frontend" / "src" / "lib" / "route.ts"))
        print(json.dumps({"pages": n, "roles": len(ROLES), "seconds": round(time.monotonic() - t)}))  # fmt: skip
        for p in problems:
            print(f"FAIL {p}")
        print("smoke: passed" if not problems else f"smoke: {len(problems)} problems")
        return 1 if problems else 0
    except (RuntimeError, OSError) as exc:
        print(f"smoke could not run: {exc}", file=sys.stderr)
        return 2
    finally:
        if proc is not None:
            bc.stop(proc)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
