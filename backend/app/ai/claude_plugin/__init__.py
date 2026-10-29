"""The observe-only hooks plugins (ADR-0026, amendment 2026-10-29): one per platform,
packed per source with its server address, token, content choice, pilot list, and
optionally this server's own certificate. The folders next to this module are the plugins
as shipped; their files are read, never changed, and written into the zip as they are.

`managed=True` instead returns a bundle for endpoint management: the plugin with an empty
config, and the machine-wide `hooks.conf` (which wins over the plugin's own copy) holding
the address and token, with a README on where it goes."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Literal

HERE = Path(__file__).parent
Platform = Literal["windows", "posix"]
SCRIPTS: dict[str, str] = {"windows": "hooks/send.ps1", "posix": "hooks/send.sh"}
LABELS: dict[str, str] = {"windows": "Windows", "posix": "macOS and Linux"}
VERSION = str(
    json.loads((HERE / "posix" / ".claude-plugin" / "plugin.json").read_text())["version"]
)
SCRIPT_SHA256: dict[str, str] = {
    p: hashlib.sha256((HERE / p / s).read_bytes()).hexdigest() for p, s in SCRIPTS.items()
}
CA_NAME = "server-ca.pem"  # this server's self-signed certificate, when bundled
MACHINE_CONF: dict[str, str] = {
    "windows": r"%ProgramData%\siem-claude-hooks\hooks.conf",
    "macos": "/Library/Application Support/siem-claude-hooks/hooks.conf",
    "linux": "/etc/siem-claude-hooks/hooks.conf",
}
_STAMP = (2026, 1, 1, 0, 0, 0)  # fixed zip times: the same inputs give the same file


def files(platform: str) -> tuple[str, ...]:
    return (".claude-plugin/plugin.json", "hooks/hooks.json", SCRIPTS[platform])


def _check(*values: str) -> None:
    for value in values:
        if any(c in value for c in "\r\n=") or not value.isprintable():
            raise ValueError("config values cannot hold line breaks or =")


def config_text(
    url: str, token: str, send_content: bool, pilot: list[str], ca_file: str = ""
) -> str:
    """A config: key=value lines the scripts read as data, never run. `ca_file` relative
    to the plugin folder (the bundled certificate) or an absolute path on the machine."""
    _check(url, token, ca_file, *pilot)
    text = (
        f"REMNANT_URL={url}\n"
        f"REMNANT_TOKEN={token}\n"
        f"SEND_CONTENT={1 if send_content else 0}\n"
        f"PILOT_USERS={' '.join(pilot)}\n"
    )
    return text + (f"CA_FILE={ca_file}\n" if ca_file else "")


def _add(z: zipfile.ZipFile, name: str, data: bytes, mode: int) -> None:
    info = zipfile.ZipInfo(name, date_time=_STAMP)
    info.external_attr = (0o100000 | mode) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    z.writestr(info, data)


def build_zip(
    url: str,
    token: str,
    send_content: bool,
    pilot: list[str],
    platform: str = "posix",
    ca_pem: bytes | None = None,
    config: str | None = None,
) -> bytes:
    """One platform's plugin folder as a zip, ready to upload in the admin console."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name in files(platform):
            mode = 0o755 if name.endswith((".sh", ".ps1")) else 0o644
            _add(z, name, (HERE / platform / name).read_bytes(), mode)
        if ca_pem:
            _add(z, CA_NAME, ca_pem, 0o644)
        if config is None:
            config = config_text(url, token, send_content, pilot, CA_NAME if ca_pem else "")
        _add(z, "config", config.encode(), 0o600)
    return buf.getvalue()


def build_managed(
    url: str,
    token: str,
    send_content: bool,
    pilot: list[str],
    platform: str,
    ca_pem: bytes | None = None,
) -> bytes:
    """A bundle for endpoint management: the plugin (its own config empty, so a machine
    without the managed file sends nothing), the machine-wide `hooks.conf`, the
    certificate when bundled, and a README naming where each goes."""
    ca_path = ""
    if ca_pem:
        ca_path = (
            "C:\\ProgramData\\siem-claude-hooks\\server-ca.pem"
            if platform == "windows"
            else "/etc/siem-claude-hooks/server-ca.pem"
        )
    conf = config_text(url, token, send_content, pilot, ca_path)
    plugin = build_zip("", "", False, [], platform, config="")
    where = (
        f"Windows: {MACHINE_CONF['windows']}"
        if platform == "windows"
        else f"macOS: {MACHINE_CONF['macos']}\nLinux: {MACHINE_CONF['linux']}"
    )
    readme = f"""Claude hooks plugin ({LABELS[platform]}), version {VERSION}

1. Upload plugin-{platform}.zip in Claude: Organization settings > Plugins & skills.
   Its own config is empty: it sends only where the managed file below is deployed.
2. Deploy hooks.conf with your endpoint management tool to:
{where}
   Administrators (or root) write it; users read it. It holds the source token.
{"3. Deploy server-ca.pem next to it (CA_FILE in hooks.conf names that path)." if ca_pem else ""}

Script SHA-256 ({SCRIPTS[platform]}): {SCRIPT_SHA256[platform]}
"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        _add(z, f"plugin-{platform}.zip", plugin, 0o644)
        _add(z, "hooks.conf", conf.encode(), 0o600)
        if ca_pem:
            _add(z, CA_NAME, ca_pem, 0o644)
        _add(z, "README.txt", readme.encode(), 0o644)
    return buf.getvalue()
