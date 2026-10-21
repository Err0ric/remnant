"""Payload parser contract (CLAUDE.md rule 8): one class per format, one public method.

A parser turns the payload text (the line after any syslog envelope) into named fields.
It never raises on bad input: log content is hostile, so failures come back as an error
string and the event is stored with whatever was parsed and its raw line intact.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class PayloadResult:
    fields: dict[str, Any] = field(default_factory=dict)
    error: str | None = None  # set when nothing usable was parsed
    partial: bool = False  # parsed, but something was left over or missing

    @property
    def ok(self) -> bool:
        return self.error is None


class PayloadParser(Protocol):
    def parse(self, text: str) -> PayloadResult: ...
