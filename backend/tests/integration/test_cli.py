"""CLI against a real in-process server (no network)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from app.cli import main as cli
from app.cli.client import Credentials
from app.cli.output import clean
from app.core.config import load_config
from app.ingest.framer import Framer
from app.ingest.normalizer import Normalizer, SourceSpec
from app.ingest.records import decode_frame
from app.ingest.writer import LakeWriter
from app.main import create_app

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
LOG = (
    b"<38>Oct  9 20:41:12 bastion sshd[1]: Accepted publickey for jordan\n"
    b"<38>Oct  9 21:00:00 bastion sshd[2]: Failed password for admin\n"
    b"<38>Oct  9 21:05:00 bastion sshd[3]: \x1b[31mred\x1b[0m \x1b]0;pwned\x07title\n"
)


@pytest.fixture
def runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    n = Normalizer(SourceSpec(source_id="linux_auth", format="syslog"), clock=lambda: NOW)
    rows = [r for f in Framer().frames([LOG]) if (r := n.normalize(decode_frame(f)))]
    LakeWriter(tmp_path / "lake").write(rows)
    env = {"APP__PATHS__DATA_DIR": str(tmp_path)}
    app = create_app(load_config(Path("missing.yaml"), env))

    def factory(creds: Credentials) -> TestClient:
        client = TestClient(app)
        client.headers["Accept"] = "application/json"
        return client

    monkeypatch.setattr(cli, "client_factory", factory)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("REMNANT_TOKEN", raising=False)
    monkeypatch.delenv("REMNANT_SERVER", raising=False)
    return CliRunner()


def run(runner: CliRunner, *args: str) -> tuple[int, str, str]:
    res = runner.invoke(cli.app, list(args))
    return res.exit_code, res.stdout, res.stderr


def test_query_table(runner: CliRunner) -> None:
    code, out, err = run(
        runner, "query", "SELECT actor_process_pid AS pid, message FROM events ORDER BY pid"
    )
    assert code == 0
    lines = out.splitlines()
    assert lines[0].split() == ["PID", "MESSAGE"]
    assert "Failed password for admin" in lines[2]
    assert "3 rows" in err


def test_query_json_lines(runner: CliRunner) -> None:
    code, out, _ = run(
        runner, "query", "SELECT actor_process_pid AS pid FROM events ORDER BY pid", "-o", "json"
    )
    assert code == 0
    assert [json.loads(line) for line in out.splitlines()] == [{"pid": 1}, {"pid": 2}, {"pid": 3}]


def test_tail_last_two_in_time_order(runner: CliRunner) -> None:
    code, out, _ = run(runner, "tail", "linux_auth", "-n", "2", "-o", "csv")
    assert code == 0
    lines = out.splitlines()
    assert lines[0] == "time,source_id,device_hostname,actor_process_name,message"
    assert "Failed password for admin" in lines[1]
    assert lines[2].startswith("2026-10-09T21:05:00")


def test_tail_raw_strips_terminal_escapes(runner: CliRunner) -> None:
    code, out, _ = run(runner, "tail", "linux_auth", "-n", "1", "-o", "raw")
    assert code == 0
    assert "\x1b" not in out and "\x07" not in out
    assert out.strip().endswith("red title")


def test_tail_where_filter(runner: CliRunner) -> None:
    code, out, _ = run(
        runner, "tail", "linux_auth", "--where", "message LIKE 'Failed%'", "-o", "raw"
    )
    assert code == 0
    assert out.strip().endswith("Failed password for admin")


def test_guard_error_reported(runner: CliRunner) -> None:
    code, _, err = run(runner, "query", "DROP TABLE events")
    assert code == 1
    assert "error:" in err and "not allowed" in err.lower()


def test_bad_source_rejected_locally(runner: CliRunner) -> None:
    code, _, err = run(runner, "tail", "linux_auth' OR 1=1 --")
    assert code != 0
    assert "lowercase" in err


def test_bad_since(runner: CliRunner) -> None:
    code, _, err = run(runner, "query", "SELECT 1", "--since", "yesterday")
    assert code != 0
    assert "30m" in err


def test_login_on_open_server_needs_no_password(runner: CliRunner) -> None:
    code, out, _ = run(runner, "login")
    assert code == 0
    assert "No sign-in needed" in out


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("plain", "plain"),
        ("a\x1b[31mred\x1b[0mb", "aredb"),
        ("x\x1b]0;title\x07y", "xy"),
        ("line1\nline2\ttab", "line1 line2 tab"),
        ("bell\x07 null\x00 c1\x9b", "bell null c1"),
        (None, "·"),
        (42, "42"),
    ],
)
def test_clean(value: object, expected: str) -> None:
    assert clean(value) == expected


# --- saved searches ---------------------------------------------------------------------


def test_search_list_run_export_import(runner: CliRunner, tmp_path: Path) -> None:
    spec = {
        "id": "by_host",
        "name": "Events by host",
        "tags": ["triage"],
        "visibility": "shared",
        "sql": "SELECT device_hostname, count(*) AS n FROM events GROUP BY 1 LIMIT {{top}}",
        "params": [{"name": "top", "type": "int", "default": 10}],
    }
    client = cli.client_factory(Credentials("http://127.0.0.1", None))
    assert client.post("/api/searches", json=spec).status_code == 201

    code, out, _ = run(runner, "search", "-o", "csv")
    assert code == 0
    assert "by_host,Events by host,triage,shared" in out

    # Saved-search runs default to the last 24 hours; the fixture lines are fixed dates.
    code, out, _ = run(runner, "search", "by_host", "-p", "top=1", "-o", "csv", "--since", "3650d")
    assert code == 0, out
    assert out.splitlines()[0] == "device_hostname,n"
    assert len(out.splitlines()) == 2

    code, out, err = run(runner, "search", "by_host", "-p", "top=lots")
    assert code == 1 and "top" in err

    code, out, _ = run(runner, "search", "by_host", "--export")
    assert code == 0 and "schema_version: 1" in out
    doc = tmp_path / "copy.yaml"
    doc.write_text(out.replace("id: by_host", "id: by_host_copy"))
    code, out, _ = run(runner, "search", "--import", str(doc))
    assert code == 0 and "Imported by_host_copy" in out


def test_search_param_must_be_name_value(runner: CliRunner) -> None:
    code, _, err = run(runner, "search", "anything", "-p", "no-equals")
    assert code != 0
    assert "name=value" in err


def test_tail_follow_reads_the_live_stream_and_prints_each_event_once(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`tail -f` follows on the server's live stream (ADR-0036 row 10): what arrived after
    the last line shown, once, then the stream's own end message."""
    later = datetime(2026, 10, 10, 12, 5, tzinfo=UTC)
    new = b"<38>Oct 10 12:04:00 bastion sshd[9]: Accepted password for newcomer\n"
    n = Normalizer(SourceSpec(source_id="linux_auth", format="syslog"), clock=lambda: later)
    rows = [r for f in Framer().frames([new]) if (r := n.normalize(decode_frame(f)))]
    real = cli.client_factory

    def factory(creds: Credentials) -> TestClient:
        client = real(creds)
        live = client.app.state.live  # type: ignore[attr-defined]  # TestClient's app
        live.poll_s, live.limit_override_s = 0.05, 0.5
        return client

    monkeypatch.setattr(cli, "client_factory", factory)
    # The new line arrives before -f starts following: it is after the last one shown.
    original = cli.TailCursor.latest

    def latest_then_arrive(self: cli.TailCursor, lines: int) -> dict[str, object]:
        out = original(self, lines)
        LakeWriter(tmp_path / "lake").write(rows)
        return out

    monkeypatch.setattr(cli.TailCursor, "latest", latest_then_arrive)
    res = runner.invoke(cli.app, ["tail", "linux_auth", "-n", "2", "-f", "-o", "raw"])
    assert res.exit_code == 0, res.output
    lines = res.stdout.splitlines()
    assert "Failed password for admin" in lines[0]  # the first two are the latest, oldest first
    assert sum("newcomer" in line for line in lines) == 1
    assert "Live stopped after" in res.stderr


