"""`remnant` command-line client (SPEC 5.6): login, query, tail, search, ask."""

import getpass
import re
import shutil
import time
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
TAIL_COLUMNS = "time, source_id, device_hostname, actor_process_name, message"

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


def _print(data: dict[str, Any], fmt: OutputFormat, reverse: bool = False) -> None:
    rows = list(reversed(data["rows"])) if reverse else data["rows"]
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
    interval: Annotated[float, typer.Option(help="Seconds between polls with -f", min=0.5)] = 2.0,
    server: ServerOpt = None,
) -> None:
    """Show the latest events from a source, like `tail -n`, optionally following."""
    if not _SOURCE.fullmatch(source):
        raise typer.BadParameter(
            "source ids are lowercase letters, digits, and _", param_hint="SOURCE"
        )
    api = _api(server)
    cols = "raw" if fmt == "raw" else TAIL_COLUMNS
    extra = f" AND ({where})" if where else ""
    start = _since(since)
    # source is validated above; the server guard and sandbox apply to the whole query.
    base = f"FROM events WHERE source_id = '{source}'{extra}"
    try:
        data = api.query(
            f"SELECT {cols}, time_observed AS _seen, event_id AS _id {base} "
            f"ORDER BY coalesce(time, time_observed) DESC, time_observed DESC LIMIT {lines}",
            start=start.isoformat() if start else None,
        )
    except ApiError as exc:
        _fail(exc)
        return
    seen_ids = {r[-1] for r in data["rows"]}
    newest = max((r[-2] for r in data["rows"]), default=None)
    _print(_strip_cursor(data), fmt, reverse=True)

    while follow:
        time.sleep(interval)
        since_clause = f" AND time_observed >= TIMESTAMPTZ '{_iso(newest)}'" if newest else ""
        try:
            data = api.query(
                f"SELECT {cols}, time_observed AS _seen, event_id AS _id {base}{since_clause} "
                "ORDER BY time_observed, coalesce(time, time_observed) LIMIT 1000"
            )
        except ApiError as exc:
            _fail(exc)
            return
        fresh = [r for r in data["rows"] if r[-1] not in seen_ids]
        if fresh:
            seen_ids.update(r[-1] for r in fresh)
            newest = max(r[-2] for r in fresh)
            data["rows"] = fresh
            out = _strip_cursor(data)
            width = shutil.get_terminal_size((160, 40)).columns
            typer.echo(render(out["columns"], out["rows"], fmt, width, header=False))


def _iso(value: str) -> str:
    """Re-render a server timestamp so only a valid ISO value reaches the SQL text."""
    return datetime.fromisoformat(value).isoformat()


def _strip_cursor(data: dict[str, Any]) -> dict[str, Any]:
    """Drop the helper columns (_seen, _id) used for follow mode."""
    return {**data, "columns": data["columns"][:-2], "rows": [r[:-2] for r in data["rows"]]}


def main() -> None:
    app()
