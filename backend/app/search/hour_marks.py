"""Unusual hours on the Overview volume (D65).

Each hour of the last 24 is compared with the same hour of day on the days before it (up
to 7). The rules are plain on purpose, so an analyst can say why a cell is marked:

- typical: the median of that hour over the earlier days, once a source has 3 days of
  history; before that nothing is marked.
- busy: at least 3 times typical and at least 20 events more (activity at an hour that is
  usually empty counts once it reaches 20).
- quiet: typical is at least 20 and the hour has a quarter of that or less. The current
  hour is never quiet, because it is not over yet.
"""

from statistics import median

MIN_DAYS = 3
BUSY_RATIO = 3.0
BUSY_MIN_EXTRA = 20
QUIET_MIN_TYPICAL = 20
QUIET_RATIO = 0.25


def typical(history: list[int]) -> float | None:
    """Median of the same hour on earlier days, or None with fewer than MIN_DAYS."""
    if len(history) < MIN_DAYS:
        return None
    return float(median(history))


def mark_hours(counts: list[int], usual: list[float | None], current: int = -1) -> list[str]:
    """'busy', 'quiet', or '' per hour. `current` is the index of the unfinished hour."""
    marks: list[str] = []
    for i, (n, t) in enumerate(zip(counts, usual, strict=True)):
        mark = ""
        if t is not None:
            if n >= BUSY_RATIO * t and n - t >= BUSY_MIN_EXTRA:
                mark = "busy"
            elif t >= QUIET_MIN_TYPICAL and n <= QUIET_RATIO * t and i != current:
                mark = "quiet"
        marks.append(mark)
    return marks
