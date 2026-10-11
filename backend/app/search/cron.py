"""Five-field cron schedules (SPEC 5.5): minute hour day-of-month month day-of-week.

Supported in each field: `*`, numbers, ranges `a-b`, lists `a,b`, and steps `*/n`, `a-b/n`.
Day of week is 0 to 7 (0 and 7 are Sunday). As in standard cron, when both day of month
and day of week are restricted, a day matches if either does. Times are wall-clock times
in the installation's time zone; the next fire time is returned in UTC. An expression
that would never fire within five years (for example 31 February) is refused.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo

from app.core.errors import ParamInvalidError

PRESETS: dict[str, str] = {
    "hourly": "0 * * * *",
    "daily": "0 7 * * *",
    "weekdays": "0 7 * * 1-5",
}
MAX_LENGTH = 100
_HORIZON = timedelta(days=366 * 5)
_FIELDS = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day of month", 1, 31),
    ("month", 1, 12),
    ("day of week", 0, 7),
)


def _field(text: str, name: str, low: int, high: int) -> frozenset[int]:
    values: set[int] = set()
    for part in text.split(","):
        base, _, step_text = part.partition("/")
        step = 1
        if step_text:
            if not step_text.isdigit() or int(step_text) == 0:
                raise ParamInvalidError(f"Cron {name}: step must be a positive number")
            step = int(step_text)
        if base == "*":
            start, end = low, high
        elif "-" in base:
            a, _, b = base.partition("-")
            if not (a.isdigit() and b.isdigit()):
                raise ParamInvalidError(f"Cron {name}: {part!r} is not a range")
            start, end = int(a), int(b)
        elif base.isdigit():
            start = end = int(base)
            if step_text:
                end = high
        else:
            raise ParamInvalidError(f"Cron {name}: {part!r} is not a number, range, or *")
        if not (low <= start <= end <= high):
            raise ParamInvalidError(f"Cron {name}: values must be {low} to {high}")
        values.update(range(start, end + 1, step))
    return frozenset(values)


@dataclass(frozen=True, slots=True)
class Cron:
    expr: str
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]  # 0 is Sunday
    day_restricted: bool
    weekday_restricted: bool

    @classmethod
    def parse(cls, expr: str) -> "Cron":
        if len(expr) > MAX_LENGTH:
            raise ParamInvalidError(f"Cron expressions are limited to {MAX_LENGTH} characters")
        parts = expr.split()
        if len(parts) != 5:
            raise ParamInvalidError("Cron needs five fields: minute hour day month weekday")
        sets = [_field(p, n, lo, hi) for p, (n, lo, hi) in zip(parts, _FIELDS, strict=True)]
        cron = cls(
            expr=" ".join(parts),
            minutes=sets[0],
            hours=sets[1],
            days=sets[2],
            months=sets[3],
            weekdays=frozenset(d % 7 for d in sets[4]),
            day_restricted=parts[2] != "*",
            weekday_restricted=parts[4] != "*",
        )
        cron.next_after(datetime(2026, 1, 1, tzinfo=UTC), UTC)  # refuses one that never fires
        return cron

    def _day_ok(self, t: datetime) -> bool:
        day = t.day in self.days
        weekday = (t.weekday() + 1) % 7 in self.weekdays
        if self.day_restricted and self.weekday_restricted:
            return day or weekday
        return day and weekday

    def next_after(self, after: datetime, tz: tzinfo) -> datetime:
        """The first fire time strictly after `after`, in UTC."""
        if after.tzinfo is None:
            raise ValueError("after must be timezone-aware")
        t = after.astimezone(tz).replace(tzinfo=None, second=0, microsecond=0)
        t += timedelta(minutes=1)
        limit = t + _HORIZON
        while t <= limit:
            if t.month not in self.months:
                t = (t.replace(day=1) + timedelta(days=32)).replace(day=1, hour=0, minute=0)
            elif not self._day_ok(t):
                t = (t + timedelta(days=1)).replace(hour=0, minute=0)
            elif t.hour not in self.hours:
                t = (t + timedelta(hours=1)).replace(minute=0)
            elif t.minute not in self.minutes:
                t += timedelta(minutes=1)
            else:
                fire = t.replace(tzinfo=tz).astimezone(UTC)
                if fire > after:
                    return fire
                t += timedelta(minutes=1)
        raise ParamInvalidError("This schedule would never run")
