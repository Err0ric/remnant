"""IBM Log Event Extended Format, versions 1.0 and 2.0.

LEEF:1.0|Vendor|Product|Version|EventID|k=v<TAB>k=v
LEEF:2.0|Vendor|Product|Version|EventID|Delimiter|k=v<D>k=v

The 2.0 delimiter is one character or a hex code (x09, 0x5E). When that slot does not
look like a delimiter it is treated as the start of the attributes, with a tab delimiter.
"""

import re

from app.ingest.payload.base import PayloadResult

_HEX = re.compile(r"(?:0x|x)([0-9A-Fa-f]{2})")


class LeefParser:
    def parse(self, text: str) -> PayloadResult:
        start = text.find("LEEF:")
        if start < 0:
            return PayloadResult(error="no LEEF: header")
        body = text[start + 5 :]
        version = body.split("|", 1)[0]
        if version.startswith("1"):
            parts = body.split("|", 5)
            delim, attrs = "\t", parts[5] if len(parts) > 5 else ""
        elif version.startswith("2"):
            parts = body.split("|", 6)
            delim, attrs = "\t", ""
            if len(parts) > 6:
                slot = parts[5]
                parsed = _delimiter(slot)
                if parsed is None:
                    attrs = slot + "|" + parts[6]
                else:
                    delim, attrs = parsed, parts[6]
            elif len(parts) == 6:
                attrs = parts[5]
        else:
            return PayloadResult(error=f"unsupported LEEF version {version[:10]!r}")
        header = ("leef_version", "vendor", "product", "product_version", "event_id")
        fields: dict[str, str] = dict(zip(header, parts, strict=False))
        if len(parts) < len(header):
            return PayloadResult(fields, partial=True)
        stray: list[str] = []
        for item in attrs.split(delim):
            if not item:
                continue
            key, sep, value = item.partition("=")
            if sep and key.strip():
                fields[key.strip()] = value
            else:
                stray.append(item)
        result = PayloadResult(fields, partial=bool(stray))
        if stray:
            result.fields["_unparsed"] = delim.join(stray)[:2000]
        return result


def _delimiter(slot: str) -> str | None:
    if len(slot) == 1:
        return slot
    m = _HEX.fullmatch(slot)
    return chr(int(m.group(1), 16)) if m else None
