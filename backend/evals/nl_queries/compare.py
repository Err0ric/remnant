"""Does a generated result answer the question the way the reference does?

A generated result matches when some of its columns, one per reference column, hold the
same values row for row: extra columns (an event id, a message) and a different column
order or alias are fine. Values are normalised so equivalent SQL spellings compare equal:
whole-number floats become ints, floats round to 4 places, a UTC midnight timestamp equals
its date. Rows whose compared values are all NULL are ignored on both sides.
"""

from collections import Counter
from datetime import UTC, date, datetime
from itertools import permutations
from typing import Any, Literal

Compare = Literal["set", "ordered"]
MAX_PERMUTATIONS = 5_000


def norm(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else round(value, 4)
    if isinstance(value, datetime):
        value = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        if (value.hour, value.minute, value.second, value.microsecond) == (0, 0, 0, 0):
            return value.date().isoformat()
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return _iso_or_text(value)
    return value


def _iso_or_text(text: str) -> Any:
    """Engine results arrive as JSON-safe strings; treat ISO timestamps as timestamps."""
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return text
        if len(text) == 10:
            return parsed.date().isoformat()
        return norm(parsed)
    return text


def _rows(rows: list[list[Any]], cols: tuple[int, ...]) -> list[tuple[Any, ...]]:
    out = []
    for row in rows:
        picked = tuple(norm(row[i]) for i in cols)
        if any(v is not None for v in picked):
            out.append(picked)
    return out


def matches(
    reference: list[list[Any]], ref_width: int, got: list[list[Any]], got_width: int, how: Compare
) -> bool:
    if ref_width == 0:
        return not got
    if got_width < ref_width:
        return False
    want = _rows(reference, tuple(range(ref_width)))
    want_counter = Counter(want)
    # Candidate columns for each reference column: same multiset of values.
    got_cols = [Counter(norm(r[i]) for r in got) for i in range(got_width)]
    ref_cols = [Counter(norm(r[i]) for r in reference) for i in range(ref_width)]
    candidates = [
        [j for j in range(got_width) if _same_values(ref_cols[i], got_cols[j])]
        for i in range(ref_width)
    ]
    if any(not c for c in candidates):
        return False
    tried = 0
    for choice in permutations(range(got_width), ref_width):
        if any(choice[i] not in candidates[i] for i in range(ref_width)):
            continue
        tried += 1
        if tried > MAX_PERMUTATIONS:
            return False
        have = _rows(got, choice)
        if (how == "ordered" and have == want) or (how == "set" and Counter(have) == want_counter):
            return True
    return False


def _same_values(a: Counter[Any], b: Counter[Any]) -> bool:
    """Columns may differ only in all-NULL rows, which are ignored."""
    a = Counter({k: v for k, v in a.items() if k is not None})
    b = Counter({k: v for k, v in b.items() if k is not None})
    return a == b
