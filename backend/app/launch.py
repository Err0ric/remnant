"""`app-server` entry point: check the service can read its own install, then start.

An update run with a strict umask (077) leaves code, packages, or the web UI readable by
root only; the service user then fails with a long traceback (F50). This module imports
only the standard library, so it can say what is wrong in one line before anything else
is loaded.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

FIX = "chmod -R a+rX {root} (scripts/update-systemd.sh does this on every update)"


def unreadable(roots: list[Path], limit: int = 1) -> list[Path]:
    """Files or folders under `roots` this process cannot read (folders: cannot list)."""
    found: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if not os.access(root, os.R_OK | (os.X_OK if root.is_dir() else 0)):
            found.append(root)
            if len(found) >= limit:
                return found
            continue
        for here, dirs, files in os.walk(root, onerror=lambda e: found.append(Path(e.filename))):
            base = Path(here)
            for d in list(dirs):
                if not os.access(base / d, os.R_OK | os.X_OK):
                    found.append(base / d)
                    dirs.remove(d)
            for f in files:
                p = base / f
                if not p.is_symlink() and not os.access(p, os.R_OK):
                    found.append(p)
            if len(found) >= limit:
                return found[:limit]
    return found[:limit]


def install_roots() -> list[Path]:
    """The app's code and its Python packages, plus the Python itself when it was
    installed inside the same folder (UV_PYTHON_INSTALL_DIR=/opt/remnant/.python). The web
    UI folder comes from the config, so `app.main` checks it after loading the config."""
    code = Path(__file__).resolve().parent
    roots = [code, Path(sys.prefix)]
    base = Path(sys.base_prefix).resolve()
    if base != Path(sys.prefix).resolve() and install_root(code) in base.parents:
        roots.append(base)
    return roots


def install_root(path: Path) -> Path:
    """The folder to fix: the checkout above the code (/opt/remnant), else the path."""
    for parent in [path, *path.parents]:
        if (parent / "backend").is_dir() and (parent / "frontend").is_dir():
            return parent
    return path


def check() -> str | None:
    bad = unreadable(install_roots())
    if not bad:
        return None
    return message_for(bad[0])


def message_for(path: Path) -> str:
    import pwd

    user = pwd.getpwuid(os.getuid()).pw_name
    root = install_root(path)
    return (
        f"error: user {user} cannot read {path}: files in the install folder are readable"
        f" only by their owner (an update run with umask 077?). Fix: {FIX.format(root=root)}"
    )


def run() -> None:
    message = check()
    if message:
        print(message, file=sys.stderr, flush=True)
        raise SystemExit(78)  # EX_CONFIG: systemd's Restart=on-failure retries, same line
    from app.main import run as serve

    serve()
