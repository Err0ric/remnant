"""Template transforms (SPEC 4.1), applied to parsed fields in order after the payload parse.

A transform that cannot apply to a value (not a number, no regex match, bad timestamp)
sets the field to None and reports an error code; it never raises on log content. A
regex_extract or map with `optional: true` that does not match changes nothing and is no
error. For to_int and timestamp, "-" and "" mean "no value" and become None without an
error. `pick` copies the field named by this field's value (Inbound -> the remote address).
"""

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any

import regex

from app.ingest.payload.regexpayload import MATCH_TIMEOUT_S
from app.templates.validator import Transform

MISSING = object()
# Log formats write "-" or nothing for "no value"; converting ops treat those as empty.
_EMPTY = ("", "-")
MAX_TEXT = 65_536  # longest string a transform may produce


def get_path(fields: dict[str, Any], path: str) -> Any:
    """Read a field: an exact key first, then a dotted path into nested objects."""
    if path in fields:
        return fields[path]
    value: Any = fields
    for part in path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return MISSING
    return value


class TransformRunner:
    def __init__(
        self,
        transforms: list[Transform],
        default_tz: tzinfo,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._steps = [(t, _prepare(t)) for t in transforms]
        self._tz = default_tz
        self._clock = clock

    def apply(self, fields: dict[str, Any]) -> list[str]:
        """Transform `fields` in place; return error codes for values that did not convert."""
        errors: list[str] = []
        for t, compiled in self._steps:
            value = get_path(fields, t.field)
            if value is MISSING or value is None:
                continue
            if (
                t.op in ("to_int", "timestamp")
                and isinstance(value, str)
                and value.strip() in _EMPTY
            ):
                if str(t.args.get("into", t.field)) == t.field:
                    fields[t.field] = None
                continue  # an empty value never overwrites a different target
            if t.op == "join":
                parts = [value, *(get_path(fields, f) for f in t.args["with"])]
                # Objects and lists never make a useful key part: skipping them lets a join
                # list the scalar and the object form of the same field (EVTX EventID).
                text = [
                    str(p)
                    for p in parts
                    if p is not MISSING and p not in (None, "") and not isinstance(p, dict | list)
                ]
                fields[str(t.args["into"])] = str(t.args.get("sep", ":")).join(text)
                continue
            if t.op == "pick":
                ref = t.args["from"].get(str(value)) if not isinstance(value, dict | list) else None
                picked = get_path(fields, ref) if ref is not None else MISSING
                if picked is not MISSING and picked is not None:
                    fields[str(t.args["into"])] = picked
                continue  # nothing to pick is no error: the value names no known choice
            if (
                t.op == "map"
                and t.args.get("optional") is True
                and str(value) not in t.args["values"]
            ):
                continue  # an optional map with no entry leaves the target alone
            try:
                result = _run(t, compiled, value, self._tz, self._clock)
            except (ValueError, TypeError, OverflowError, TimeoutError, IndexError, KeyError):
                result, ok = None, False
            else:
                ok = result is not None
            target = str(t.args.get("into", t.field))
            if not ok and t.op == "regex_extract" and t.args.get("optional") is True:
                continue  # an optional extraction that does not match leaves the target alone
            fields[target] = result
            if not ok:
                errors.append(f"transform_{t.op}:{t.field}"[:80])
        return errors


def _prepare(t: Transform) -> regex.Pattern[str] | None:
    if t.op in ("regex_extract", "replace"):
        return regex.compile(str(t.args["pattern"]))
    return None


def _run(
    t: Transform,
    compiled: regex.Pattern[str] | None,
    value: Any,
    tz: tzinfo,
    clock: Callable[[], datetime],
) -> Any:
    a = t.args
    if t.op == "to_int":
        if isinstance(value, bool):
            raise ValueError("bool")
        if isinstance(value, float):
            if not value.is_integer():
                raise ValueError("fraction")
            number = int(value)
        else:
            text = str(value).strip()
            if len(text) > 80:  # longer than any int64 in base 2, 8, 10, or 16
                raise OverflowError("too long")
            number = int(text, 0 if str(a.get("base", "10")) == "auto" else 10)
        if not -(2**63) <= number < 2**63:
            raise OverflowError("int64")
        return number
    if isinstance(value, list) and t.op == "regex_extract":
        # A list of cells (a CSV row's extra columns, `_extra`) is searched as its scalar
        # items joined with commas, so a pattern can find a field whose position varies.
        value = ",".join(str(v) for v in value if v is not None and not isinstance(v, dict | list))
    text = value if isinstance(value, str) else str(value)
    if t.op == "to_lower":
        return text.lower()
    if t.op == "to_upper":
        return text.upper()
    if t.op == "strip":
        return text.strip(a.get("chars")) if a.get("chars") is not None else text.strip()
    if t.op == "split":
        parts = text.split(str(a["sep"]))
        index = int(a.get("index", 0))
        return parts[index] if -len(parts) <= index < len(parts) else None
    if t.op == "regex_extract":
        assert compiled is not None
        m = compiled.search(text, timeout=MATCH_TIMEOUT_S)
        if not m:
            return None
        group = a.get("group", 1)
        return m.group(group)
    if t.op == "map":
        values: dict[str, Any] = a["values"]
        return values.get(text, a.get("default"))
    if t.op == "replace":
        assert compiled is not None
        repl = str(a.get("with", ""))
        # Bound the work before building the string: past this many substitutions the
        # result is over MAX_TEXT anyway and is refused below.
        limit = MAX_TEXT // len(repl) + 1 if repl else 0
        out = compiled.sub(repl, text, count=limit, timeout=MATCH_TIMEOUT_S)
        if len(out) > MAX_TEXT:
            raise ValueError("replace result too long")
        return out
    if t.op == "timestamp":
        formats = a["format"] if isinstance(a["format"], list) else [a["format"]]
        for fmt in formats[:-1]:
            try:
                return _timestamp(value, str(fmt), tz, clock)
            except (ValueError, TypeError, OverflowError):
                continue
        return _timestamp(value, str(formats[-1]), tz, clock)
    raise ValueError(t.op)  # pragma: no cover  # the schema allows only the ops above


_BSD = re.compile(
    r"([A-Z][a-z]{2})\s+(\d{1,2})(?:\s+(\d{4}))?\s+(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?"
    r"(?:\s+([A-Z]{2,5}))?"
)
_MONTHS = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}
_UTC_NAMES = frozenset({"UTC", "GMT", "Z", "UT"})


