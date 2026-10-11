"""Terminal-safe rendering for CLI output (SPEC T17).

Log content is hostile: every value is stripped of terminal control sequences
(ANSI escapes, OSC, C0/C1 controls) before printing.
"""

import csv
import io
import json
import re
from collections.abc import Sequence
from typing import Any, Literal

OutputFormat = Literal["table", "json", "csv", "raw"]

_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def clean(value: Any) -> str:
    """Render one value as safe single-line text."""
    if value is None:
        return "·"
    text = (
        value
        if isinstance(value, str)
        else json.dumps(value)
        if isinstance(value, dict | list)
        else str(value)
    )
    text = _ANSI.sub("", text)
    text = text.replace("\r\n", " ").replace("\n", " ").replace("\t", " ")
    return _CONTROL.sub("", text)


def clean_block(value: str) -> str:
    """Multi-line text (SQL, model explanations) with control sequences removed."""
    text = _ANSI.sub("", value).replace("\r\n", "\n").replace("\t", "    ")
    return "\n".join(_CONTROL.sub("", line) for line in text.split("\n"))


def render(
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
    fmt: OutputFormat,
    width: int = 160,
    header: bool = True,
) -> str:
    if fmt == "json":
        return "\n".join(
            json.dumps({c: _safe_json(v) for c, v in zip(columns, row, strict=True)})
            for row in rows
        )
    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        if header:
            writer.writerow(columns)
        writer.writerows([[clean(v) if v is not None else "" for v in row] for row in rows])
        return buf.getvalue().rstrip("\n")
    if fmt == "raw":
        idx = columns.index("raw") if "raw" in columns else 0
        return "\n".join(clean(row[idx]) for row in rows)
    return _table(columns, rows, width, header)


def _table(
    columns: Sequence[str], rows: Sequence[Sequence[Any]], width: int, header: bool = True
) -> str:
    cells = [[clean(v) for v in row] for row in rows]
    widths = [len(c) for c in columns]
    for row in cells:
        for i, v in enumerate(row):
            widths[i] = min(max(widths[i], len(v)), 60)
    # Give the last column whatever room is left so wide messages are not cut too early.
    used = sum(widths[:-1]) + 2 * (len(widths) - 1)
    if widths:
        widths[-1] = max(min(widths[-1], width - used), len(columns[-1]))
    lines = []
    if header:
        lines.append(
            "  ".join(c.upper().ljust(w) for c, w in zip(columns, widths, strict=True)).rstrip()
        )
    for row in cells:
        lines.append("  ".join(_fit(v, w) for v, w in zip(row, widths, strict=True)).rstrip())
    return "\n".join(lines)


def _fit(value: str, width: int) -> str:
    return value.ljust(width) if len(value) <= width else value[: max(width - 1, 0)] + "…"


def _safe_json(value: Any) -> Any:
    if isinstance(value, str):
        return clean(value) if (_ANSI.search(value) or _CONTROL.search(value)) else value
    return value
