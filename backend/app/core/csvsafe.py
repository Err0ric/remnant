"""Spreadsheet-safe CSV cells (OWASP CSV injection guidance).

Log text is untrusted: a text value starting with = + - @ or a tab or carriage return
would run as a formula in Excel or Sheets, so it gets a leading apostrophe. Numbers stay
numbers. Shared by the server's export and the CLI's `--format csv`.
"""

from __future__ import annotations

import json
from typing import Any

FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def neutralize(text: str) -> str:
    return "'" + text if text.startswith(FORMULA_START) else text


def csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict | list):
        return neutralize(json.dumps(value))
    if isinstance(value, str):
        return neutralize(value)
    return str(value)
