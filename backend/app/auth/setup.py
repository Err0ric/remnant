"""One-time setup link for the first administrator (ADR-0001 item 2, D245).

32 random bytes, kept only as a SHA-256, single use, 30 minute expiry. Issuing a new link
(every restart, or `app-admin setup-link` on the server) invalidates the previous one. The
hash is kept in `meta.sqlite`, so the command on the server and the running server share it.
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from app.core.config import AppConfig, is_loopback_host
from app.meta.db import MetaDB

SETUP_TTL = timedelta(minutes=30)
COMMAND = "app-admin setup-link"


class SetupLink:
    def __init__(self, meta: MetaDB) -> None:
        self._meta = meta

    def issue(self, now: datetime) -> str:
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self._meta.connect() as con:
            con.execute(
                "INSERT INTO setup_link (id, digest, expires_at) VALUES (1, ?, ?)"
                " ON CONFLICT (id) DO UPDATE SET digest = excluded.digest,"
                " expires_at = excluded.expires_at",
                (digest, (now + SETUP_TTL).isoformat()),
            )
        return token

    def consume(self, token: str, now: datetime) -> bool:
        """True once for the current, unexpired token. Any later call is False."""
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self._meta.connect() as con:
            row = con.execute("SELECT digest, expires_at FROM setup_link WHERE id = 1").fetchone()
            if row is None or now >= datetime.fromisoformat(row["expires_at"]):
                return False
            if not hmac.compare_digest(row["digest"], digest):
                return False
            # Single use also when two requests race: only one of them removes the row.
            gone = con.execute("DELETE FROM setup_link WHERE id = 1 AND digest = ?", (digest,))
            return gone.rowcount == 1


def link_url(token: str, host: str, port: int, base: str | None, loopback: bool) -> str:
    """The token sits in the fragment, never in a request line. `base` (server.public_url)
    wins when set, so the link works through a reverse proxy."""
    if base:
        return f"{base.rstrip('/')}/setup#{token}"
    return f"{'http' if loopback else 'https'}://{host}:{port}/setup#{token}"


def link_host(config: AppConfig, hostname: str) -> str:
    """The host a setup link names when no public URL is set: the bind address on a
    loopback install (only this machine can open it), else the first public name."""
    host = config.server.host
    if is_loopback_host(host):
        return f"[{host}]" if ":" in host else host
    return config.server.public_names[0] if config.server.public_names else hostname


def notice(config: AppConfig, url: str) -> list[str]:
    """What the server log and `app-admin setup-link` print with a fresh link."""
    lines = [
        "No administrator account exists yet. Open this one-time link to create it:",
        f"  {url}",
        f"The link works once and expires in 30 minutes. For a new one run: {COMMAND}",
    ]
    if config.server.public_url:
        return lines
    port = config.server.port
    if is_loopback_host(config.server.host):
        lines.append(
            "This link opens on this machine only. From another computer, open an SSH tunnel"
            f" there first (ssh -L {port}:{link_host(config, '')}:{port} <this server>), then open"
            " the link in that computer's browser."
        )
    lines.append(
        "Behind a reverse proxy? Set APP_PUBLIC_NAME and APP_PUBLIC_URL (systemd:"
        " APP__SERVER__PUBLIC_NAMES and APP__SERVER__PUBLIC_URL) to the name and address"
        " people open, then restart, so this link goes through it."
    )
    return lines
