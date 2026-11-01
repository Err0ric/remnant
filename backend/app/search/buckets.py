"""Chart buckets in the viewer's time zone (D133), correct across clock changes (owner,
2026-11-01).

Hours are counted from the window start (`$start`, a whole UTC hour or the viewer's
midnight), never by truncating local wall-clock time: on a fall-back day the repeated
local hour is two buckets, not one holding both and one empty, and a spring-forward day
has 23. Days are the viewer's wall-clock days (`$tz`), 23, 24, or 25 hours long."""

from __future__ import annotations


def bucket_sql(col: str = "t") -> str:
    """The bucket start of `col` for `$unit` ('hour' or 'day'); needs `$start` and `$tz`."""
    return (
        f"CASE WHEN $unit = 'hour' THEN time_bucket(INTERVAL 1 HOUR, {col}, $start)"
        f" ELSE timezone($tz, date_trunc($unit, timezone($tz, {col}))) END"
    )
