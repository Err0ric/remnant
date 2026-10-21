"""key=value payloads (Fortinet, UniFi, many appliances).

Values may be quoted; inside quotes a backslash escapes the quote character and itself.
Tokens without a separator are kept under `_unparsed` and mark the result partial.
"""

import re

from app.ingest.payload.base import PayloadResult

MAX_PAIRS = 500
_KEY = re.compile(r"[A-Za-z0-9_.\-:@\[\]]{1,128}")


class KvParser:
    def __init__(self, pair_sep: str = " ", kv_sep: str = "=", quote: str | None = '"') -> None:
        if not pair_sep or not kv_sep or pair_sep == kv_sep:
            raise ValueError("kv needs distinct, non-empty pair and key-value separators")
        if quote is not None and len(quote) != 1:
            raise ValueError("kv quote must be one character")
        self._pair = pair_sep
        self._kv = kv_sep
        self._quote = quote

    def _is_sep(self, text: str, i: int) -> int:
        """Length of the pair separator at i, or 0. A space separator matches any run of
        whitespace, since devices pad fields inconsistently."""
        if self._pair == " ":
            j = i
            while j < len(text) and text[j] in " \t":
                j += 1
            return j - i
        return len(self._pair) if text.startswith(self._pair, i) else 0

    def parse(self, text: str) -> PayloadResult:
        fields: dict[str, str] = {}
        stray: list[str] = []
        i, n = 0, len(text)
        while i < n:
            i += self._is_sep(text, i)
            if i >= n:
                break
            j = i
            while j < n and not text.startswith(self._kv, j) and not self._is_sep(text, j):
                j += 1
            key = text[i:j]
            if j >= n or not text.startswith(self._kv, j) or not _KEY.fullmatch(key):
                end = j
                while end < n and not self._is_sep(text, end):
                    end += 1
                stray.append(text[i:end])
                i = end
                continue
            j += len(self._kv)
            if self._quote is not None and j < n and text[j] == self._quote:
                value, j, closed = _quoted(text, j + 1, self._quote)
                if not closed:
                    stray.append(f"{key}=<unterminated quote>")
            else:
                k = j
                while k < n and not self._is_sep(text, k):
                    k += 1
                value, j = text[j:k], k
            fields[key] = value
            i = j
            if len(fields) >= MAX_PAIRS:
                stray.append("<more pairs dropped>")
                break
        result = PayloadResult(dict(fields), partial=bool(stray))
        if stray:
            result.fields["_unparsed"] = " ".join(stray)[:2000]
        if not fields:
            result.error = "no key=value pairs found"
        return result


def _quoted(text: str, i: int, quote: str) -> tuple[str, int, bool]:
    out: list[str] = []
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n and text[i + 1] in (quote, "\\"):
            out.append(text[i + 1])
            i += 2
            continue
        if c == quote:
            return "".join(out), i + 1, True
        out.append(c)
        i += 1
    return "".join(out), n, False
