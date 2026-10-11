"""YAML loading for files and uploads people provide (templates, tables, saved searches).

`yaml.safe_load` blocks Python object tags but still expands aliases, so a few hundred bytes
of nested anchors (a "billion laughs" document) can grow into gigabytes once anything walks
or prints the result. Nothing here needs anchors, so documents that use them are refused,
and so is nesting deeper than any real document needs. Every failure is a YAMLError, so
callers handle bad input in one place.
"""

from typing import Any

import yaml
from yaml.events import AliasEvent

MAX_DEPTH = 64


class _NoAliasLoader(yaml.SafeLoader):
    _depth = 0

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(AliasEvent):
            raise yaml.composer.ComposerError(None, None, "YAML aliases (*name) are not allowed")
        self._depth += 1
        try:
            if self._depth > MAX_DEPTH:
                raise yaml.composer.ComposerError(
                    None, None, f"YAML nested deeper than {MAX_DEPTH} levels"
                )
            return super().compose_node(parent, index)
        finally:
            self._depth -= 1


def load(text: str) -> Any:
    """Parse one YAML document safely: no object tags, no aliases, bounded nesting."""
    try:
        return yaml.load(text, Loader=_NoAliasLoader)  # noqa: S506  # subclasses SafeLoader
    except yaml.YAMLError:
        raise
    except (ValueError, RecursionError, OverflowError) as exc:
        # Scalars the resolver cannot build (a 5,000-digit int, 2026-02-30) and anything
        # too deep for the parser itself.
        raise yaml.YAMLError(f"YAML value not accepted: {type(exc).__name__}") from exc
