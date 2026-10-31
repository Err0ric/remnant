"""`remnant` command-line client (SPEC 5.6): login, query, tail, search, ask."""

import getpass
import json
import re
import shutil
import sys
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import typer

from app.cli.client import (
    Api,
    ApiError,
    ClientFactory,
    Credentials,
    UntrustedCertificateError,
    default_client,
    delete_token,
    fetch_certificate,
    fingerprint,
    load_credentials,
    save_pin,
    save_server,
    store_token,
)
from app.cli.output import OutputFormat, clean, clean_block, render
from app.cli.tailing import TAIL_COLUMNS, TailCursor
from app.core.branding import PRODUCT_NAME

app = typer.Typer(
    help=f"{PRODUCT_NAME} command-line client. Talks to the server API; never reads data files.",
    no_args_is_help=True,
    add_completion=False,
)

# Swappable in tests (the CLI otherwise talks real HTTP).
client_factory: ClientFactory = default_client

_SOURCE = re.compile(r"[a-z0-9][a-z0-9_]{0,63}")
_SINCE = re.compile(r"(\d+)([smhd])")
_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}

ServerOpt = Annotated[
    str | None,
    typer.Option("--server", help="Server URL (default: saved or http://127.0.0.1:8080)"),
]
FormatOpt = Annotated[
    OutputFormat,
    typer.Option("--format", "-o", help="table, json (one object per line), csv, or raw"),
]
SinceOpt = Annotated[
    str | None, typer.Option("--since", help="Only events newer than this, e.g. 15m, 1h, 7d")
]


def _api(server: str | None) -> Api:
    return Api(load_credentials(server), client_factory)


def _since(value: str | None) -> datetime | None:
    if value is None:
        return None
    m = _SINCE.fullmatch(value.strip())
    if not m:
        raise typer.BadParameter("use a number and unit, like 30m, 2h, or 7d", param_hint="--since")
    return datetime.now(UTC) - timedelta(**{_UNITS[m.group(2)]: int(m.group(1))})


def _fail(exc: ApiError) -> None:
    hint = " (run `remnant login`)" if exc.status == 401 else ""
    typer.secho(f"error: {exc.detail}{hint}", err=True, fg=typer.colors.RED)
    raise typer.Exit(1)


def _print(data: dict[str, Any], fmt: OutputFormat) -> None:
    rows = data["rows"]
    if rows or fmt == "table":
        typer.echo(render(data["columns"], rows, fmt, shutil.get_terminal_size((160, 40)).columns))
    if fmt == "table":
        note = " (truncated)" if data.get("truncated") else ""
        typer.secho(f"{len(rows)} rows · {data['elapsed_ms']} ms{note}", err=True, dim=True)


