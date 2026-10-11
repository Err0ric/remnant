"""ArcSight Common Event Format.

CEF:Version|Device Vendor|Device Product|Device Version|Signature ID|Name|Severity|Extension

Header fields escape `|` and `\\` with a backslash. Extension values escape `=`, `\\`,
and use `\\n` / `\\r` for line breaks; a value runs until the next ` key=`.
"""

import re

from app.ingest.payload.base import PayloadResult

HEADER = (
    "cef_version",
    "device_vendor",
    "device_product",
    "device_version",
    "signature_id",
    "name",
    "severity",
)
_EXT_KEY = re.compile(r"(?:^|(?<=\s))([A-Za-z0-9_.\-\[\]]{1,128})=")
_UNESCAPE = {"\\=": "=", "\\\\": "\\", "\\n": "\n", "\\r": "\r"}
_ESCAPED = re.compile(r"\\[=\\nr]")


class CefParser:
    def parse(self, text: str) -> PayloadResult:
        start = text.find("CEF:")
        if start < 0:
            return PayloadResult(error="no CEF: header")
        body = text[start + 4 :]
        parts: list[str] = []
        cur: list[str] = []
        i = 0
        while i < len(body) and len(parts) < len(HEADER):
            c = body[i]
            if c == "\\" and i + 1 < len(body) and body[i + 1] in "|\\":
                cur.append(body[i + 1])
                i += 2
                continue
            if c == "|":
                parts.append("".join(cur))
                cur = []
            else:
                cur.append(c)
            i += 1
        fields: dict[str, str] = dict(zip(HEADER, parts, strict=False))
        if len(parts) < len(HEADER):
            fields[HEADER[len(parts)]] = "".join(cur)
            return PayloadResult(fields, partial=True)
        fields.update(_extension(body[i:]))
        return PayloadResult(fields)


def _extension(ext: str) -> dict[str, str]:
    out: dict[str, str] = {}
    keys = list(_EXT_KEY.finditer(ext))
    for k, m in enumerate(keys):
        end = keys[k + 1].start() if k + 1 < len(keys) else len(ext)
        raw = ext[m.end() : end].rstrip(" ")
        out[m.group(1)] = _ESCAPED.sub(lambda e: _UNESCAPE[e.group(0)], raw)
    return out
