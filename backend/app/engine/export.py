"""CSV export of query results for spreadsheet tools.

Log text is untrusted: a text value starting with = + - @ or a tab or carriage return
would run as a formula in Excel or Sheets, so it gets a leading apostrophe (OWASP CSV
injection guidance). Numbers stay numbers.
"""

import csv
import io
import json
from collections.abc import Sequence
from typing import Any

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict | list):
        text = json.dumps(value)
    elif isinstance(value, str):
        text = value
    else:
        return str(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


def to_csv(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow([_cell(c) for c in columns])
    writer.writerows([_cell(v) for v in row] for row in rows)
    return out.getvalue()
