"""Regex payloads: the first pattern that matches wins; named groups become fields.

Patterns are compiled with the `regex` module and every match has a time limit (CLAUDE.md
security rule 5), so a pathological line cannot stall ingest.
"""

import regex

from app.ingest.payload.base import PayloadResult

MATCH_TIMEOUT_S = 0.05


def compile_patterns(patterns: list[str]) -> list[regex.Pattern[str]]:
    """Compile template patterns; raises ValueError with the index of a bad one."""
    compiled = []
    for i, p in enumerate(patterns):
        try:
            c = regex.compile(p)
        except regex.error as exc:
            raise ValueError(f"pattern {i + 1}: {exc}") from exc
        if not c.groupindex:
            raise ValueError(f"pattern {i + 1} has no named groups")
        compiled.append(c)
    return compiled


class RegexParser:
    def __init__(self, patterns: list[str], timeout_s: float = MATCH_TIMEOUT_S) -> None:
        if not patterns:
            raise ValueError("regex needs at least one pattern")
        self._patterns = compile_patterns(patterns)
        self._timeout = timeout_s

    def parse(self, text: str) -> PayloadResult:
        for p in self._patterns:
            try:
                m = p.search(text, timeout=self._timeout)
            except TimeoutError:
                return PayloadResult(error="regex timed out")
            if m:
                return PayloadResult({k: v for k, v in m.groupdict().items() if v is not None})
        return PayloadResult(error="no pattern matched")


class PlainParser:
    """No structure: the payload is the message."""

    def parse(self, text: str) -> PayloadResult:
        return PayloadResult({"message": text})
