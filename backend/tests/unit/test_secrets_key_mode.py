"""The install key's file is only chmod-ed when its mode is wrong (owner, 2026-11-01): a
chmod on every start changed its ctime, so file integrity monitoring reported it."""

import time
from pathlib import Path

from app.meta.secrets import SecretBox


def test_the_key_file_is_left_alone_when_its_mode_is_right(tmp_path: Path) -> None:
    SecretBox(tmp_path).encrypt("x")
    key = tmp_path / ".key"
    before = key.stat().st_ctime_ns
    time.sleep(0.05)
    SecretBox(tmp_path).encrypt("y")  # a restart
    assert key.stat().st_ctime_ns == before
    key.chmod(0o644)  # loosened by someone
    SecretBox(tmp_path).encrypt("z")
    assert key.stat().st_mode & 0o777 == 0o600
