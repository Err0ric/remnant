"""JSON payloads, optionally after a prefix such as `@cee:`, with a root path.

The root is a small JSONPath subset: `$`, `.name`, `['name']`, `[index]`. The object at
the root becomes the fields; nested objects stay nested and mapping reads them with dotted
paths.
"""

import json
import re
from typing import Any

from app.ingest.payload.base import PayloadResult

_STEP = re.compile(r"\.([A-Za-z_@$][\w@$\-]*)|\['([^'\]]+)'\]|\[(\d+)\]")


def parse_root(path: str) -> list[str | int]:
    """Validate and split a root path; raises ValueError for anything unsupported."""
    if not path.startswith("$"):
        raise ValueError(f"JSON root must start with $: {path!r}")
    steps: list[str | int] = []
    i = 1
    while i < len(path):
        m = _STEP.match(path, i)
        if not m:
            raise ValueError(f"Unsupported JSON root syntax at {path[i:]!r}")
        name, quoted, index = m.groups()
        steps.append(int(index) if index is not None else (name or quoted))
        i = m.end()
    return steps


class JsonParser:
    def __init__(self, root: str = "$") -> None:
        self._steps = parse_root(root)

    def parse(self, text: str) -> PayloadResult:
        body = text.strip()
        if body.startswith("@cee:"):
            body = body[5:].lstrip()
        if not body.startswith(("{", "[")):
            brace = body.find("{")
            if brace < 0:
                return PayloadResult(error="no JSON object found")
            body = body[brace:]
        try:
            # NaN and Infinity are not JSON; keep them as the text the device sent.
            value: Any = json.loads(body, parse_constant=str)
        except (ValueError, RecursionError):
            return PayloadResult(error="invalid JSON")
        for step in self._steps:
            if isinstance(step, int) and isinstance(value, list) and step < len(value):
                value = value[step]
            elif isinstance(step, str) and isinstance(value, dict) and step in value:
                value = value[step]
            else:
                return PayloadResult(error=f"JSON root not found at {step!r}")
        if not isinstance(value, dict):
            return PayloadResult(error="JSON root is not an object")
        return PayloadResult(value)
