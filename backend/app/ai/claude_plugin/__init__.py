"""The observe-only hooks plugin (ADR-0026), packed per source with its server address,
token, content choice, and pilot list. The files next to this module are the plugin as
shipped; they are read, never changed, and written into the zip as they are."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

HERE = Path(__file__).parent
FILES = (".claude-plugin/plugin.json", "hooks/hooks.json", "hooks/send.sh")
VERSION = str(json.loads((HERE / ".claude-plugin" / "plugin.json").read_text())["version"])
SCRIPT_SHA256 = hashlib.sha256((HERE / "hooks" / "send.sh").read_bytes()).hexdigest()
_STAMP = (2026, 1, 1, 0, 0, 0)  # fixed zip times: the same inputs give the same file


def config_text(url: str, token: str, send_content: bool, pilot: list[str]) -> str:
    """The plugin's config: key=value lines the script reads as data, never runs."""
    for value in (url, token, *pilot):
        if any(c in value for c in "\r\n=") or not value.isprintable():
            raise ValueError("config values cannot hold line breaks or =")
    return (
        f"REMNANT_URL={url}\n"
        f"REMNANT_TOKEN={token}\n"
        f"SEND_CONTENT={1 if send_content else 0}\n"
        f"PILOT_USERS={' '.join(pilot)}\n"
    )


def build_zip(url: str, token: str, send_content: bool, pilot: list[str]) -> bytes:
    """The plugin folder as a zip, ready to upload in the admin console or unpack."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name in FILES:
            info = zipfile.ZipInfo(name, date_time=_STAMP)
            mode = 0o755 if name.endswith(".sh") else 0o644
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, (HERE / name).read_bytes())
        info = zipfile.ZipInfo("config", date_time=_STAMP)
        info.external_attr = (0o100000 | 0o600) << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(info, config_text(url, token, send_content, pilot))
    return buf.getvalue()
