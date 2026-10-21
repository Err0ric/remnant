"""JSON text that DuckDB's json functions always accept.

Log content can carry values Python's json module would write but DuckDB rejects: lone
UTF-16 surrogates (from escapes like \\ud800) and non-finite floats (NaN, 1e999). Those
are replaced value by value, so one hostile field never costs the rest of the event.
"""

import json
import math
from typing import Any

_MAX_DEPTH = 200


def clean_text(text: str) -> str:
    """Lone surrogates become U+FFFD; valid text is returned unchanged."""
    if text.isascii():
        return text
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    return text


def _clean(value: Any, depth: int) -> Any:
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if depth >= _MAX_DEPTH:
        return "..." if isinstance(value, dict | list | tuple) else value
    if isinstance(value, dict):
        return {clean_text(str(k)): _clean(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_clean(v, depth + 1) for v in value]
    if isinstance(value, int | bool) or value is None:
        return value
    return clean_text(str(value))


def dumps(value: Any) -> str:
    return json.dumps(_clean(value, 0), separators=(",", ":"), allow_nan=False)
