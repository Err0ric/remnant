"""Which sources a Sigma rule runs on (ADR-0006 row 2).

A template declares the Sigma logsources its events can satisfy. A rule applies to a
template when one declared entry has every field the rule names, with the same value.
The entry may be more specific than the rule: a rule for `product: windows` applies to a
template declaring `{product: windows, service: security}`, but a rule for
`{product: windows, service: security}` does not apply to a template declaring only
`{product: windows}`. A declared `*` (service or category only) stands for any value, so
a Windows template can take every service or category. A rule naming no product, service,
or category applies to nothing.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

FIELDS = ("product", "service", "category")
ANY = "*"


@dataclass(frozen=True, slots=True)
class LogSource:
    product: str | None = None
    service: str | None = None
    category: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, object] | None) -> "LogSource":
        """From a rule's `logsource:` block; other keys (definition) are ignored."""
        value = value or {}
        parts: dict[str, str | None] = {}
        for name in FIELDS:
            v = value.get(name)
            parts[name] = v.strip().lower() if isinstance(v, str) and v.strip() else None
        return cls(**parts)

    def is_empty(self) -> bool:
        return self.product is None and self.service is None and self.category is None

    def label(self) -> str:
        return " / ".join(f"{n}: {getattr(self, n)}" for n in FIELDS if getattr(self, n))


def applies(rule: LogSource, declared: Iterable[LogSource]) -> bool:
    """True when the rule's logsource is satisfied by any declared entry."""
    if rule.is_empty():
        return False
    wanted = [(n, getattr(rule, n)) for n in FIELDS if getattr(rule, n) is not None]
    return any(
        all(
            getattr(entry, n) == v or (n != "product" and getattr(entry, n) == ANY)
            for n, v in wanted
        )
        for entry in declared
    )
