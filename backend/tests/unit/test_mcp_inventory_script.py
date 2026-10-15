"""The endpoint MCP inventory script reports names only, never secrets (ADR-0015 row 6)."""

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts" / "endpoint"))
import mcp_inventory

SECRET = "ghp_supersecrettoken123"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    h = tmp_path / "alice"
    monkeypatch.setattr(mcp_inventory, "homes", lambda: [("alice", h)])
    monkeypatch.setattr(mcp_inventory.platform, "system", lambda: "Linux")
    (h / ".config" / "Claude").mkdir(parents=True)
    (h / ".config" / "Claude" / "claude_desktop_config.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "github": {
                        "command": "npx",
                        "args": [
                            "-y",
                            "@modelcontextprotocol/server-github@1.4.0",
                            f"--token={SECRET}",
                        ],
                        "env": {"GITHUB_TOKEN": SECRET},
                    },
                    "paste": {
                        "url": f"https://mcp.paste.example/sse?key={SECRET}",
                        "headers": {"Authorization": SECRET},
                    },
                }
            }
        )
    )
    (h / ".claude.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "fs": {"command": "/usr/local/bin/uvx", "args": ["mcp-server-fs", SECRET]}
                },
                "projects": {
                    "/work/app": {
                        "mcpServers": {"pg": {"command": "docker", "args": ["run", SECRET]}}
                    }
                },
            }
        )
    )
    (h / ".cursor").mkdir()
    (h / ".cursor" / "mcp.json").write_text("{not json")
    return h


def records() -> list[dict[str, Any]]:
    return list(mcp_inventory.inventory())


def test_lists_servers_with_names_only(home: Path) -> None:
    out = {(r["client"], r["scope"], r["server"]): r for r in records()}
    assert set(out) == {
        ("claude_desktop", "user", "github"),
        ("claude_desktop", "user", "paste"),
        ("claude_code", "user", "fs"),
        ("claude_code", "project", "pg"),
    }
    gh = out[("claude_desktop", "user", "github")]
    assert (gh["transport"], gh["command"], gh["package"]) == (
        "stdio",
        "npx",
        "@modelcontextprotocol/server-github",
    )
    paste = out[("claude_desktop", "user", "paste")]
    assert (paste["transport"], paste["url_host"]) == ("http", "mcp.paste.example")
    assert out[("claude_code", "user", "fs")]["command"] == "uvx"
    assert out[("claude_code", "user", "fs")]["package"] == "mcp-server-fs"
    assert out[("claude_code", "project", "pg")]["package"] is None  # docker is not a launcher


def test_no_secret_reaches_the_output_or_the_otlp_body(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert mcp_inventory.main([]) == 0
    printed = capsys.readouterr().out
    assert SECRET not in printed and "args" not in printed and "env" not in printed
    body = json.dumps(mcp_inventory.otlp_body(records()))
    assert SECRET not in body
    assert '"mcp_inventory"' in body


def test_endpoint_needs_a_token_file_and_https(home: Path, tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        mcp_inventory.main(["--endpoint", "https://siem.example.internal/api/otlp"])
    tok = tmp_path / "t"
    tok.write_text("rmt_x")
    with pytest.raises(SystemExit, match="https"):
        mcp_inventory.main(
            ["--endpoint", "http://siem.example.internal/api/otlp", "--token-file", str(tok)]
        )