def _bsd(text: str, tz: tzinfo, clock: Callable[[], datetime]) -> datetime:
    """Syslog-style 'Oct  9 [2026] 20:41:12[.123] [UTC]'. A missing year is the most recent
    one that does not put the time more than a week in the future. Zone names other than
    UTC/GMT are ambiguous, so they fall back to the source time zone."""
    m = _BSD.fullmatch(text.strip().lstrip("*."))
    if m is None or m.group(1) not in _MONTHS:
        raise ValueError("not a syslog timestamp")
    mon, day, year, hh, mi, ss, frac, zone = m.groups()
    zone_tz = UTC if zone in _UTC_NAMES else tz
    micro = int((frac or "0")[:6].ljust(6, "0"))
    now = clock()
    y = int(year) if year else now.year
    parsed = datetime(y, _MONTHS[mon], int(day), int(hh), int(mi), int(ss), micro, zone_tz)
    if not year and parsed > now + timedelta(days=7):
        parsed = parsed.replace(year=y - 1)
    return parsed.astimezone(UTC)


def _timestamp(
    value: Any, fmt: str, tz: tzinfo, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
) -> datetime:
    if isinstance(value, bool):
        raise TypeError("bool")
    if fmt == "bsd":
        return _bsd(str(value), tz, clock)
    if fmt == "epoch_auto":
        # Devices disagree on the unit (FortiOS changed it between releases): pick it from
        # the number of integer digits, 10 s, 13 ms, 16 us, 19 ns.
        text = str(value).strip()
        digits = len(text.split(".", 1)[0].lstrip("-"))
        scale = {10: 1, 13: 10**3, 16: 10**6, 19: 10**9}.get(digits)
        if scale is None:
            raise ValueError("epoch digits")
        whole = int(text.split(".", 1)[0])
        return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(
            seconds=whole // scale, microseconds=(whole % scale) * 10**6 // scale
        )
    if fmt in ("epoch", "epoch_ms"):
        seconds = float(value) / (1000 if fmt == "epoch_ms" else 1)
        return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds)
    text = str(value).strip()
    if fmt == "iso8601":
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00") if text.endswith("Z") else text)
    else:
        parsed = datetime.strptime(text, fmt)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(UTC)