def test_query_match_runs_a_simple_search_with_bound_values(runner: CliRunner) -> None:
    code, out, err = run(runner, "query", "--match", '"failed password" -pid:2', "-o", "json")
    assert code == 0, err
    rows = [json.loads(line) for line in out.splitlines()]
    assert rows and all("Failed password" in r["message"] for r in rows)
    code, _, err = run(runner, "query", "--match", "Foo:1")
    assert code == 0 and "Note: Foo is not a column" in err


def test_query_needs_sql_or_match_but_not_both(runner: CliRunner) -> None:
    assert run(runner, "query")[0] == 2
    assert run(runner, "query", "SELECT 1", "--match", "x")[0] == 2
    code, _, err = run(runner, "query", "--match", "(a")
    assert code != 0 and "never closed" in err


def test_mcp_stdio_bridge_relays_messages_and_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    n = Normalizer(SourceSpec(source_id="linux_auth", format="syslog"), clock=lambda: NOW)
    LakeWriter(tmp_path / "lake").write(
        [r for f in Framer().frames([LOG]) if (r := n.normalize(decode_frame(f)))]
    )
    app = create_app(load_config(Path("missing.yaml"), {"APP__PATHS__DATA_DIR": str(tmp_path)}))
    monkeypatch.setattr(cli, "client_factory", lambda creds: TestClient(app))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    lines = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "t"}},
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "run_query", "arguments": {"sql": "SELECT count(*) FROM events"}},
        },
    ]
    stdin = "\n".join(json.dumps(m) for m in lines) + "\n"
    off = CliRunner().invoke(cli.app, ["mcp"], input=stdin)
    replies = [json.loads(x) for x in off.stdout.splitlines()]
    assert [r["id"] for r in replies] == [1, 2]  # the notification gets no reply
    assert "MCP server is off" in replies[0]["error"]["message"]

    app.state.mcp_settings.save(True, True, "test")
    on = CliRunner().invoke(cli.app, ["mcp"], input=stdin)
    replies = [json.loads(x) for x in on.stdout.splitlines()]
    assert replies[0]["result"]["serverInfo"]["name"]
    out = json.loads(replies[1]["result"]["content"][0]["text"])
    assert out["rows"] == [[3]] and out["sources_read"] == ["linux_auth"]


def test_csv_output_cannot_run_spreadsheet_formulas() -> None:
    from app.cli.output import render

    text = render(["message", "n"], [['=HYPERLINK("http://203.0.113.5/","x")', -5]], "csv")
    assert text.splitlines()[1] == '"\'=HYPERLINK(""http://203.0.113.5/"",""x"")",-5'
