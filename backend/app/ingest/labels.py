"""Loki stream labels as a syslog envelope (install finding 10).

A syslog receiver in front of Loki often strips the header and turns its parts into
labels, so the line Loki returns is only the message. The labels then carry what the
header would have: host, program, process id, severity, facility. Automatic routing and
templates use this envelope as if it came from a header; the line itself is unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.ingest.envelope import Envelope

Part = str  # one of DEFAULT_LABEL_MAP's keys

# Checked in order; the first label present wins.
DEFAULT_LABEL_MAP: dict[Part, tuple[str, ...]] = {
    "hostname": ("hostname", "host"),
    "app_name": ("app_name", "appname", "program", "service_name"),
    "procid": ("proc_id", "pid"),
    "severity": ("severity", "level"),
    "facility": ("facility",),
}

_SEVERITY = {
    "emerg": 0, "emergency": 0, "panic": 0,
    "alert": 1,
    "crit": 2, "critical": 2, "fatal": 2,
    "err": 3, "error": 3,
    "warning": 4, "warn": 4,
    "notice": 5,
    "info": 6, "informational": 6,
    "debug": 7, "trace": 7,
}  # fmt: skip
_FACILITY = {
    "kern": 0, "user": 1, "mail": 2, "daemon": 3, "auth": 4, "syslog": 5, "lpr": 6,
    "news": 7, "uucp": 8, "cron": 9, "authpriv": 10, "ftp": 11, "ntp": 12, "security": 13,
    "console": 14, "solaris-cron": 15, "clock": 15,
    **{f"local{i}": 16 + i for i in range(8)},
}  # fmt: skip
USER_FACILITY = 1  # RFC 3164: the facility to assume when only a severity is known


def effective_map(overrides: Mapping[Any, Sequence[str]] | None) -> dict[Part, tuple[str, ...]]:
    """The default label map with any per-source overrides applied."""
    out = dict(DEFAULT_LABEL_MAP)
    for part, names in (overrides or {}).items():
        if part in out:
            out[part] = tuple(n for n in names if n)
    return out


def _first(labels: Mapping[str, str], names: Sequence[str]) -> str | None:
    for name in names:
        value = (labels.get(name) or "").strip()
        if value and value != "-":
            return value[:255]
    return None


def _number(value: str | None, names: Mapping[str, int], top: int) -> int | None:
    if value is None:
        return None
    if value.isdigit():
        n = int(value)
        return n if n <= top else None
    return names.get(value.lower())


def labels_envelope(
    labels: Mapping[str, str], label_map: Mapping[Any, Sequence[str]] | None = None
) -> Envelope | None:
    """An envelope from stream labels, or None when the labels name no host or program."""
    m = effective_map(label_map)
    hostname = _first(labels, m["hostname"])
    app_name = _first(labels, m["app_name"])
    if hostname is None and app_name is None:
        return None
    severity = _number(_first(labels, m["severity"]), _SEVERITY, 7)
    facility = _number(_first(labels, m["facility"]), _FACILITY, 23)
    pri = None
    if severity is not None:
        pri = (USER_FACILITY if facility is None else facility) * 8 + severity
    return Envelope(
        rfc="labels",
        msg="",
        pri=pri,
        hostname=hostname,
        app_name=app_name,
        procid=_first(labels, m["procid"]),
    )
