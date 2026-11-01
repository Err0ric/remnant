"""Wall-clock times without a zone, read in a source's zone around a clock change (owner,
2026-11-01; SPEC D140). Used by the syslog envelope and by template timestamps.

- A repeated hour (fall back, 01:30 happens twice): a live event takes the reading
  closest to when it arrived and not after it; otherwise the earliest reading not before
  the source's previous event when there is one, else the first reading. Noted
  `ambiguous_local_time`.
- A skipped hour (spring forward, 02:30 never happens): read with the offset before the
  change, as a clock not yet moved forward shows it (02:30 PST is 03:30 PDT). Noted
  `nonexistent_local_time`.

The notes go in `parse_errors` for finding these events; they do not make a parse partial.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, tzinfo

AMBIGUOUS = "ambiguous_local_time"
NONEXISTENT = "nonexistent_local_time"
NOTES = frozenset({AMBIGUOUS, NONEXISTENT})
# A live event is stamped at most this long before it arrives.
LIVE_WINDOW = timedelta(hours=3)
CLOCK_SKEW = timedelta(minutes=2)


def localize(
    naive: datetime, tz: tzinfo, now: datetime, last: datetime | None = None
) -> tuple[datetime, str | None]:
    """`naive` read in `tz`, in UTC, with a note when the clock change made it unclear."""
    a = naive.replace(tzinfo=tz, fold=0).astimezone(UTC)
    b = naive.replace(tzinfo=tz, fold=1).astimezone(UTC)
    if a == b:
        return a, None
    if a.astimezone(tz).replace(tzinfo=None) != naive:
        return a, NONEXISTENT  # fold=0 uses the offset before the change
    early, late = sorted((a, b))
    now = now.astimezone(UTC)
    if now - late <= LIVE_WINDOW and late <= now + CLOCK_SKEW:
        return late, AMBIGUOUS  # both possible; the later is closer to arrival
    if now - early <= LIVE_WINDOW and early <= now + CLOCK_SKEW:
        return early, AMBIGUOUS  # the later reading would be in the future
    if last is not None and early < last - CLOCK_SKEW:
        return late, AMBIGUOUS  # the source already passed the first reading
    return early, AMBIGUOUS