def _trust_on_first_use(server: str) -> None:
    """Show the certificate fingerprint and pin it only if the user confirms it."""
    try:
        pem = fetch_certificate(server)
    except OSError as exc:
        typer.secho(f"error: cannot reach {server}: {exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(1) from exc
    typer.echo(f"{server} presented a certificate this computer does not trust yet.")
    typer.echo(f"SHA-256 {fingerprint(pem)}")
    if not typer.confirm(
        "Does this match the fingerprint printed in the server log?", default=False
    ):
        typer.secho("Not trusted. Nothing was saved.", err=True)
        raise typer.Exit(1)
    path = save_pin(server, pem)
    typer.echo(f"Trusted. Saved to {path}")


@app.command()
def login(
    server: ServerOpt = None,
    username: Annotated[str | None, typer.Option("--username", "-u")] = None,
) -> None:
    """Sign in and keep a token in the system keychain. The password is never echoed."""
    target = (server or load_credentials().server).rstrip("/")
    save_server(target)
    try:
        try:
            state = Api(Credentials(target, None), client_factory).auth_state()
        except UntrustedCertificateError:
            _trust_on_first_use(target)
            state = Api(Credentials(target, None), client_factory).auth_state()
        if state["mode"] == "open":
            typer.echo(f"{target} runs without accounts (local only). No sign-in needed.")
            return
        if state["mode"] == "setup":
            typer.secho(
                "No administrator exists yet. Open the one-time setup link from the server log.",
                err=True,
            )
            raise typer.Exit(1)
        user = username or typer.prompt("Username")
        password = getpass.getpass("Password: ")
        token = Api(Credentials(target, None), client_factory).login(user, password)
    except ApiError as exc:
        _fail(exc)
        return
    where = store_token(target, token)
    typer.echo(f"Signed in to {target} as {user}. Token saved in {where}.")


@app.command()
def logout(server: ServerOpt = None) -> None:
    """Revoke this computer's token on the server and forget it."""
    creds = load_credentials(server)
    if creds.token:
        try:
            Api(creds, client_factory).logout()
        except ApiError:
            pass  # already expired or revoked; still forget it locally
    delete_token(creds.server)
    typer.echo(f"Signed out of {creds.server}.")


@app.command()
def query(
    sql: Annotated[str | None, typer.Argument(help="SQL to run against the events table")] = None,
    match: Annotated[
        str | None,
        typer.Option(
            "--match",
            "-m",
            help="Simple search instead of SQL, e.g. 'sshd \"failed password\" -user:root'",
        ),
    ] = None,
    source: Annotated[
        list[str] | None, typer.Option("--source", "-s", help="Limit to these sources")
    ] = None,
    since: SinceOpt = None,
    fmt: FormatOpt = "table",
    server: ServerOpt = None,
) -> None:
    """Run SQL, or a Simple search with --match, against the events table (read-only,
    guarded by the server)."""
    if (sql is None) == (match is None):
        typer.echo("Give either SQL or --match, not both.", err=True)
        raise typer.Exit(2)
    start = _since(since)
    api = _api(server)
    try:
        params: dict[str, Any] | None = None
        if match is not None:
            compiled = api.compile_search(match)
            sql, params = compiled["sql"], compiled["params"] or None
            for note in compiled.get("notes", []):
                typer.echo(f"Note: {clean(str(note))}", err=True)
        if sql is None:  # unreachable: one of the two was given
            raise typer.Exit(2)
        data = api.query(
            sql, start=start.isoformat() if start else None, sources=source, params=params
        )
    except ApiError as exc:
        _fail(exc)
        return
    _print(data, fmt)


@app.command()
def ask(
    question: Annotated[str, typer.Argument(help="Your question in plain English")],
    model: Annotated[
        str | None, typer.Option("--model", "-m", help="Provider name or id (default: first local)")
    ] = None,
    source: Annotated[
        list[str] | None, typer.Option("--source", "-s", help="Limit to these sources")
    ] = None,
    since: SinceOpt = "24h",
    fmt: FormatOpt = "table",
    server: ServerOpt = None,
) -> None:
    """A model drafts SQL for your question. It is printed, and runs only if you say yes."""
    api = _api(server)
    start = _since(since)
    try:
        provider_id = None
        if model:
            wanted = model.lower()
            match = [
                p
                for p in api.ask_providers()
                if p["provider_id"] == model or str(p["name"]).lower() == wanted
            ]
            if not match:
                typer.secho(f"error: no enabled AI provider named {model}", err=True, fg="red")
                raise typer.Exit(1)
            provider_id = match[0]["provider_id"]
        answer = api.ask(
            question,
            provider_id=provider_id,
            start=start.isoformat() if start else None,
            sources=source,
        )
    except ApiError as exc:
        _fail(exc)
        return
    provider = answer["provider"]
    typer.secho(
        f"-- {clean(provider['name'])} ({clean(provider['model'])}, {provider['locality']})"
        " wrote this SQL. Read it before running.",
        err=True,
        dim=True,
    )
    typer.echo(clean_block(answer["sql"]))
    if answer.get("explanation"):
        typer.secho(f"-- {clean(answer['explanation'])}", err=True, dim=True)
    for item in answer.get("assumptions") or []:
        typer.secho(f"-- assumes: {clean(item)}", err=True, dim=True)
    check = {"ok": "returns rows", "empty": "matched no rows", "failed": "failed"}[answer["check"]]
    detail = f": {clean(answer['check_detail'])}" if answer.get("check_detail") else ""
    typer.secho(f"-- self-check {check}{detail}", err=True, dim=True)
    # Never auto-runs (SPEC 5.6): the default is no, and there is no flag to skip asking.
    if not typer.confirm("Run?", default=False, err=True):
        return
    try:
        data = api.query(answer["sql"], start=start.isoformat() if start else None, sources=source)
    except ApiError as exc:
        _fail(exc)
        return
    _print(data, fmt)


_PARAM = re.compile(r"^([a-z_][a-z0-9_]{0,31})=(.*)$", re.S)


@app.command()
def search(
    search_id: Annotated[
        str | None, typer.Argument(help="Saved search id to run; omit to list them")
    ] = None,
    param: Annotated[
        list[str] | None,
        typer.Option("--param", "-p", help="Parameter as name=value; repeat for more"),
    ] = None,
    tag: Annotated[
        str | None, typer.Option("--tag", help="List only searches with this tag")
    ] = None,
    export: Annotated[
        bool, typer.Option("--export", help="Print the saved search as YAML instead of running it")
    ] = False,
    import_file: Annotated[
        typer.FileText | None,
        typer.Option("--import", help="Import a saved search from a YAML file"),
    ] = None,
    since: SinceOpt = None,
    fmt: FormatOpt = "table",
    server: ServerOpt = None,
) -> None:
    """List, run, export, or import saved searches. Runs use your own source access."""
    api = _api(server)
    try:
        if import_file is not None:
            created = api.import_search(import_file.read())
            typer.echo(f"Imported {created['id']} (private; share it from the web UI if needed)")
            return
        if search_id is None:
            rows = [
                [s["id"], s["name"], ", ".join(s["tags"]), s["visibility"]]
                for s in api.searches(tag)
            ]
            _print(
                {"columns": ["id", "name", "tags", "visibility"], "rows": rows, "elapsed_ms": 0},
                fmt,
            )
            return
        if export:
            typer.echo(api.export_search(search_id), nl=False)
            return
        values: dict[str, str] = {}
        for item in param or []:
            m = _PARAM.match(item)
            if not m:
                raise typer.BadParameter("use name=value", param_hint="--param")
            values[m.group(1)] = m.group(2)
        start = _since(since)
        data = api.run_search(search_id, values, start.isoformat() if start else None)
    except ApiError as exc:
        _fail(exc)
        return
    _print(data, fmt)


@app.command()
def tail(
    source: Annotated[str, typer.Argument(help="Source id, e.g. linux_auth")],
    lines: Annotated[
        int, typer.Option("-n", "--lines", min=1, max=10_000, help="How many recent events")
    ] = 10,
    follow: Annotated[
        bool, typer.Option("-f", "--follow", help="Keep printing new events")
    ] = False,
    where: Annotated[
        str | None, typer.Option("--where", help='Extra SQL filter, e.g. "status_id = 2"')
    ] = None,
    since: SinceOpt = None,
    fmt: FormatOpt = "table",
    interval: Annotated[
        float, typer.Option(help="Ignored: the server follows every 2 s", min=0.5, hidden=True)
    ] = 2.0,
    server: ServerOpt = None,
) -> None:
    """Show the latest events from a source, like `tail -n`, optionally following. With -f
    it is a live search: it counts toward your 2 and stops at the live time limit."""
    if not _SOURCE.fullmatch(source):
        raise typer.BadParameter(
            "source ids are lowercase letters, digits, and _", param_hint="SOURCE"
        )
    api = _api(server)
    start = _since(since)
    cursor = TailCursor(
        api,
        source,
        columns="raw" if fmt == "raw" else TAIL_COLUMNS,
        where=where,
        start=start.isoformat() if start else None,
    )
    try:
        data = cursor.latest(lines)
    except ApiError as exc:
        _fail(exc)
        return
    _print(data, fmt)

    del interval  # kept so old scripts still parse
    if not follow:
        return
    # Follow on the server's live stream (ADR-0036 row 10): the same limits, audit, and
    # cursor as Live on Search; `--interval` is kept for old scripts and ignored.
    since, after = cursor.cursor()
    try:
        for event, body in api.live(cursor.follow_sql(), "cli", since, after):
            if event == "rows" and body["rows"]:
                cursor.advance(body["cursor"])
                width = shutil.get_terminal_size((160, 40)).columns
                typer.echo(render(body["columns"], body["rows"], fmt, width, header=False))
            elif event in ("notice", "end"):
                typer.echo(clean(str(body.get("message", ""))), err=True)
                if event == "end":
                    return
    except ApiError as exc:
        _fail(exc)


@app.command()
def tui(
    source: Annotated[
        str | None, typer.Option("--source", "-s", help="Source to follow in the tail pane")
    ] = None,
    since: SinceOpt = None,
    interval: Annotated[float, typer.Option(help="Seconds between tail polls", min=0.5)] = 2.0,
    server: ServerOpt = None,
) -> None:
    """Full-screen terminal view: query box, results table, and a live tail pane."""
    if source is not None and not _SOURCE.fullmatch(source):
        raise typer.BadParameter(
            "source ids are lowercase letters, digits, and _", param_hint="--source"
        )
    try:
        from app.cli.tui import Tui
    except ImportError as exc:  # textual is an optional extra
        typer.secho("The terminal UI needs the tui extra: uv sync --extra tui", err=True, fg="red")
        raise typer.Exit(1) from exc
    start = _since(since)
    Tui(_api(server), source, start.isoformat() if start else None, interval).run()


@app.command()
def mcp(server: ServerOpt = None) -> None:
    """Read-only MCP server for local AI clients, over stdin and stdout (ADR-0003).

    Relays each JSON-RPC line to the server with this computer's token. Point a client
    such as Claude Desktop at this command. Nothing but MCP messages is written to stdout.
    """
    api = _api(server)
    session: str | None = None
    for line in sys.stdin.buffer:
        if not line.strip():
            continue
        try:
            status, body, sid = api.mcp(line.strip(), session)
        except ApiError as exc:
            status, body, sid = 0, b"", None
            typer.echo(f"mcp: {exc}", err=True)
        session = sid or session
        if status == 200 and body:
            sys.stdout.buffer.write(body.replace(b"\n", b"") + b"\n")
            sys.stdout.buffer.flush()
        elif status not in (200, 202):
            reply = _mcp_error(line, status, body)
            if reply is not None:
                sys.stdout.buffer.write(reply + b"\n")
                sys.stdout.buffer.flush()


def _mcp_error(line: bytes, status: int, body: bytes) -> bytes | None:
    """A JSON-RPC error for a request the server refused (off, no access, unreachable)."""
    try:
        request = json.loads(line)
    except ValueError:
        return None
    if not isinstance(request, dict) or request.get("id") is None:
        return None  # a notification gets no reply, even on failure
    try:
        detail = str(json.loads(body).get("detail", "")) if body else ""
    except (ValueError, AttributeError):
        detail = ""
    message = detail or ("Cannot reach the server" if status == 0 else f"HTTP {status}")
    error = {"code": -32000, "message": message[:300]}
    return json.dumps({"jsonrpc": "2.0", "id": request["id"], "error": error}).encode()


def main() -> None:
    app()
