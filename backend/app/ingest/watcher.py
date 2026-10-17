"""Tail/watch ingest (SPEC 3.5).

Polls each enabled source's files, reads only complete new lines from the last
checkpoint, and writes them through the normal pipeline. Rotation is detected by
inode change (rename) or a file shorter than the checkpoint (copytruncate).
Delivery is at-least-once: the checkpoint advances after the lake write.
"""

import errno
import json
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx
import structlog

from app.core.errors import ParamInvalidError, SourceRejectedError
from app.core.ids import AUTO_PARSER
from app.ingest.connectors import registry as api_connectors
from app.ingest.connectors.base import ConnectorError, RetryLaterError, backoff
from app.ingest.connectors.loki import (
    POLL_EVERY,
    LokiClient,
    LokiSettings,
    Position,
    from_ns,
)
from app.ingest.connectors.loki import poll as loki_poll
from app.ingest.evtx import EvtxReader, file_signature
from app.ingest.framer import Framer
from app.ingest.integrity import LakeEvents
from app.ingest.normalizer import Normalizer
from app.ingest.records import DecodedLine, Frame, decode_frame
from app.ingest.sources import (
    SPOOL_SUFFIX,
    SourceConfig,
    SourceStore,
    display_name,
    files_for,
    open_regular,
    path_key,
    spool_files,
    spool_name,
)
from app.ingest.writer import LakeWriter
from app.meta.db import MetaDB
from app.templates.registry import TemplateRegistry
from app.templates.router import AutoNormalizer
from app.templates.runtime import TemplateNormalizer

log = structlog.get_logger(__name__)

# An .evtx shorter than its header says is usually a copy still being written. If its size
# has not changed for this long it is read as it is (a truncated transfer would otherwise
# never be ingested), and the chunks it lacks are simply not there.
SHORT_EVTX_GRACE = timedelta(minutes=10)
SYSLOG_MAX_MESSAGE = 65_536  # the listener never spools a longer message
SPOOL_HEADER_MAX = 256  # bytes: a syslog spool record header is far shorter
READ_LIMIT = 8 << 20  # bytes per file per pass, so one huge file cannot starve the rest
MAX_LINE = 65_536


@dataclass(frozen=True, slots=True)
class SourceStatus:
    """What the last pass saw for one source. In memory; resets on restart."""

    files: int = 0
    last_pass_at: datetime | None = None
    last_event_at: datetime | None = None
    events_last_pass: int = 0
    events_since_start: int = 0
    error: str | None = None
    # EVTX records that could not be read, from the latest read of each file the source
    # lists now. Replaced on each read, never added up: a missing record just past the
    # checkpoint is looked for again on the next pass and would be counted twice.
    records_skipped: int = 0
    # .evtx files shorter than their header says, still inside SHORT_EVTX_GRACE.
    files_waiting: int = 0
    # Loki and API sources: how far the read position is behind now, in seconds.
    behind_s: float | None = None
    # API sources: feeds that failed while others worked (a missing license, a scope).
    warnings: tuple[str, ...] = ()
    # API sources: the next poll after errors or a provider's request to slow down.
    retry_at: datetime | None = None


SourceState = Literal["waiting", "reading", "error", "disabled"]


def source_state(enabled: bool, st: SourceStatus | None) -> SourceState:
    """waiting, reading, error, or disabled: what the Sources and Overview pages show."""
    if not enabled:
        return "disabled"
    if st is not None and st.error:
        return "error"
    if st is None or st.last_pass_at is None:
        return "waiting"
    return "reading"


