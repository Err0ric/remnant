"""Server-side admin commands, run on the server host (not over the network).

`app-admin ingest` loads log files into the lake with the watcher's pipeline.
`app-admin reset-password` is the lost-admin recovery path (ADR-0001): it needs
shell access to the server, never a web route.
"""

from pathlib import Path
from typing import Annotated

import typer

from app.auth.passwords import MIN_LENGTH
from app.auth.users import UserStore
from app.core.config import load_config
from app.core.errors import NotFoundError
from app.ingest.envelope import SyslogEnvelopeConfig
from app.ingest.framer import Framer
from app.ingest.normalizer import Normalizer, SourceFormat, SourceSpec
from app.ingest.records import decode_frame
from app.ingest.writer import LakeWriter
from app.meta.db import MetaDB

app = typer.Typer(help="Server-side admin commands.", no_args_is_help=True, add_completion=False)

BATCH = 50_000


@app.callback()
def _group() -> None:
    """Keep subcommands explicit (`app-admin ingest ...`) as more are added."""


CHUNK = 1 << 20


@app.command()
def ingest(
    files: Annotated[list[Path], typer.Argument(exists=True, dir_okay=False, readable=True)],
    source: Annotated[str, typer.Option("--source", "-s", help="Source id, e.g. linux_auth")],
    fmt: Annotated[SourceFormat, typer.Option("--format", "-f")] = "syslog",
    timezone: Annotated[str, typer.Option(help="IANA timezone for timestamps without one")] = "UTC",
    classification: Annotated[str, typer.Option(help="local_only or cloud_allowed")] = "local_only",
    max_len: Annotated[int, typer.Option(help="Max bytes per message")] = 8192,
) -> None:
    """Load log files into the lake under a source id."""
    config = load_config()
    spec = SourceSpec.model_validate(
        {
            "source_id": source,
            "format": fmt,
            "classification": classification,
            "envelope": SyslogEnvelopeConfig(timezone=timezone),
        }
    )
    writer = LakeWriter(config.paths.data_dir / "lake")
    total = 0
    for path in files:
        normalizer = Normalizer(spec)
        batch = []
        with path.open("rb") as fh:
            chunks = iter(lambda: fh.read(CHUNK), b"")
            for frame in Framer(max_len=max_len).frames(chunks):
                row = normalizer.normalize(decode_frame(frame))
                if row is None:
                    continue
                batch.append(row)
                if len(batch) >= BATCH:
                    writer.write(batch)
                    total += len(batch)
                    batch = []
        if batch:
            writer.write(batch)
            total += len(batch)
        typer.echo(f"{path}: done")
    typer.echo(f"Ingested {total} events into source '{source}'")


@app.command("reset-password")
def reset_password(
    username: Annotated[str, typer.Argument(help="Account to reset")],
) -> None:
    """Set a new password, re-enable the account, and sign it out everywhere."""
    password = typer.prompt("New password", hide_input=True, confirmation_prompt=True)
    if len(password) < MIN_LENGTH:
        typer.echo(f"Password must be at least {MIN_LENGTH} characters", err=True)
        raise typer.Exit(2)
    config = load_config()
    try:
        UserStore(MetaDB(config.paths.data_dir / "meta.sqlite")).set_password(username, password)
    except NotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Password reset for {username}. Existing sessions were signed out.")


def main() -> None:
    app()
