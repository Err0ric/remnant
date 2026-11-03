"""Owner 2026-11-02: a plugin download carries a one-step installer for one machine
(install-local.ps1 or install-local.sh) that builds a local marketplace from the unzipped
plugin and installs it for the user with the Claude Code CLI."""

import io
import json
import os
import stat
import subprocess
import zipfile
from pathlib import Path

from app.ai.claude_plugin import LOCAL_MARKETPLACE, build_managed, build_zip

URL, TOKEN = "https://siem.example.internal", "rmt_test0000"


def _names(data: bytes) -> list[str]:
    return zipfile.ZipFile(io.BytesIO(data)).namelist()


def test_each_platform_carries_its_own_installer() -> None:
    win = zipfile.ZipFile(io.BytesIO(build_zip(URL, TOKEN, False, [], "windows")))
    text = win.read("install-local.ps1").decode()
    assert "@MARKETPLACE@" not in text and LOCAL_MARKETPLACE in text
    assert "--scope user" in text and "claude plugin list" in text.replace("& ", "")
    assert "install-local.sh" not in win.namelist()
    posix = _names(build_zip(URL, TOKEN, False, [], "posix"))
    assert "install-local.sh" in posix and "install-local.ps1" not in posix
    assert LOCAL_MARKETPLACE.endswith("-local")


def test_the_managed_bundles_plugin_carries_the_installer_too() -> None:
    """For a fleet tool to run per user; the plugin's own config is empty, so only the
    machine-wide hooks.conf makes it send."""
    bundle = zipfile.ZipFile(io.BytesIO(build_managed(URL, TOKEN, False, [], "posix")))
    inner = zipfile.ZipFile(io.BytesIO(bundle.read("plugin-posix.zip")))
    assert "install-local.sh" in inner.namelist() and inner.read("config") == b""
    assert "install-local.sh" in bundle.read("README.txt").decode()


def test_the_shell_installer_builds_a_marketplace_and_installs(tmp_path: Path) -> None:
    folder = tmp_path / "plugin"
    zipfile.ZipFile(io.BytesIO(build_zip(URL, TOKEN, False, [], "posix"))).extractall(folder)
    log = tmp_path / "calls.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "claude"  # stands in for the Claude Code CLI: records each call
    fake.write_text(f'#!/bin/sh\necho "$*" >> "{log}"\n')
    fake.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "XDG_DATA_HOME": str(tmp_path / "data"),
    }
    run = subprocess.run(
        ["sh", str(folder / "install-local.sh")], env=env, capture_output=True, text=True
    )
    assert run.returncode == 0, run.stderr
    calls = log.read_text().splitlines()
    dest = tmp_path / "data" / LOCAL_MARKETPLACE
    assert calls == [
        f"plugin marketplace remove {LOCAL_MARKETPLACE}",
        f"plugin marketplace add {dest}",
        f"plugin install siem-claude-hooks-posix@{LOCAL_MARKETPLACE} --scope user",
        "plugin list",
    ]
    market = json.loads((dest / ".claude-plugin" / "marketplace.json").read_text())
    assert market["name"] == LOCAL_MARKETPLACE
    assert market["plugins"] == [
        {
            "name": "siem-claude-hooks-posix",
            "source": "./plugins/siem-claude-hooks-posix",
            "description": market["plugins"][0]["description"],
        }
    ]
    copy = dest / "plugins" / "siem-claude-hooks-posix"
    assert (copy / ".claude-plugin" / "plugin.json").is_file()
    assert (copy / "hooks" / "send.sh").is_file() and not (copy / "install-local.sh").exists()
    assert stat.S_IMODE((copy / "config").stat().st_mode) == 0o600
    assert f"REMNANT_TOKEN={TOKEN}" in (copy / "config").read_text()


def test_the_shell_installer_stops_without_the_cli(tmp_path: Path) -> None:
    folder = tmp_path / "plugin"
    zipfile.ZipFile(io.BytesIO(build_zip(URL, TOKEN, False, [], "posix"))).extractall(folder)
    empty = tmp_path / "bin"
    empty.mkdir()
    run = subprocess.run(
        ["/bin/sh", str(folder / "install-local.sh")],
        env={"PATH": str(empty), "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
    )
    assert run.returncode == 1 and "not on PATH" in run.stderr
