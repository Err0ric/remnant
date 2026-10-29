"""Sensitive-data signals for detective DLP (ADR-0015 row 13).

Scans text a person sent to an AI tool (prompt, tool input) and returns categories and
counts only; the text itself is never returned or stored by this module. Patterns are
linear-time regular expressions over at most MAX_SCAN characters per value.
"""

import re

MAX_SCAN = 64 * 1024

_PATTERNS: dict[str, re.Pattern[str]] = {
    "us_ssn": re.compile(r"(?<!\d)(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?!\d)"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "github_token": re.compile(
        r"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{22,255})\b"
    ),
    "slack_token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,200}\b"),
    "anthropic_key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,200}"),
    "openai_key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{20,200}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    "jwt": re.compile(
        r"\beyJ[A-Za-z0-9_-]{8,2000}\.eyJ[A-Za-z0-9_-]{8,4000}\.[A-Za-z0-9_-]{8,2000}"
    ),
    "password_assignment": re.compile(
        r"(?i)\b(?:password|passwd|pwd|secret)\s*[:=]\s*[\"']?[^\s\"']{6,200}"
    ),
}
_CARD = re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])")


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = ord(ch) - 48
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def scan(*texts: object) -> dict[str, int]:
    """Counts per category across `texts` (non-strings are ignored)."""
    found: dict[str, int] = {}
    for text in texts:
        if not isinstance(text, str) or not text:
            continue
        # Head and tail: a long paste (a .env, a log) often ends with the secret (QA F2).
        chunk = (
            text
            if len(text) <= MAX_SCAN
            else text[: MAX_SCAN * 3 // 4] + "\n" + text[-MAX_SCAN // 4 :]
        )
        for name, pattern in _PATTERNS.items():
            n = sum(1 for _ in pattern.finditer(chunk))
            if n:
                found[name] = found.get(name, 0) + n
        cards = 0
        for m in _CARD.finditer(chunk):
            digits = re.sub(r"[ -]", "", m.group(0))
            if 13 <= len(digits) <= 19 and _luhn(digits) and len(set(digits)) > 1:
                cards += 1
        if cards:
            found["payment_card"] = found.get("payment_card", 0) + cards
    return found


def mask(text: str) -> str:
    """`text` with every detected secret replaced by `[redacted:<category>]`, for content a
    source keeps (ADR-0026 amendment 2026-10-29 row 5). The counts come from `scan`, run
    before this on the full text."""
    for name, pattern in _PATTERNS.items():
        text = pattern.sub(f"[redacted:{name}]", text)

    def card(m: re.Match[str]) -> str:
        digits = re.sub(r"[ -]", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits) and len(set(digits)) > 1:
            return "[redacted:payment_card]"
        return m.group(0)

    return _CARD.sub(card, text)
