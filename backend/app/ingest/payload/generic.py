"""Generic payload parsers used before templates exist (Slice 1).

They only find a time and a message; everything else goes to `unmapped`.
Template-driven OCSF mapping arrives in Slice 3.
"""

import csv
import json
from collections.abc import Mapping
from datetime import UTC, datetime, tzinfo
from typing import Any

TIME_KEYS = ("@timestamp", "timestamp", "time", "EventTime", "TimeCreated", "eventTime", "date")
MESSAGE_KEYS = ("message", "Message", "msg", "MSG")
_EPOCH_MS_THRESHOLD = 10_000_000_000  # numbers above this are milliseconds


def parse_json_object(text: str) -> dict[str, Any] | None:
    """Return the object for a JSON line, or None if it is not a JSON object."""
    try:
        value = json.loads(text, parse_constant=str)  # NaN and Infinity stay as text
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


class CsvRowParser:
    """Stateful CSV parser: the first line is the header."""

    def __init__(self, delimiter: str = ",") -> None:
        self._delimiter = delimiter
        self._columns: list[str] | None = None

    def parse(self, text: str) -> tuple[dict[str, Any], bool] | None:
        """Return (row, column_count_ok), or None when the line was the header."""
        cells = next(csv.reader([text], delimiter=self._delimiter), [])
        if self._columns is None:
            self._columns = [c.strip() for c in cells]
            return None
        row: dict[str, Any] = dict(zip(self._columns, cells, strict=False))
        ok = len(cells) == len(self._columns)
        if len(cells) > len(self._columns):
            row["_extra"] = cells[len(self._columns) :]
        return row, ok


def find_time(obj: Mapping[str, Any], default_tz: tzinfo) -> datetime | None:
    for key in TIME_KEYS:
        if key in obj:
            parsed = _to_datetime(obj[key], default_tz)
            if parsed is not None:
                return parsed
    return None


def find_message(obj: Mapping[str, Any]) -> str | None:
    for key in MESSAGE_KEYS:
        value = obj.get(key)
        if isinstance(value, str):
            return value
    return None


SUMMARY_CHARS = 300


def summarize(obj: Mapping[str, Any]) -> str | None:
    """A short `key=value` line for rows that carry no message field, so a generic CSV or
    JSON row is not blank in a results table. Time fields, empty values, and nested values
    are left out; everything stays in `unmapped` and `raw` is untouched."""
    parts: list[str] = []
    for key, value in obj.items():
        if key in TIME_KEYS or value is None or value == "" or isinstance(value, dict | list):
            continue
        parts.append(f"{key}={str(value).lower() if isinstance(value, bool) else value}")
    text = " ".join(parts)
    if len(text) > SUMMARY_CHARS:
        text = text[: SUMMARY_CHARS - 1] + "…"
    return text or None


def _to_datetime(value: Any, default_tz: tzinfo) -> datetime | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        seconds = value / 1000 if value > _EPOCH_MS_THRESHOLD else value
        try:
            return datetime.fromtimestamp(seconds, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value:
        return None
    text = value.strip().replace("Z", "+00:00") if value.strip().endswith("Z") else value.strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=default_tz)
    return parsed.astimezone(UTC)
