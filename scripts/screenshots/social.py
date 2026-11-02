#!/usr/bin/env python3
"""GitHub social preview (1280x640): the wordmark beside a crop of the demo Dashboard.

    python3 scripts/screenshots/social.py [--shot docs/images/dashboard.png] [--out docs/images/social-preview.png]

Run after capture.py. Uses the app's own colors (docs/DESIGN.md dark tokens), mark, and
fonts from the built frontend (frontend/dist), so nothing is fetched. Upload the PNG in the
repository's Settings > Social preview; GitHub does not read it from the tree.
"""

from __future__ import annotations

import argparse
import base64
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
MARK = (ROOT / "frontend" / "public" / "favicon.svg").read_text(encoding="utf-8")
PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
@font-face {{ font-family: "Source Sans 3"; font-weight: 400; src: url("{sans400}"); }}
@font-face {{ font-family: "Source Sans 3"; font-weight: 700; src: url("{sans700}"); }}
html, body {{ margin: 0; width: 1280px; height: 640px; overflow: hidden; background: #0f1115; }}
body {{ font-family: "Source Sans 3", system-ui, sans-serif; color: #e6e9ef; position: relative; }}
.left {{ position: absolute; left: 72px; top: 0; bottom: 0; width: 470px; display: flex;
  flex-direction: column; justify-content: center; gap: 22px; }}
.brand {{ display: flex; align-items: center; gap: 20px; }}
.brand svg {{ width: 76px; height: 76px; }}
.name {{ font-size: 76px; font-weight: 700; letter-spacing: -0.5px; line-height: 1; }}
.line {{ font-size: 34px; font-weight: 700; line-height: 1.15; }}
.sub {{ font-size: 23px; color: #a3acba; line-height: 1.35; }}
.shot {{ position: absolute; left: 600px; top: 72px; width: 1100px; border: 1px solid #272d38;
  border-radius: 8px; box-shadow: 0 0 0 8px #161a21; }}
.rule {{ position: absolute; left: 0; right: 0; bottom: 0; height: 6px; background: #2f6fe0; }}
</style></head><body>
<div class="left">
  <div class="brand">{mark}<span class="name">Remnant</span></div>
  <div class="line">Self-hosted AI usage monitoring</div>
  <div class="sub">Shadow AI, agents, and MCP servers in the logs you already have, on a local-first SIEM.</div>
</div>
<img class="shot" src="{shot}">
<div class="rule"></div>
</body></html>"""


def font(weight: int) -> str:
    found = sorted((ROOT / "frontend" / "dist" / "assets").glob(f"source-sans-3-latin-{weight}-normal-*.woff2"))  # fmt: skip
    if not found:
        raise SystemExit("frontend/dist is missing its fonts: build the frontend first")
    return found[0].as_uri()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--shot", type=Path, default=ROOT / "docs" / "images" / "dashboard.png")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "images" / "social-preview.png")
    args = ap.parse_args()
    shot = "data:image/png;base64," + base64.b64encode(args.shot.read_bytes()).decode()
    html = PAGE.format(sans400=font(400), sans700=font(700), mark=MARK, shot=shot)
    with tempfile.TemporaryDirectory() as tmp:
        page_file = Path(tmp) / "social.html"
        page_file.write_text(html, encoding="utf-8")
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 640})
            page.goto(page_file.as_uri())
            page.wait_for_timeout(500)
            page.screenshot(path=str(args.out))
            browser.close()
    print(args.out)


if __name__ == "__main__":
    main()
