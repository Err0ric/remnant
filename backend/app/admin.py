"""Server-side admin commands, run on the server host (not over the network).

`app-admin ingest` loads log files into the lake with the watcher's pipeline.
`app-admin reset-password` is the lost-admin recovery path (ADR-0001): it needs
shell access to the server, never a web route.
`app-admin backup`, `verify-backup`, and `restore` handle the data folder
(docs/install/backup.md).
"""

import os
import shutil
import sys
import tempfile
from datetime import UTC, datetime
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
from app.ops.backup import BackupError, BackupInfo, create, restore, verify

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


def _describe(info: BackupInfo) -> str:
    key = "includes the key" if info.has_key else "WITHOUT the key"
    return (
        f"{info.files} files, {info.bytes / 1e6:.1f} MB, made {info.created_at},"
        f" database schema {info.schema_version}, {key}"
    )


@app.command()
def backup(
    out: Annotated[
        str | None,
        typer.Option("--out", "-o", help="File to write, or - for standard output"),
    ] = None,
    no_key: Annotated[
        bool,
        typer.Option(
            "--no-key",
            help="Leave out the encryption key (stored secrets then cannot be restored)",
        ),
    ] = False,
) -> None:
    """Back up the data folder while the server runs: events, settings, users, audit log."""
    config = load_config()
    try:
        if out == "-":
            info = create(config.paths.data_dir, sys.stdout.buffer, include_key=not no_key)
            where = "standard output"
        else:
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            path = Path(out) if out else Path(f"backup-{stamp}.tar.gz")
            # 0600 from the first byte: the file holds the key and every stored secret.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, "wb") as fh:
                    info = create(config.paths.data_dir, fh, include_key=not no_key)
            except BaseException:
                path.unlink(missing_ok=True)
                raise
            where = str(path)
    except (BackupError, FileExistsError) as exc:
        typer.echo(f"Backup failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Backup written to {where}: {_describe(info)}", err=True)
    if info.has_key:
        typer.echo("Keep it as safe as the server: it can decrypt every stored secret.", err=True)


def _spooled(archive: str) -> Path:
    """`-` reads the backup from standard input into a private temporary file."""
    if archive != "-":
        return Path(archive)
    fd, name = tempfile.mkstemp(suffix=".tar.gz")
    with os.fdopen(fd, "wb") as fh:
        shutil.copyfileobj(sys.stdin.buffer, fh)
    return Path(name)


@app.command("verify-backup")
def verify_backup(
    archive: Annotated[str, typer.Argument(help="Backup file, or - for standard input")],
) -> None:
    """Check every file in a backup against its checksum, without restoring it."""
    path = _spooled(archive)
    try:
        info, _ = verify(path)
    except BackupError as exc:
        typer.echo(f"Backup is NOT usable: {exc}", err=True)
        raise typer.Exit(1) from exc
    finally:
        if archive == "-":
            path.unlink(missing_ok=True)
    typer.echo(f"Backup OK: {_describe(info)}")


@app.command("restore")
def restore_cmd(
    archive: Annotated[str, typer.Argument(help="Backup file, or - for standard input")],
    replace: Annotated[
        bool,
        typer.Option("--replace", help="Restore over existing data (kept aside, not deleted)"),
    ] = False,
) -> None:
    """Restore a backup into the data folder. Stop the server first."""
    config = load_config()
    path = _spooled(archive)
    try:
        info, kept = restore(path, config.paths.data_dir, replace=replace)
    except BackupError as exc:
        typer.echo(f"Restore failed, nothing was changed: {exc}", err=True)
        raise typer.Exit(1) from exc
    finally:
        if archive == "-":
            path.unlink(missing_ok=True)
    typer.echo(f"Restored {_describe(info)} into {config.paths.data_dir}")
    if kept is not None:
        typer.echo(f"The previous contents are in {kept}; delete it once the server looks right.")
    if not info.has_key:
        typer.echo(
            "The backup had no key: re-enter AI provider keys, alert target secrets, and Loki"
            " passwords."
        )


def main() -> None:
    app()
