"""Which code is running: the package version plus the commit it was built from.

The About page shows "0.3.0+1a2b3c4" so an administrator can tell exactly what is
installed. A git checkout (systemd and single-user installs) is read directly, without
running git; a container image carries a BUILD_COMMIT file written at build time.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

HEX = re.compile(r"^[0-9a-f]{7,40}$")


def _ref_commit(git: Path, ref: str) -> str | None:
    loose = git / ref
    if loose.is_file():
        return loose.read_text().strip()
    packed = git / "packed-refs"
    if packed.is_file():
        for line in packed.read_text().splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] == ref:
                return parts[0]
    return None


def commit_of(start: Path) -> str | None:
    """The short commit for the install holding `start`, or None when unknown."""
    for folder in [start, *start.parents]:
        stamp = folder / "BUILD_COMMIT"
        git = folder / ".git"
        try:
            if stamp.is_file():
                stamped = stamp.read_text().strip().lower()
                return stamped[:7] if HEX.match(stamped) else None
            if git.is_dir():
                head = (git / "HEAD").read_text().strip()
                value = _ref_commit(git, head[5:]) if head.startswith("ref: ") else head
                return value[:7] if value and HEX.match(value) else None
        except OSError:
            return None
    return None


@cache
def build_commit() -> str | None:
    return commit_of(Path(__file__).resolve().parent)


def full_version(package_version: str) -> str:
    commit = build_commit()
    return f"{package_version}+{commit}" if commit else package_version
