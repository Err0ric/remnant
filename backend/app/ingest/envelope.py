"""Syslog envelope parser: RFC 5424, RFC 3164, or none (SPEC 3.5, 4.1).

Pure and deterministic: no I/O, no LLM. Every pattern is anchored and linear so
hostile lines cannot cause catastrophic backtracking (T14). Structured data is
parsed with a small state machine rather than a regex for the same reason.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.localtime import localize

Rfc = Literal["5424", "3164", "none", "labels"]  # labels: built from Loki stream labels

_MONTHS = {
    m: i
    for i, m in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
        start=1,
    )
}
_PRI = re.compile(r"<(\d{1,3})>")
_5424_HEADER = re.compile(
    r"<(\d{1,3})>(\d{1,2}) (\S{1,64}) (\S{1,255}) (\S{1,48}) (\S{1,128}) (\S{1,32})(?: |$)"
)
_RFC3339 = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})?"
)
# Optional fractional seconds: Cisco "service timestamps ... msec" writes "20:41:12.123".
_BSD_TS = re.compile(
    r"([A-Z][a-z]{2}) {1,2}(\d{1,2})(?: (\d{4}))? (\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?"
)
_TAG = re.compile(r"([^\s\[\]:]{1,64})(?:\[([^\]\s]{1,32})\])?: ?")
_HOST = re.compile(r"(\S{1,255})(?: |$)")
_ROLLOVER_FUTURE_DAYS = 7


class SyslogEnvelopeConfig(BaseModel):
    """Per-source envelope settings (template `envelope.syslog` block)."""

    model_config = ConfigDict(extra="forbid")

    rfc: Literal["auto", "3164", "5424"] = "auto"
    assume_year: Literal["current", "rollover_safe"] = "rollover_safe"
    timezone: str = "UTC"
    strip_relay_headers: bool = True
    max_relay_hops: int = Field(default=3, ge=0, le=3)

    @field_validator("timezone")
    @classmethod
    def _known_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown IANA timezone: {value}") from exc
        return value


@dataclass(frozen=True, slots=True)
class Envelope:
    rfc: Rfc
    msg: str
    pri: int | None = None
    timestamp: datetime | None = None
    hostname: str | None = None
    app_name: str | None = None
    procid: str | None = None
    msgid: str | None = None
    structured_data: dict[str, dict[str, str]] | None = None
    relay_hops: int = 0
    errors: tuple[str, ...] = field(default=())

    @property
    def facility(self) -> int | None:
        return None if self.pri is None else self.pri // 8

    @property
    def severity(self) -> int | None:
        return None if self.pri is None else self.pri % 8

    def to_column(self) -> dict[str, Any]:
        """Value for the `envelope` JSON column (SPEC 3.4)."""
        return {
            "rfc": self.rfc,
            "pri": self.pri,
            "facility": self.facility,
            "severity": self.severity,
            "hostname": self.hostname,
            "app_name": self.app_name,
            "procid": self.procid,
            "msgid": self.msgid,
            "structured_data": self.structured_data,
            "relay_hops": self.relay_hops,
        }


class EnvelopeParser:
    def __init__(
        self,
        config: SyslogEnvelopeConfig | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._cfg = config or SyslogEnvelopeConfig()
        self._tz = ZoneInfo(self._cfg.timezone)
        self._clock = clock
        # The source's previous event in UTC: orders a repeated local hour in a backfill.
        self._last: datetime | None = None

    def parse(self, line: str, hint: Envelope | None = None) -> Envelope:
        """Parse one decoded line. Never raises on bad input; problems go in `errors`.

        `hint` is an envelope built from outside the line (Loki stream labels). It is used
        when the line has no complete syslog header of its own; a real header always wins,
        and nothing is guessed from a line that has none (install finding 10)."""
        env = self._parse(line)
        if hint is None or (_is_real_header(env) and "no_header" not in env.errors):
            return env
        # The space a receiver leaves after stripping the header is not part of the payload
        # (Palo Alto CSV regexes are anchored at the first field). Only the working copy is
        # trimmed; `raw` keeps the line as received (rule 5).
        return replace(hint, msg=line.lstrip(" "), errors=())

    def _parse(self, line: str) -> Envelope:
        env = self._parse_once(line, forced=self._cfg.rfc)
        if not self._cfg.strip_relay_headers or env.rfc == "none":
            return env
        hops = 0
        while True:
            inner = self._parse_once(env.msg, forced="auto")
            if not _is_real_header(inner):
                return replace(env, relay_hops=hops)
            if hops >= self._cfg.max_relay_hops:
                return replace(env, relay_hops=hops, errors=(*env.errors, "relay_hops_capped"))
            hops += 1
            env = inner

    # -- single header -------------------------------------------------------------

    def _parse_once(self, line: str, forced: str) -> Envelope:
        if forced in ("auto", "5424"):
            env = self._parse_5424(line)
            if env is not None:
                return env
            if forced == "5424":
                return Envelope(rfc="none", msg=line, errors=("not_rfc5424",))
        env = self._parse_3164(line)
        if env is not None:
            return env
        errors = ("not_rfc3164",) if forced == "3164" else ()
        return Envelope(rfc="none", msg=line, errors=errors)

    def _parse_5424(self, line: str) -> Envelope | None:
        m = _5424_HEADER.match(line)
        if m is None or m.group(2) != "1":
            return None
        errors: list[str] = []
        pri = _valid_pri(int(m.group(1)), errors)
        ts_raw = m.group(3)
        timestamp = None
        if ts_raw != "-":
            timestamp = self._rfc3339(ts_raw, errors, require_full=True)
        sd, msg = _parse_structured_data(line[m.end() :], errors)
        return Envelope(
            rfc="5424",
            msg=msg.removeprefix("﻿"),
            pri=pri,
            timestamp=timestamp,
            hostname=_nil(m.group(4)),
            app_name=_nil(m.group(5)),
            procid=_nil(m.group(6)),
            msgid=_nil(m.group(7)),
            structured_data=sd,
            errors=tuple(errors),
        )

    def _parse_3164(self, line: str) -> Envelope | None:
        errors: list[str] = []
        pos = 0
        pri = None
        pm = _PRI.match(line)
        if pm:
            pri = _valid_pri(int(pm.group(1)), errors)
            pos = pm.end()

        timestamp: datetime | None
        tm = _RFC3339.match(line, pos)
        if tm and line[tm.end() : tm.end() + 1] in (" ", ""):
            timestamp = self._rfc3339(tm.group(0), errors, require_full=False)
            pos = tm.end()
        else:
            bm = _BSD_TS.match(line, pos)
            if bm is None or bm.group(1) not in _MONTHS:
                if pm is None:
                    return None
                # PRI with no header at all, as FortiGate and some appliances send
                # (`<189>date=... time=...`): keep the priority, the rest is the message.
                return Envelope(rfc="3164", msg=line[pos:], pri=pri, errors=(*errors, "no_header"))
            timestamp = self._bsd_timestamp(bm, errors)
            pos = bm.end()
        if line[pos : pos + 1] == " ":
            pos += 1

        hostname = None
        if line.startswith(": ", pos):
            pos += 2  # Cisco "Oct 09 2026 20:41:12: %ASA-..." puts a colon after the time
        elif not _TAG.match(line, pos):
            hm = _HOST.match(line, pos)
            if hm:
                hostname, pos = hm.group(1), hm.end()
                if line.startswith(": ", pos):
                    pos += 2  # Cisco device-id form "asa01 : %ASA-..."

        app_name = procid = None
        tag = _TAG.match(line, pos)
        if tag:
            app_name, procid, pos = tag.group(1), tag.group(2), tag.end()

        return Envelope(
            rfc="3164",
            msg=line[pos:],
            pri=pri,
            timestamp=timestamp,
            hostname=hostname,
            app_name=app_name,
            procid=procid,
            errors=tuple(errors),
        )

    # -- timestamps ------------------------------------------------------------------

    def _rfc3339(self, raw: str, errors: list[str], require_full: bool) -> datetime | None:
        m = _RFC3339.fullmatch(raw)
        if m is None or (require_full and m.group(8) is None):
            errors.append("invalid_timestamp")
            return None
        y, mo, d, h, mi, s = (int(m.group(i)) for i in range(1, 7))
        micro = int((m.group(7) or "0")[:6].ljust(6, "0"))
        zone = m.group(8)
        try:
            if zone is None:
                return self._localize(datetime(y, mo, d, h, mi, s, micro), errors)
            elif zone == "Z":
                local = datetime(y, mo, d, h, mi, s, micro, tzinfo=UTC)
            else:
                sign = 1 if zone[0] == "+" else -1
                offset = timedelta(hours=int(zone[1:3]), minutes=int(zone[4:6])) * sign
                local = datetime(y, mo, d, h, mi, s, micro, tzinfo=UTC) - offset
        except ValueError:
            errors.append("invalid_timestamp")
            return None
        return local.astimezone(UTC)

    def _bsd_timestamp(self, m: re.Match[str], errors: list[str]) -> datetime | None:
        month, day = _MONTHS[m.group(1)], int(m.group(2))
        h, mi, s = int(m.group(4)), int(m.group(5)), int(m.group(6))
        now_local = self._clock().astimezone(self._tz)
        year = int(m.group(3)) if m.group(3) else now_local.year
        micro = int((m.group(7) or "0").ljust(6, "0"))
        try:
            naive = datetime(year, month, day, h, mi, s, micro)
            if (
                m.group(3) is None
                and self._cfg.assume_year == "rollover_safe"
                and naive > now_local.replace(tzinfo=None) + timedelta(days=_ROLLOVER_FUTURE_DAYS)
            ):
                naive = naive.replace(year=year - 1)
        except ValueError:
            errors.append("invalid_timestamp")
            return None
        return self._localize(naive, errors)

    def _localize(self, naive: datetime, errors: list[str]) -> datetime:
        """A wall-clock time in the source's zone, in UTC (`app.core.localtime`)."""
        out, note = localize(naive, self._tz, self._clock(), self._last)
        if note is not None:
            errors.append(note)
        self._last = out
        return out


