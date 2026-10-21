"""One-time setup link for the first administrator (ADR-0001 item 2).

32 random bytes, kept only as a SHA-256 in memory, single use, 30 minute expiry.
Issuing a new link (every restart) invalidates the previous one.
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

SETUP_TTL = timedelta(minutes=30)


class SetupLink:
    def __init__(self) -> None:
        self._digest: bytes | None = None
        self._expires: datetime | None = None

    def issue(self, now: datetime) -> str:
        token = secrets.token_urlsafe(32)
        self._digest = hashlib.sha256(token.encode()).digest()
        self._expires = now + SETUP_TTL
        return token

    def consume(self, token: str, now: datetime) -> bool:
        """True once for the current, unexpired token. Any later call is False."""
        if self._digest is None or self._expires is None or now >= self._expires:
            return False
        if not hmac.compare_digest(self._digest, hashlib.sha256(token.encode()).digest()):
            return False
        self._digest = None
        self._expires = None
        return True
