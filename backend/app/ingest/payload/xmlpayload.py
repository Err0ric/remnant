"""XML payloads (Windows event XML and similar), parsed with defusedxml.

DTDs, entities, and external references are refused, so no entity expansion or file and
network access can come from a log line. Fields are ElementTree paths relative to the
root, with an optional trailing `/@attribute` and a prefix-to-namespace map.
"""

from xml.etree.ElementTree import Element

import defusedxml.ElementTree as SafeET
from defusedxml import DefusedXmlException

from app.ingest.payload.base import PayloadResult


class XmlParser:
    def __init__(self, fields: dict[str, str], namespaces: dict[str, str] | None = None) -> None:
        if not fields:
            raise ValueError("xml needs at least one field path")
        self._fields = {name: _split(path) for name, path in fields.items()}
        self._ns = namespaces or {}
        probe = SafeET.fromstring("<r/>")
        for name, (path, _) in self._fields.items():
            try:
                probe.find(path, self._ns)
            # ElementTree reports bad paths as SyntaxError, or as TypeError or KeyError
            # from inside its path tokenizer.
            except (SyntaxError, TypeError, KeyError, ValueError) as exc:
                raise ValueError(f"xml field {name}: {exc}") from exc

    def parse(self, text: str) -> PayloadResult:
        start = text.find("<")
        if start < 0:
            return PayloadResult(error="no XML found")
        try:
            root: Element = SafeET.fromstring(
                text[start:], forbid_dtd=True, forbid_entities=True, forbid_external=True
            )
        except (SafeET.ParseError, DefusedXmlException, ValueError) as exc:
            return PayloadResult(error=f"xml: {type(exc).__name__}")
        fields: dict[str, str | None] = {}
        for name, (path, attr) in self._fields.items():
            node = root if path == "." else root.find(path, self._ns)
            if node is None:
                fields[name] = None
            elif attr is not None:
                fields[name] = node.get(attr)
            else:
                fields[name] = (node.text or "").strip() or None
        return PayloadResult(fields)


def _split(path: str) -> tuple[str, str | None]:
    path = path.strip().lstrip("/") or "."
    if "/@" in path:
        element, attr = path.rsplit("/@", 1)
        return element or ".", attr
    if path.startswith("@"):
        return ".", path[1:]
    return path, None
