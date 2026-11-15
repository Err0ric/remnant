#!/usr/bin/env python3
"""Contrast check for the color tokens (DESIGN.md section 9, ADR-0052 section 3.10).

Reads frontend/src/styles/tokens.css and fails when a token pair drops under WCAG AA in
either theme: 4.5:1 for text, 3:1 for marks, dots, control edges, focus rings and chart
series. Translucent tokens are composited over the surface they sit on first. It also fails
when a color in tokens.css differs from the token mapping in docs/DESIGN.md section 11.

    python3 scripts/check-contrast.py            # check, print failures
    python3 scripts/check-contrast.py --list     # print every pair with its ratio
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "frontend" / "src" / "styles" / "tokens.css"
DESIGN = ROOT / "docs" / "DESIGN.md"

TEXT, MARK = 4.5, 3.0
# Chart series (DESIGN.md section 2): the neutral and the four categorical colors.
SERIES = ["series-neutral", "series-1", "series-2", "series-3", "series-4"]
Color = tuple[float, float, float, float]

# What text and marks sit on. A pair of names is a translucent token over its backdrop.
SURFACES = ["bg", "surface", "surface-head", "surface-expand", "inset"]
TINTS = [("row-selected", "surface"), ("warn-tint", "surface")]
# Pressed segment, selected row or chip. globals.css turns muted text into secondary there.
PRESSED = ("accent-subtle", "surface")
TEXTS = ["text", "text-secondary", "text-muted", "accent-text"]
STATES = ["ok", "warn", "danger"]


def blocks(css: str) -> dict[str, dict[str, str]]:
    """Declarations of the dark and light theme blocks, light inheriting from dark."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    found: dict[str, dict[str, str]] = {"dark": {}, "light": {}}
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        decls = dict(re.findall(r"--([\w-]+)\s*:\s*([^;]+);", body))
        if 'data-theme="dark"' in selector:
            found["dark"].update(decls)
        elif 'data-theme="light"' in selector:
            found["light"].update(decls)
    found["light"] = {**found["dark"], **found["light"]}
    return found


def parse(value: str, theme: dict[str, str]) -> Color | None:
    value = value.strip()
    ref = re.fullmatch(r"var\(--([\w-]+)\)", value)
    if ref:
        return parse(theme[ref.group(1)], theme)
    if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        red, green, blue = (float(int(value[i : i + 2], 16)) for i in (1, 3, 5))
        return (red, green, blue, 1.0)
    rgba = re.fullmatch(r"rgba\(([^)]+)\)", value)
    if rgba:
        r, g, b, a = (float(x) for x in rgba.group(1).split(","))
        return (r, g, b, a)
    return None


def over(top: Color, under: Color) -> Color:
    a = top[3]
    return (*(top[i] * a + under[i] * (1 - a) for i in range(3)), 1.0)  # type: ignore[return-value]


def luminance(c: Color) -> float:
    def channel(v: float) -> float:
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(c[0]) + 0.7152 * channel(c[1]) + 0.0722 * channel(c[2])


def ratio(fg: Color, bg: Color) -> float:
    a, b = luminance(over(fg, bg)), luminance(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def pairs() -> list[tuple[str, str | tuple[str, str], float]]:
    """(foreground token, background, minimum). The background is a token or (tint, under)."""
    grounds: list[str | tuple[str, str]] = [*SURFACES, *TINTS]
    out: list[tuple[str, str | tuple[str, str], float]] = []
    out += [(t, g, TEXT) for t in TEXTS for g in grounds]
    out += [(t, "nav", TEXT) for t in TEXTS]
    out += [(t, PRESSED, TEXT) for t in TEXTS if t != "text-muted"]
    # State colors are text on plain surfaces; --warn is also the text of a blind row.
    out += [(s, g, TEXT) for s in STATES for g in ["bg", "surface", "surface-head"]]
    out += [("warn", ("warn-tint", "surface"), TEXT)]
    out += [("on-accent", "accent", TEXT), ("sev-c-on", "sev-c-solid", TEXT)]
    out += [("sev-h-on", "sev-h-solid", TEXT), ("info-tx", "info-bg", TEXT)]
    out += [
        ("local-tx", ("local-bg", "surface"), TEXT),
        ("cloud-tx", ("cloud-bg", "surface"), TEXT),
    ]
    # Marks: dots, outlines, control edges, the focus ring, chart series.
    out += [(d, g, MARK) for d in ["sev-m-dot", "text-muted", "accent-text", "warn", "local-tx"]
            for g in ["surface", "surface-head"]]  # fmt: skip
    out += [("border-control", g, MARK) for g in grounds if g in ("surface", "inset", TINTS[0])]
    out += [("focus-ring", g, MARK) for g in [*grounds, PRESSED]]
    out += [("focus-ring-top", "top", MARK)]
    out += [(s, g, MARK) for s in SERIES for g in ["surface", "surface-head"]]
    # State tags are outlined, not filled: the state color is text on a plain surface, and
    # the neutral tag is secondary text on the Info fill.
    out += [(s, g, TEXT) for s in ["warn", "danger"] for g in ["surface-expand", "inset"]]
    out += [("text-secondary", "info-bg", TEXT)]
    return out


def check(css: str) -> tuple[list[str], list[str]]:
    """(every pair as a line, the failing lines)."""
    lines: list[str] = []
    failures: list[str] = []
    for name, theme in blocks(css).items():
        for fg, ground, need in pairs():
            if isinstance(ground, tuple):
                tint, under = (parse(theme[g], theme) for g in ground)
                label = f"{ground[0]} over {ground[1]}"
            else:
                tint, under, label = None, parse(theme[ground], theme), ground
            color = parse(theme[fg], theme)
            assert color and under, f"unreadable color in {name}: {fg} on {label}"
            got = ratio(color, over(tint, under) if tint else under)
            line = f"{name:5} {fg} on {label}: {got:.2f} (needs {need})"
            lines.append(line)
            if got < need:
                failures.append(line)
    return lines, failures


def drift(css: str, design: str) -> list[str]:
    """Color values in tokens.css that differ from DESIGN.md section 11."""
    section = design.split("## 11. Token mapping", 1)[-1]
    fenced = re.search(r"```css\n(.*?)```", section, flags=re.S)
    if not fenced:
        return ["docs/DESIGN.md section 11 has no css block"]
    ours, theirs = blocks(css), blocks(fenced.group(1))
    out = []
    for name in ("dark", "light"):
        for token, value in theirs[name].items():
            mine = ours[name].get(token)
            a, b = parse(mine or "", ours[name]), parse(value, theirs[name])
            # A value this script cannot read (3-digit hex, rgb()) never counts as a match.
            if a is None or b is None or a != b:
                out.append(f"{name} --{token}: tokens.css has {mine}, DESIGN.md has {value}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--tokens", type=Path, default=TOKENS)
    ap.add_argument("--list", action="store_true", help="print every pair with its ratio")
    args = ap.parse_args()
    css = args.tokens.read_text(encoding="utf-8")
    lines, failures = check(css)
    differs = drift(css, DESIGN.read_text(encoding="utf-8"))
    if args.list:
        print("\n".join(lines))
    for line in failures:
        print(f"FAIL {line}")
    for line in differs:
        print(f"DIFFERS {line}")
    if failures or differs:
        print(f"\n{len(failures)} of {len(lines)} pairs fail; {len(differs)} values differ.")
        return 1
    print(f"All {len(lines)} pairs pass in both themes; tokens.css matches DESIGN.md section 11.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