class IngestService:
    def __init__(
        self,
        sources: SourceStore,
        meta: MetaDB,
        lake_dir: Path,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        templates: TemplateRegistry | None = None,
        events: LakeEvents | None = None,
    ) -> None:
        self._sources = sources
        self._templates = templates
        self._meta = meta
        self._writer = LakeWriter(lake_dir, events)
        self._evtx = EvtxReader(max_len=MAX_LINE)
        self._clock = clock
        self._status: dict[str, SourceStatus] = {}
        self._skipped: dict[tuple[str, str], int] = {}  # (source, path key) -> latest read
        # (source, path key) -> (size, first seen at that size) for short .evtx files
        self._short: dict[tuple[str, str], tuple[int, datetime]] = {}
        # (source, path key) -> (gap, first seen) for .evtx files held before an id gap
        self._gaps: dict[tuple[str, str], tuple[tuple[int, int], datetime]] = {}
        self._lock = threading.Lock()
        # Set by the app: source id -> why its syslog listener is not listening.
        self.listener_errors: Callable[[], dict[str, str]] | None = None
        self._loki_polled: dict[str, datetime] = {}  # source id -> last poll
        # Tests swap this for a client with a fake transport.
        self.loki_client: Callable[[LokiSettings, str | None], LokiClient] = LokiClient
        # API sources (m365, anthropic): last poll, failures in a row. Tests set a transport.
        self._api_polled: dict[str, datetime] = {}
        self._api_failures: dict[str, int] = {}
        self.api_transport: httpx.BaseTransport | None = None

    def run_once(self) -> int:
        """One pass over every enabled source. Returns the number of events written.

        A failing source (folder removed, permissions changed) is recorded in its
        status and skipped; it never stops the other sources.
        """
        total = 0
        for source in self._sources.list():
            if not source.enabled:
                continue
            prev = self.status().get(source.source_id, SourceStatus())
            count, files, error = 0, 0, None
            skipped, waiting = prev.records_skipped, prev.files_waiting
            try:
                self._normalizer(source)  # a missing template shows even with no new data
                if source.kind == "loki":
                    count, behind = self._ingest_loki(source, prev)
                    now = self._clock()
                    with self._lock:
                        self._status[source.source_id] = replace(
                            prev,
                            last_pass_at=now,
                            last_event_at=now if count else prev.last_event_at,
                            events_last_pass=count,
                            events_since_start=prev.events_since_start + count,
                            error=None,
                            behind_s=behind,
                        )
                    total += count
                    continue
                if source.kind in api_connectors.API_KINDS:
                    total += self._run_api(source, prev)
                    continue
                if source.kind in SPOOL_SUFFIX:
                    spool = self._sources.spool_root
                    paths = spool_files(source, spool) if spool else []
                else:
                    paths = files_for(source, self._sources.allowed_roots)
                files = len(paths)
                failed: list[str] = []
                for path in paths:
                    # One unreadable file is reported and skipped; the others are still read.
                    try:
                        count += self._ingest_file(source, path)
                    except FileNotFoundError:
                        continue  # rotated or removed since it was listed
                    except OSError as exc:
                        reason = exc.strerror or type(exc).__name__
                        failed.append(f"{display_name(path.name)[:100]}: {reason}")
                    except Exception as exc:  # one file must not stop the rest
                        log.exception("ingest_file_failed", source_id=source.source_id)
                        failed.append(f"{display_name(path.name)[:100]}: {type(exc).__name__}")
                if failed:
                    error = f"Cannot read {len(failed)} of {files} files ({failed[0]})"
                if source.kind in SPOOL_SUFFIX:
                    paths = self._drop_read_spool(source, paths)
                listed = {(source.source_id, path_key(p)) for p in paths}
                self._prune(source.source_id, listed)
                skipped = sum(n for key, n in self._skipped.items() if key in listed)
                waiting = sum(1 for key in listed if key in self._short or key in self._gaps)
            except (SourceRejectedError, ParamInvalidError) as exc:
                error = str(exc)
            except OSError as exc:
                error = f"Cannot read: {exc.strerror or type(exc).__name__}"
            except Exception as exc:  # one source must not stop the others
                log.exception("ingest_source_failed", source_id=source.source_id)
                error = f"Ingest failed: {type(exc).__name__}"
            now = self._clock()
            with self._lock:
                self._status[source.source_id] = replace(
                    prev,
                    files=files,
                    last_pass_at=now,
                    last_event_at=now if count else prev.last_event_at,
                    events_last_pass=count,
                    events_since_start=prev.events_since_start + count,
                    error=error,
                    records_skipped=skipped,
                    files_waiting=waiting,
                )
            total += count
        return total

    def _ingest_loki(self, source: SourceConfig, prev: SourceStatus) -> tuple[int, float | None]:
        """Read new lines from Loki (ADR-0011) at most every POLL_EVERY. The lake is
        written before the position moves, so a crash can repeat lines, never lose them."""
        now = self._clock()
        last = self._loki_polled.get(source.source_id)
        if last is not None and now - last < POLL_EVERY:
            return 0, prev.behind_s
        self._loki_polled[source.source_id] = now
        if source.loki is None:
            raise SourceRejectedError("This Loki source has no settings")
        client = self.loki_client(source.loki, self._sources.connector_secret(source.source_id))
        result = loki_poll(client, source.loki, Position.load(self._position(source)), now)
        normalizer = self._normalizer(source)
        rows: list[dict[str, Any]] = []
        for item in result.lines:
            data = item.line.encode("utf-8", "replace")
            frame = Frame(data=data[:MAX_LINE], truncated=len(data) > MAX_LINE)
            row = normalizer.normalize(decode_frame(frame))
            if row is None:
                continue
            env = _json_object(row.get("envelope"))
            env["loki_labels"] = item.labels
            row["envelope"] = json.dumps(env, separators=(",", ":"))
            if row.get("time") is None:  # no timestamp in the line: Loki's is the next best
                row["time"] = from_ns(item.ns)
            rows.append(row)
        if rows:
            self._writer.write(rows)
        with self._meta.connect() as con:
            con.execute(
                "INSERT INTO connector_checkpoints (source_id, position, updated_at)"
                " VALUES (?, ?, ?) ON CONFLICT (source_id) DO UPDATE SET"
                " position = excluded.position, updated_at = excluded.updated_at",
                (source.source_id, result.position.dump(), now.isoformat()),
            )
        return len(rows), result.behind.total_seconds()

    def _run_api(self, source: SourceConfig, prev: SourceStatus) -> int:
        """Poll an API source and record its status; errors back off (SPEC 3.7)."""
        now = self._clock()
        sid = source.source_id
        if prev.retry_at is not None and now < prev.retry_at:
            return 0
        connector = api_connectors.for_source(
            source, self._sources.connector_secret(sid), self.api_transport
        )
        last = self._api_polled.get(sid)
        if last is not None and now - last < connector.poll_every:
            return 0
        self._api_polled[sid] = now
        count, error, retry_at = 0, None, None
        behind, warnings = prev.behind_s, prev.warnings
        try:
            pull = connector.pull(self._position(source), now)
            count = self._write_api(source, pull.records)
            self._save_position(sid, pull.checkpoint, now)
            behind, warnings = pull.behind_s, tuple(w[:300] for w in pull.warnings[:10])
            self._api_failures.pop(sid, None)
        except ConnectorError as exc:
            failures = self._api_failures.get(sid, 0) + 1
            self._api_failures[sid] = failures
            wait = exc.seconds if isinstance(exc, RetryLaterError) else None
            retry_at = now + backoff(failures, connector.poll_every, wait)
            error = str(exc)[:500]
        with self._lock:
            self._status[sid] = replace(
                prev,
                last_pass_at=now,
                last_event_at=now if count else prev.last_event_at,
                events_last_pass=count,
                events_since_start=prev.events_since_start + count,
                error=error,
                behind_s=behind,
                warnings=warnings,
                retry_at=retry_at,
            )
        return count

    def _write_api(self, source: SourceConfig, records: list[Any]) -> int:
        """Each record is one line for the parser, written before the checkpoint moves."""
        normalizer = self._normalizer(source)
        rows: list[dict[str, Any]] = []
        for rec in records:
            data = rec.text.encode("utf-8", "replace")
            frame = Frame(data=data[:MAX_LINE], truncated=len(data) > MAX_LINE)
            row = normalizer.normalize(decode_frame(frame))
            if row is None:
                continue
            if row.get("time") is None and rec.time is not None:
                row["time"] = rec.time
            rows.append(row)
        if rows:
            self._writer.write(rows)
        return len(rows)

    def _save_position(self, source_id: str, position: str, now: datetime) -> None:
        with self._meta.connect() as con:
            con.execute(
                "INSERT INTO connector_checkpoints (source_id, position, updated_at)"
                " VALUES (?, ?, ?) ON CONFLICT (source_id) DO UPDATE SET"
                " position = excluded.position, updated_at = excluded.updated_at",
                (source_id, position, now.isoformat()),
            )

    def _drop_read_spool(self, source: SourceConfig, paths: list[Path]) -> list[Path]:
        """Delete spool files that are fully read and no longer written (an older hour),
        so the spool holds only what ingest has not reached yet. Returns what is left."""
        keep: list[Path] = []
        current = spool_name(self._clock(), source.kind)
        for path in paths:
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                continue
            cp = self._checkpoint(source.source_id, path_key(path))
            if path.name < current and cp is not None and cp["offset"] >= size:
                key = path_key(path)
                path.unlink(missing_ok=True)
                with self._meta.connect() as con:
                    con.execute(
                        "DELETE FROM checkpoints WHERE source_id = ? AND path = ?",
                        (source.source_id, key),
                    )
                continue
            keep.append(path)
        return keep

    def _position(self, source: SourceConfig) -> str | None:
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT position FROM connector_checkpoints WHERE source_id = ?",
                (source.source_id,),
            ).fetchone()
        return None if row is None else str(row["position"])

    def _prune(self, source_id: str, listed: set[tuple[str, str]]) -> None:
        """Forget per-file state for files this source no longer lists (rotated away)."""
        for table in (self._skipped, self._short, self._gaps):
            for key in [k for k in table if k[0] == source_id and k not in listed]:
                del table[key]

    def status(self) -> dict[str, SourceStatus]:
        with self._lock:
            out = dict(self._status)
        # A syslog listener that cannot bind its port is this source's error (ADR-0021).
        for sid, error in (self.listener_errors() if self.listener_errors else {}).items():
            out[sid] = replace(out.get(sid) or SourceStatus(), error=error)
        return out

    def _ingest_file(self, source: SourceConfig, path: Path) -> int:
        if source.kind == "syslog":
            return self._ingest_syslog_spool(source, path)
        if self._framing(source) == "evtx":
            return self._ingest_evtx(source, path)
        stat = path.stat()
        inode, size = stat.st_ino, stat.st_size
        checkpoint = self._checkpoint(source.source_id, path_key(path))
        offset = 0
        csv_header = None
        skipping = False
        if checkpoint is not None and checkpoint["inode"] == inode and checkpoint["offset"] <= size:
            offset = checkpoint["offset"]
            csv_header = checkpoint["csv_header"]
            skipping = bool(checkpoint["skip_to_newline"])
        if offset >= size:
            return 0

        with open_regular(path, self._sources.read_roots()) as fh:
            fh.seek(offset)
            data = fh.read(READ_LIMIT)

        if skipping:
            # Still inside an over-long line already emitted as truncated: drop its tail.
            nl = data.find(b"\n")
            if nl < 0:
                self._save_checkpoint(
                    source.source_id, path_key(path), inode, offset + len(data), csv_header, True
                )
                return 0
            offset += nl + 1
            data = data[nl + 1 :]
            skipping = False

        end = data.rfind(b"\n")
        oversized: Frame | None = None
        if end < 0:
            if len(data) < READ_LIMIT:
                self._save_checkpoint(
                    source.source_id, path_key(path), inode, offset, csv_header, False
                )
                return 0  # no complete line yet
            # A single line longer than one read (review finding S4): emit its start as a
            # truncated event, then skip to the next newline on later passes.
            oversized = Frame(data=data[:MAX_LINE], truncated=True)
            complete = b""
            consumed = len(data)
            skipping = True
        else:
            complete = data[: end + 1]
            consumed = len(complete)

        normalizer = self._normalizer(source)
        generic_csv = source.format == "csv" and source.template_id is None
        if generic_csv and csv_header is not None:
            normalizer.normalize(DecodedLine(text=csv_header, bytes_invalid=False, truncated=False))
        rows: list[dict[str, Any]] = []
        frames = (
            list(Framer(max_len=MAX_LINE, mode="newline").frames([complete])) if complete else []
        )
        if oversized is not None:
            frames.append(oversized)
        for frame in frames:
            line = decode_frame(frame)
            if generic_csv and csv_header is None:
                csv_header = line.text
            row = normalizer.normalize(line)
            if row is not None:
                rows.append(row)
        if rows:
            self._writer.write(rows)
        self._save_checkpoint(
            source.source_id, path_key(path), inode, offset + consumed, csv_header, skipping
        )
        return len(rows)

    def _ingest_syslog_spool(self, source: SourceConfig, path: Path) -> int:
        """Records the syslog listener spooled (ADR-0021 row 2): a JSON header line with the
        message length, sender, and truncation flag, then the message bytes and a newline.
        Only whole records are read; the checkpoint stops at the last one."""
        stat = path.stat()
        inode, size = stat.st_ino, stat.st_size
        checkpoint = self._checkpoint(source.source_id, path_key(path))
        offset = 0
        if checkpoint is not None and checkpoint["inode"] == inode and checkpoint["offset"] <= size:
            offset = checkpoint["offset"]
        if offset >= size:
            return 0
        with open_regular(path, self._sources.read_roots()) as fh:
            fh.seek(offset)
            data = fh.read(READ_LIMIT + SPOOL_HEADER_MAX)
        normalizer = self._normalizer(source)
        rows: list[dict[str, Any]] = []
        pos = 0
        damaged = False
        while pos < len(data):
            nl = data.find(b"\n", pos, pos + SPOOL_HEADER_MAX)
            if nl < 0:
                damaged = len(data) - pos >= SPOOL_HEADER_MAX  # no header where one must be
                break
            try:
                head = json.loads(data[pos:nl])
                n, sender, cut = int(head["n"]), head.get("ip"), bool(head.get("t"))
            except (ValueError, KeyError, TypeError):
                damaged = True
                break
            if not 0 <= n <= SYSLOG_MAX_MESSAGE or not (
                sender is None or (isinstance(sender, str) and len(sender) <= 45)
            ):
                damaged = True
                break
            end = nl + 1 + n
            if end + 1 > len(data):
                break  # the rest of this record is not written or read yet
            if data[end : end + 1] != b"\n":
                damaged = True
                break
            line = decode_frame(Frame(data=data[nl + 1 : end], truncated=cut))
            pos = end + 1
            row = normalizer.normalize(line)
            if row is None:
                continue
            if row.get("device_ip") is None and isinstance(sender, str):
                row["device_ip"] = sender  # what the network saw (ADR-0021 row 5)
            rows.append(row)
        if rows:
            self._writer.write(rows)
        self._save_checkpoint(source.source_id, path_key(path), inode, offset + pos, None, False)
        if damaged:
            # Never resync inside message bodies: senders control those bytes and could
            # plant a header there. Set the rest of the file aside and say so.
            path.rename(path.with_name(path.name + ".damaged"))
            log.warning("syslog_spool_damaged", source_id=source.source_id)
            raise OSError(errno.EIO, "spool file damaged after a crash or full disk; set aside")
        return len(rows)

    def _framing(self, source: SourceConfig) -> str:
        if source.template_id is None or self._templates is None:
            return "lines"
        template = self._templates.get(source.template_id)
        return template.framing.mode if template is not None else "lines"

    def _ingest_evtx(self, source: SourceConfig, path: Path) -> int:
        """Records after the checkpoint's record id, in id order, one bounded batch per pass.

        `offset` holds the last record id written and `content_digest` that record's digest.
        The file is identified by content, not inode: copy tools replace files (new inode,
        same log), and an in-place copy can bring a different log (same inode). A file whose
        signature (size, file header, chunk id ranges) matches the one saved after a complete
        read is skipped unparsed. A file shorter than its header says is a copy in progress
        and is left for a later pass.
        The checkpoint is dropped, and the file read from the start, when the record at the
        checkpoint id has different content or every id is below the checkpoint.
        """
        with open_regular(path, self._sources.read_roots()) as fh:
            stat = os.fstat(fh.fileno())
            signature = file_signature(fh)
            checkpoint = self._checkpoint(source.source_id, path_key(path))
            after, digest = 0, None
            if checkpoint is not None:
                if checkpoint["file_signature"] == signature:
                    return 0
                after, digest = checkpoint["offset"], checkpoint["content_digest"]
            batch = self._evtx.read(fh, after)
            key = (source.source_id, path_key(path))
            if batch.short and not self._short_settled(key, stat.st_size):
                return 0  # a copy still in progress: read it once it is whole
            if self._short.pop(key, None) is not None and batch.short:
                log.warning("evtx_short_file_read", source_id=source.source_id)
            different = digest is not None and batch.after_digest not in (None, digest)
            if after and (different or batch.highest_id < after):
                log.info("evtx_checkpoint_reset", source_id=source.source_id)
                after = 0
                batch = self._evtx.read(fh, after)
        frames, digests, complete, unreadable = (
            batch.frames,
            batch.digests,
            batch.complete,
            batch.unreadable,
        )
        if batch.gap is None:
            self._gaps.pop(key, None)
        elif not self._gap_settled(key, batch.gap):
            # Ids no chunk header lists yet, between two chunks: usually a chunk Windows was
            # still writing when the file was copied. Moving the checkpoint past them would
            # lose them for good, so it stops just before the gap until they appear.
            kept = sum(1 for i, _ in frames if i < batch.gap[0])
            frames, digests, complete = frames[:kept], digests[:kept], False
        else:
            self._gaps.pop(key, None)
            unreadable += batch.gap[1] - batch.gap[0] + 1
            log.warning("evtx_gap_passed", source_id=source.source_id, ids=batch.gap)
        normalizer = self._normalizer(source)
        rows: list[dict[str, Any]] = []
        for _, frame in frames:
            row = normalizer.normalize(decode_frame(frame))
            if row is not None:
                rows.append(row)
        if rows:
            self._writer.write(rows)
        self._skipped[key] = unreadable
        if unreadable:
            log.warning("evtx_records_skipped", source_id=source.source_id, count=unreadable)
        if frames:
            after, digest = frames[-1][0], digests[-1]
        self._save_checkpoint(
            source.source_id,
            path_key(path),
            stat.st_ino,
            after,
            None,
            False,
            file_signature=signature if complete else None,
            content_digest=digest,
        )
        return len(rows)

    def _gap_settled(self, key: tuple[str, str], gap: tuple[int, int]) -> bool:
        """True once the same id gap has stayed for SHORT_EVTX_GRACE: records lost, not late."""
        now = self._clock()
        seen = self._gaps.get(key)
        if seen is None or seen[0] != gap:
            self._gaps[key] = (gap, now)
            return False
        return now - seen[1] >= SHORT_EVTX_GRACE

    def _short_settled(self, key: tuple[str, str], size: int) -> bool:
        """True once a short .evtx has kept the same size for SHORT_EVTX_GRACE."""
        now = self._clock()
        seen = self._short.get(key)
        if seen is None or seen[0] != size:
            self._short[key] = (size, now)
            return False
        return now - seen[1] >= SHORT_EVTX_GRACE

    def _normalizer(self, source: SourceConfig) -> Normalizer | TemplateNormalizer | AutoNormalizer:
        if source.template_id is None:
            return Normalizer(source.spec(), clock=self._clock)
        if source.template_id == AUTO_PARSER:
            # The registry as it is now: a template approved later is used from the next pass.
            reg = self._templates
            return AutoNormalizer(
                source.spec(),
                reg.all() if reg else [],
                reg.starter_ids if reg else frozenset(),
                clock=self._clock,
                tables=reg.tables if reg else None,
            )
        template = self._templates.get(source.template_id) if self._templates else None
        if template is None:
            # Never fall back silently: the source shows an error until the template exists.
            raise SourceRejectedError(f"Template {source.template_id} is not available")
        envelope = template.envelope.syslog.model_copy(update={"timezone": source.timezone})
        return TemplateNormalizer(
            template,
            source.source_id,
            source.classification,
            envelope=envelope,
            clock=self._clock,
            tables=self._templates.tables if self._templates else None,
        )

    def _checkpoint(self, source_id: str, path: str) -> Any:
        with self._meta.connect() as con:
            return con.execute(
                "SELECT inode, offset, csv_header, skip_to_newline, file_signature, content_digest"
                " FROM checkpoints"
                " WHERE source_id = ? AND path = ?",
                (source_id, path),
            ).fetchone()

    def _save_checkpoint(
        self,
        source_id: str,
        path: str,
        inode: int,
        offset: int,
        csv_header: str | None,
        skip_to_newline: bool,
        file_signature: str | None = None,
        content_digest: str | None = None,
    ) -> None:
        with self._meta.connect() as con:
            con.execute(
                "INSERT INTO checkpoints (source_id, path, inode, offset, csv_header,"
                " skip_to_newline, file_signature, content_digest, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (source_id, path) DO UPDATE SET inode = excluded.inode,"
                " offset = excluded.offset, csv_header = excluded.csv_header,"
                " skip_to_newline = excluded.skip_to_newline,"
                " file_signature = excluded.file_signature,"
                " content_digest = excluded.content_digest, updated_at = excluded.updated_at",
                (
                    source_id,
                    path,
                    inode,
                    offset,
                    csv_header,
                    int(skip_to_newline),
                    file_signature,
                    content_digest,
                    self._clock().isoformat(),
                ),
            )


def _json_object(text: Any) -> dict[str, Any]:
    if not text:
        return {}
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}