# -- helpers ---------------------------------------------------------------------------


def _nil(value: str) -> str | None:
    return None if value == "-" else value


def _valid_pri(value: int, errors: list[str]) -> int | None:
    if value > 191:
        errors.append("invalid_pri")
        return None
    return value


def _is_real_header(env: Envelope) -> bool:
    """A relayed inner header must look like a complete syslog header, not a date in prose."""
    if env.rfc == "none" or env.timestamp is None:
        return False
    if env.rfc == "5424":
        return True
    # A relay-added 3164 header carries a PRI, or a host and a tag. "20:42:00.456 UTC:"
    # inside a Cisco message has a tag-like word but no host, and is not a header.
    return env.pri is not None or (env.hostname is not None and env.app_name is not None)


def _parse_structured_data(
    rest: str, errors: list[str]
) -> tuple[dict[str, dict[str, str]] | None, str]:
    """Parse RFC 5424 STRUCTURED-DATA. Returns (sd, msg). Linear time."""
    if rest == "" or rest.startswith("-"):
        msg = rest[1:]
        return None, msg[1:] if msg.startswith(" ") else msg
    if not rest.startswith("["):
        errors.append("invalid_structured_data")
        return None, rest

    sd: dict[str, dict[str, str]] = {}
    i, n = 0, len(rest)
    while i < n and rest[i] == "[":
        i += 1
        start = i
        while i < n and rest[i] not in ' ]="':
            i += 1
        sd_id = rest[start:i]
        if not sd_id:
            errors.append("invalid_structured_data")
            return sd or None, rest[i:]
        params: dict[str, str] = {}
        while i < n and rest[i] == " ":
            i += 1
            start = i
            while i < n and rest[i] not in ' ]="':
                i += 1
            name = rest[start:i]
            if not name or rest[i : i + 2] != '="':
                errors.append(
                    "unterminated_structured_data" if i >= n else "invalid_structured_data"
                )
                return sd or None, ""
            i += 2
            value: list[str] = []
            closed = False
            while i < n:
                ch = rest[i]
                if ch == "\\" and i + 1 < n and rest[i + 1] in '"\\]':
                    value.append(rest[i + 1])
                    i += 2
                    continue
                if ch == '"':
                    closed = True
                    i += 1
                    break
                value.append(ch)
                i += 1
            if not closed:
                errors.append("unterminated_structured_data")
                return sd or None, ""
            params[name] = "".join(value)
        if i >= n or rest[i] != "]":
            errors.append("unterminated_structured_data" if i >= n else "invalid_structured_data")
            return sd or None, ""
        i += 1
        sd[sd_id] = params
    msg = rest[i:]
    return sd, msg[1:] if msg.startswith(" ") else msg
