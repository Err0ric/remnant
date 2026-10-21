"""Secrets at rest (CLAUDE.md section 4): encrypted with a key in <data_dir>/.key (0600).

Used for provider API keys now and connector credentials later. Plain values never go
to YAML, logs, audit detail, API responses, or prompts.
"""

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

KEY_NAME = ".key"


class SecretBox:
    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / KEY_NAME
        self._fernet: Fernet | None = None

    def _key(self) -> Fernet:
        if self._fernet is None:
            if not self._path.exists():
                self._path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as fh:
                    fh.write(Fernet.generate_key())
            os.chmod(self._path, 0o600)  # tighten if someone loosened it
            self._fernet = Fernet(self._path.read_bytes().strip())
        return self._fernet

    def install_key(self) -> bytes:
        """The raw install key, for deriving other keys (redaction tokens). Never logged."""
        self._key()  # created on first use
        return self._path.read_bytes().strip()

    def encrypt(self, plain: str) -> str:
        return self._key().encrypt(plain.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._key().decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("Stored secret cannot be decrypted with this install's key") from exc
