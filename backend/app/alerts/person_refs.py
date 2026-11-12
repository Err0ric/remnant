"""People in stored AI Watch alert text (D242, ADR-0029 C6).

An AI Watch item stores no name in its subject, ref id, title, detail, why, or change
lines: each name is a reference `{p:<digest>}`, the digest an HMAC-SHA256 of the name with
a key derived from the install key (`data/.key`), so one person is always the same
reference across restarts and the item's subject still keys its dedup, group, and mute.
Each reference is of one exact spelling, and that spelling is kept in the item's `people`
field; where references go is app.ai.alert_codes. Reading the item puts each name back
from its people, byte for byte; a reference to no one in them reads "a person".
"""

import hashlib
import hmac
import re
import secrets
from collections.abc import Callable, Iterable

A_PERSON = "a person"
REF = re.compile(r"\{p:[0-9a-f]{16}\}")


class PersonRefs:
    def __init__(self, install_key: Callable[[], bytes] | None = None) -> None:
        # Without the install key (unit tests), a key for this process only.
        own = secrets.token_bytes(32)
        self._install_key = install_key or (lambda: own)
        self._key: bytes | None = None
        self._seen: dict[str, str] = {}

    def ref(self, name: str) -> str:
        if self._key is None:
            self._key = hmac.new(self._install_key(), b"alert-people-v1", hashlib.sha256).digest()
        if name not in self._seen:
            if len(self._seen) >= 10_000:
                self._seen.clear()
            digest = hmac.new(self._key, name.encode(), hashlib.sha256).hexdigest()[:16]
            self._seen[name] = "{p:" + digest + "}"
        return self._seen[name]

    def known(self, people: Iterable[str]) -> dict[str, str]:
        """Each of `people` by its reference, for `render`."""
        return {self.ref(p): p for p in people}

    @staticmethod
    def render(text: str | None, known: dict[str, str]) -> str | None:
        """`text` with each reference back as the name it stands for (`known`)."""
        if text is None or "{p:" not in text:
            return text
        return REF.sub(lambda m: known.get(m.group(0), A_PERSON), text)
