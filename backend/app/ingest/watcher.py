"""Tail/watch ingest (SPEC 3.5).

Polls each enabled source's files, reads only complete new lines from the last
position, and writes them through the normal pipeline. A text file's position belongs to
the file, not its name (ADR-0051, `ingest/positions.py`): a renamed file keeps it, and a
file emptied and refilled in place is read from its start with a warning.
Delivery is at-least-once: the position advances after the lake write.
"""

import errno
import json
import os
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO, Literal

import httpx
import structlog

from app.alerts.fallback import SourceFallbacks, fallback_error, is_fallback_error
from app.alerts.stops import DetectionStops
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
from app.ingest.handles import HeldHandles, closing
from app.ingest.integrity import LakeEvents
from app.ingest.labels import labels_envelope
from app.ingest.normalizer import Normalizer, TemplateMissingNormalizer
from app.ingest.otlp import spool_full
from app.ingest.positions import (
    NOT_DRAINED,
    FilePosition,
    FilePositions,
    content_hashes,
    same_content,
)
from app.ingest.records import DecodedLine, Frame, decode_frame, mark_part_line
from app.ingest.skew import SkewTracker
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
from app.templates.tables import LookupTable
from app.templates.validator import Template

log = structlog.get_logger(__name__)

# An .evtx shorter than its header says is usually a copy still being written. If its size
# has not changed for this long it is read as it is (a truncated transfer would otherwise
# never be ingested), and the chunks it lacks are simply not there.
SHORT_EVTX_GRACE = timedelta(minutes=10)
SYSLOG_MAX_MESSAGE = 65_536  # the listener never spools a longer message
SPOOL_HEADER_MAX = 256  # bytes: a syslog spool record header is far shorter
READ_LIMIT = 8 << 20  # bytes per file per pass, so one huge file cannot starve the rest
UNDO_REASON = "ingest: the position was not saved, so the lines are read again"
MAX_LINE = 65_536
POSITION_KEEP = timedelta(days=30)  # a file not listed or read this long loses its record
SEEN_EVERY = timedelta(days=1)  # how often an idle listed file is noted as still there
PART_LINE_WAIT = timedelta(minutes=5)  # a last line without its newline waits this long
RESTART_WARNING = timedelta(days=1)  # how long a refilled file stays a warning


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
    # Event times look this many hours off (positive: early), steadily (ingest/skew.py).
    time_offset_h: float | None = None
    # Files this source lists that another source reads (one reader per file, D273), as
    # (file name, that source, whether both are equally specific), from the last pass; and
    # that source when it reads every file this one lists, so this one stores nothing: a
    # state of its own, not a problem, and no quiet alert.
    shared: tuple[tuple[str, str, bool], ...] = ()
    read_by: str | None = None


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


def template_normalizer(
    source: SourceConfig,
    template: Template,
    tables: Mapping[str, LookupTable] | None,
    clock: Callable[[], datetime],
) -> TemplateNormalizer:
    """How ingest parses a source's lines with its template (also used by a reparse,
    ADR-0050 row 7): the source's time zone wins over the template's."""
    envelope = template.envelope.syslog.model_copy(update={"timezone": source.timezone})
    return TemplateNormalizer(
        template,
        source.source_id,
        source.classification,
        envelope=envelope,
        clock=clock,
        tables=tables,
    )


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
        # Files written whose position is not saved yet, and files an undo could not
        # remove yet (the ledger could not be written): see `_write`.
        self._unsaved: list[Path] = []
        self._stuck: list[Path] = []
        # Event times a whole number of hours off: a time zone to check (trial finding).
        self.skew = SkewTracker()
        self._evtx = EvtxReader(max_len=MAX_LINE)
        self._clock = clock
        self._status: dict[str, SourceStatus] = {}
        self._skipped: dict[tuple[str, str], int] = {}  # (source, path key) -> latest read
        # (source, path key) -> (size, first seen at that size) for short .evtx files
        self._short: dict[tuple[str, str], tuple[int, datetime]] = {}
        # (source, path key) -> (gap, first seen) for .evtx files held before an id gap
        self._gaps: dict[tuple[str, str], tuple[tuple[int, int], datetime]] = {}
        # Text files: one position per file (ADR-0051), and the files that were emptied and
        # refilled in place, by source: (file name, when), shown as a warning for a day.
        self._positions = FilePositions(meta, clock)
        self._positions_copied = False
        # Files whose position from before the update could not be taken yet (missing or
        # unreadable then): settled before such a file is first read.
        self._owed: set[tuple[str, str]] = set()
        self._owed_tried = False  # in this pass
        # Text files read from lately, kept open to follow a rename (ADR-0051 row 3).
        self._handles = HeldHandles()
        # Names given to a new file while the server was down (ADR-0051 row 4), by source:
        # (file name, old file last read, noticed), shown as a warning for a day.
        self._maybe_missed: list[tuple[str, FilePosition]] = []
        # Inode numbers of the files each source listed since this process started.
        self._seen_inodes: dict[str, set[int]] = {}
        self._missed: dict[str, tuple[list[str], str, datetime]] = {}
        self._restarted: dict[str, tuple[str, datetime, bool]] = {}
        # This source's files that another source reads, in this pass: path -> (name,
        # reader, whether the two are equally specific).
        self._skips: dict[str, tuple[str, str, bool]] = {}
        self._enabled: set[str] = set()  # turned-on sources, as of this pass
        # One reader per file (D273), from configuration each pass: (device, inode) -> the
        # most specific turned-on source that lists it, with its rank; and what each file
        # source listed for it.
        self._holders: dict[tuple[int, int], tuple[tuple[int, str, str], str]] = {}
        self._listed: dict[str, list[Path]] = {}
        self._ranks: dict[str, int] = {}
        # Each listed name -> the rank keys of the sources that list it, so a file that
        # appears under a name during the pass (a rotation) goes to the same holder.
        self._by_name: dict[str, list[tuple[int, str, str]]] = {}
        # The holder the rule named for each file in the last pass (before a rename).
        self._named: dict[tuple[int, int], str] = {}
        self._lock = threading.Lock()
        # Set by the app: source id -> why its syslog listener is not listening.
        self.listener_errors: Callable[[], dict[str, str]] | None = None
        # Set by the app: a source that stops reading is never silent (D33 as amended).
        self.stops: DetectionStops | None = None
        self.fallbacks: SourceFallbacks | None = None  # ADR-0050 row 5 messages
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
        self._retry_stuck()  # every pass, not only when the next write comes
        self._owed_tried = False
        self._enabled = {s.source_id for s in self._sources.list() if s.enabled}
        self._handles.expire(self._clock(), self._enabled)
        self._find_holders()
        # What the path-keyed table knows and the positions do not, at each start.
        if not self._positions_copied:
            self._owed = self._take_checkpoints(start=True)
            self._positions_copied = True
            self._owed_tried = True  # just looked at every file
        before = {sid: st.events_since_start for sid, st in self.status().items()}
        missing_at_start: dict[str, bool] = {}
        for source in self._sources.list():
            if not source.enabled:
                # Turned off: no files another source reads are known now (Paused, not
                # "Read by"), so nothing stale outlives the pass that found them.
                with self._lock:
                    off = self._status.get(source.source_id)
                    if off is not None and (off.shared or off.read_by):
                        self._status[source.source_id] = replace(off, shared=(), read_by=None)
                continue
            missing_at_start[source.source_id] = self._missing_error(source) is not None
            self._maybe_missed = []
            self._skips = {}
            prev = self.status().get(source.source_id, SourceStatus())
            count, files, error = 0, 0, None
            skipped, waiting = prev.records_skipped, prev.files_waiting
            try:
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
                            error=self._missing_error(source),
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
                    paths = self._listed.get(source.source_id) or files_for(
                        source, self._sources.allowed_roots
                    )
                files = len(paths)
                failed: list[str] = []
                for path in paths:
                    # One unreadable file is reported and skipped; the others are still read.
                    try:
                        try:
                            count += self._ingest_file(source, path)
                        except BaseException:
                            self._undo_unsaved()  # written, but its position was not saved
                            raise
                    except FileNotFoundError:
                        continue  # rotated or removed since it was listed
                    except OSError as exc:
                        reason = exc.strerror or type(exc).__name__
                        failed.append(f"{display_name(path.name)[:100]}: {reason}")
                    except Exception as exc:  # one file must not stop the rest
                        log.exception("ingest_file_failed", source_id=source.source_id)
                        failed.append(f"{display_name(path.name)[:100]}: {type(exc).__name__}")
                if self._is_text(source):
                    try:
                        count += self._follow_renamed(source)
                    except BaseException:
                        self._undo_unsaved()  # written, but its position was not saved
                        raise
                    self._note_missed(source.source_id)
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
                # A single file renamed or deleted with no new file yet: the path does not
                # exist, and the held file is still read to its end.
                if self._is_text(source):
                    count += self._follow_safely(source)
            except OSError as exc:
                error = f"Cannot read: {exc.strerror or type(exc).__name__}"
            except Exception as exc:  # one source must not stop the others
                log.exception("ingest_source_failed", source_id=source.source_id)
                error = f"Ingest failed: {type(exc).__name__}"
            self._undo_unsaved()  # a Loki or API write whose position was not saved
            error = error or self._missing_error(source)
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
                    warnings=(
                        *self._restart_warning(source.source_id, now),
                        *self._missed_warning(source.source_id, now),
                    ),
                    **self._shared_status(source.source_id, prev, files),
                )
            total += count
        self._report_stops()
        self._report_fallbacks(before, missing_at_start)
        return total

    def _report_fallbacks(self, before: dict[str, int], missing_at_start: dict[str, bool]) -> None:
        """ADR-0050 row 5: one message when a source starts storing without its parser and
        one when its template loads again, with the count stored meanwhile."""
        if self.fallbacks is None:
            return
        enabled = [s for s in self._sources.list() if s.enabled]
        status = self.status()
        for source in enabled:
            sid = source.source_id
            missing = source.template_id if self._missing_error(source) else None
            st = status.get(sid)
            stored = (st.events_since_start if st else 0) - before.get(sid, 0)
            # Counted as stored without the parser when it was missing as the pass began,
            # even if the template was approved during the pass.
            without = stored if missing_at_start.get(sid) else 0
            self.fallbacks.update(sid, missing, without, source.template_id)
        self.fallbacks.forget(s.source_id for s in enabled)

    def _report_stops(self) -> None:
        """A source that cannot read (files, spool, listener, Loki, API connector) sends one
        "Detection stopped" message once it has lasted the grace, and one "running again"
        message when it reads again. A missing template is not a stop (ADR-0050 messages)."""
        if self.stops is None:
            return
        enabled = [s.source_id for s in self._sources.list() if s.enabled]
        status = self.status()
        for sid in enabled:
            st = status.get(sid)
            where = f"health#source={sid}"
            # A missing parser is not a stop: events are still stored, and ADR-0050's own
            # start and back messages cover it (owner, 2026-11-11). Never silent either way.
            if st is not None and st.error and not is_fallback_error(st.error):
                self.stops.failing(f"source:{sid}", f"Source {sid}", st.error, where)
            else:
                self.stops.working(f"source:{sid}", where)
        self.stops.forget("source:", [f"source:{sid}" for sid in enabled])

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
            hint = labels_envelope(item.labels, source.loki.label_map)
            row = normalizer.normalize(replace(decode_frame(frame), hint=hint))
            if row is None:
                continue
            env = _json_object(row.get("envelope"))
            env["loki_labels"] = item.labels
            row["envelope"] = json.dumps(env, separators=(",", ":"))
            if row.get("time") is None:  # no timestamp in the line: Loki's is the next best
                row["time"] = from_ns(item.ns)
            rows.append(row)
        if rows:
            self._write(source.source_id, rows)
        with self._meta.connect() as con:
            con.execute(
                "INSERT INTO connector_checkpoints (source_id, position, updated_at)"
                " VALUES (?, ?, ?) ON CONFLICT (source_id) DO UPDATE SET"
                " position = excluded.position, updated_at = excluded.updated_at",
                (source.source_id, result.position.dump(), now.isoformat()),
            )
        self._unsaved = []
        return len(rows), result.behind.total_seconds()

    def _run_api(self, source: SourceConfig, prev: SourceStatus) -> int:
        """Poll an API source and record its status; errors back off (SPEC 3.7)."""
        now = self._clock()
        sid = source.source_id
        if prev.retry_at is not None and now < prev.retry_at:
            self._refresh_missing(source, prev)
            return 0
        connector = api_connectors.for_source(
            source, self._sources.connector_secret(sid), self.api_transport
        )
        last = self._api_polled.get(sid)
        if last is not None and now - last < connector.poll_every:
            self._refresh_missing(source, prev)
            return 0
        self._api_polled[sid] = now
        count, error, retry_at = 0, None, None
        behind, warnings = prev.behind_s, prev.warnings
        try:
            pull = connector.pull(self._position(source), now)
            count = self._write_api(source, pull.records)
            self._save_position(sid, pull.checkpoint, now)
            behind, warnings = pull.behind_s, tuple(w[:300] for w in pull.warnings[:10])
            recovered = self._api_failures.pop(sid, None) is not None
            # The journal tells the story (F41): starts, feed problems, recovery, and volume.
            # Messages are the connector's own text, never event content.
            for note in pull.notices[:10]:
                log.info("connector_notice", source_id=sid, kind=source.kind, notice=note[:300])
            for w in warnings:
                if w not in prev.warnings:
                    log.warning("connector_feed_failed", source_id=sid, kind=source.kind, error=w)
            if recovered or count:
                log.info(
                    "connector_pulled",
                    source_id=sid,
                    kind=source.kind,
                    events=count,
                    behind_s=round(behind) if behind is not None else None,
                    recovered=recovered,
                )
        except ConnectorError as exc:
            failures = self._api_failures.get(sid, 0) + 1
            self._api_failures[sid] = failures
            wait = exc.seconds if isinstance(exc, RetryLaterError) else None
            retry_at = now + backoff(failures, connector.poll_every, wait)
            error = str(exc)[:500]
            log.warning(
                "connector_failed",
                source_id=sid,
                kind=source.kind,
                error=error,
                failures=failures,
                retry_in_s=round((retry_at - now).total_seconds()),
            )
        with self._lock:
            self._status[sid] = replace(
                prev,
                last_pass_at=now,
                last_event_at=now if count else prev.last_event_at,
                events_last_pass=count,
                events_since_start=prev.events_since_start + count,
                error=error or self._missing_error(source),
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
            self._write(source.source_id, rows)
        return len(rows)

    def _save_position(self, source_id: str, position: str, now: datetime) -> None:
        with self._meta.connect() as con:
            con.execute(
                "INSERT INTO connector_checkpoints (source_id, position, updated_at)"
                " VALUES (?, ?, ?) ON CONFLICT (source_id) DO UPDATE SET"
                " position = excluded.position, updated_at = excluded.updated_at",
                (source_id, position, now.isoformat()),
            )
        self._unsaved = []

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
                self._positions.drop_path(source.source_id, key)
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

    def seed_last_events(self, last: dict[str, datetime]) -> None:
        """At start, take each source's newest stored event time, so Health and Sources
        do not show "never" for a source that was reading before the restart (QA F8).
        A time the running ingest has already set is kept."""
        with self._lock:
            for sid, at in last.items():
                cur = self._status.get(sid) or SourceStatus()
                if cur.last_event_at is None:
                    self._status[sid] = replace(cur, last_event_at=at)

    def _write(self, source_id: str, rows: list[dict[str, Any]]) -> None:
        """Store rows. The caller saves its position next; until it has, the files are
        `_unsaved`, and `_undo_unsaved` takes them back if the save fails, so the retry
        does not store the batch a second time (audit 2026-11 H6)."""
        if self._retry_stuck():  # an earlier undo is still owed: nothing new until done
            raise OSError(errno.EIO, "an earlier write could not be undone yet")
        self._unsaved += self._writer.write(rows)
        self.skew.observe(source_id, rows)

    def _retry_stuck(self) -> bool:
        """Try again to take back files an undo could not remove. True while some remain."""
        if self._stuck:
            self._stuck = self._writer.discard(self._stuck, UNDO_REASON)
        return bool(self._stuck)

    def held(self) -> set[Path]:
        """Lake files ingest may still take back: compaction must not merge them."""
        return {*self._unsaved, *self._stuck}

    def _undo_unsaved(self) -> None:
        """A position was not saved after a write: remove what was written for it."""
        unsaved, self._unsaved = self._unsaved, []
        if unsaved:
            self._stuck += self._writer.discard(unsaved, UNDO_REASON)
            log.warning("ingest.write_undone", files=len(unsaved), left=len(self._stuck))

    def status(self) -> dict[str, SourceStatus]:
        with self._lock:
            out = dict(self._status)
        for sid, hours in self.skew.offsets().items():
            out[sid] = replace(out.get(sid) or SourceStatus(), time_offset_h=hours)
        # A syslog listener that cannot bind its port is this source's error (ADR-0021).
        for sid, error in (self.listener_errors() if self.listener_errors else {}).items():
            out[sid] = replace(out.get(sid) or SourceStatus(), error=error)
        # A full spool drops new messages: an error, so Health and the never-silent check
        # see it (D33 as amended).
        for sid, st in list(out.items()):
            if st.error is None and spool_full(sid):
                out[sid] = replace(st, error="Spool full: new messages are being refused")
        return out

    def _take_checkpoints(self, start: bool) -> set[tuple[str, str]]:
        return self._positions.take_checkpoints(
            {s.source_id for s in self._sources.list() if self._is_text(s)},
            self._sources.read_roots(),
            start,
        )

    def _is_text(self, source: SourceConfig) -> bool:
        """A source whose files `_ingest_text` reads line by line: file sources and OTLP
        spools, but not a syslog spool and not .evtx."""
        return source.kind in ("file", "otlp") and self._framing(source) != "evtx"

    def _restart_warning(self, source_id: str, now: datetime) -> tuple[str, ...]:
        """For a day after a file was emptied and refilled in place: what happened, which
        file, and what to change (D250). Health and Sources show a source's warnings."""
        found = self._restarted.get(source_id)
        if found is None or now - found[1] > RESTART_WARNING:
            self._restarted.pop(source_id, None)
            return ()
        if found[2]:  # the watcher still held the file: it is the same file, emptied
            return (
                f"{found[0]} was emptied and refilled in place, so it was read again from its"
                " start. Lines written during such a rotation can be lost: rotate with create,"
                " not copytruncate.",
            )
        return (
            f"{found[0]} was read again from its start: it was emptied and refilled in place,"
            " or replaced by a new file. If it is rotated with copytruncate, lines written"
            " during a rotation can be lost: rotate with create.",
        )

    def _ingest_file(self, source: SourceConfig, path: Path) -> int:
        if source.kind == "syslog":
            return self._ingest_syslog_spool(source, path)
        if self._framing(source) == "evtx":
            return self._ingest_evtx(source, path)
        return self._ingest_text(source, path)

    def _ingest_text(self, source: SourceConfig, path: Path) -> int:
        """New complete lines of one text file, from its own position (ADR-0051, D250).

        The position belongs to the file, not the name. A file whose size and modified
        time are as they were when it was last read to its end is not opened. Any other
        file is opened first and identified from the open handle, so a rotation between
        listing and reading cannot mix two files; its position is used only when the
        content matches, and otherwise it is read from its start. The handle is then kept
        for a while (`ingest/handles.py`), so the file can be read to its end after its
        name is given to another."""
        sid, key = source.source_id, path_key(path)
        seen = path.stat()
        if self._read_by_other(sid, (seen.st_dev, seen.st_ino), path, key):
            return 0
        if (sid, key) in self._owed and not self._owed_tried:
            # Here now: its old position first, if it has one. Once a pass, for every owed
            # file together: one that is listed but still cannot be opened stays owed.
            self._owed = self._take_checkpoints(start=False)
            self._owed_tried = True
        known = self._positions.get(sid, seen.st_dev, seen.st_ino)
        flush = False
        self._seen_inodes.setdefault(sid, set()).add(seen.st_ino)
        if known is not None and (
            not known.seen_at or self._clock() - datetime.fromisoformat(known.seen_at) >= SEEN_EVERY
        ):
            # Once a day a file that is listed is noted as still there (idle, or not
            # readable just now), so the 30-day sweep leaves its record alone. Its name is
            # left as recorded: only a file known to be unchanged is taken as renamed.
            self._positions.seen_at(known, known.path)
        if known is not None and (known.size, known.mtime_ns) == (seen.st_size, seen.st_mtime_ns):
            if known.path != key:
                self._positions.seen_at(known, key)  # renamed: only where it is changes
            # Idle. A last line without its newline has waited long enough when the file
            # has not grown for PART_LINE_WAIT: it is stored as it is (row 5).
            flush = (
                known.offset < known.size
                and not known.skip_to_newline
                and bool(known.updated_at)
                and self._clock() - datetime.fromisoformat(known.updated_at) >= PART_LINE_WAIT
            )
            if not flush:
                return 0
        fh = open_regular(path, self._sources.read_roots())
        try:
            info = os.fstat(fh.fileno())
            file = (sid, info.st_dev, info.st_ino)
            # Grew or changed since it was looked at: its last line is not waiting any more.
            flush = flush and (info.st_size, info.st_ino) == (seen.st_size, seen.st_ino)
            self._seen_inodes.setdefault(sid, set()).add(info.st_ino)
            if self._read_by_other(sid, file[1:], path, key):  # not the file listed
                fh.close()
                return 0
            mine = self._positions.for_file(info.st_dev, info.st_ino, sid)
            pos = next((p for p in mine if p.device == info.st_dev), None)
            moved_from: FilePosition | None = None
            if pos is None:
                # Not known under this device number, which a restart or remount can
                # change: the same inode with matching content is the same file, under any
                # name (it may have been rotated meanwhile).
                # Saving it below moves the record to the new number.
                pos = next(
                    (p for p in mine if p.offset and same_content(fh, p, info.st_size)), None
                )
                moved_from = pos
            if pos is None:
                # A new file. If its name was another file's and this process has never
                # seen that file (not listed since the start, so not held either), it was
                # rotated while the server was down, and what was written to it last may
                # never be read (row 4): decided once the source's files are all listed.
                # A file seen since the start is no such case: a rotation is followed
                # through the held file, and a quiet file whose handle was closed had
                # nothing unread when it was last looked at.
                named = self._positions.at_path(sid, key)
                before = [p for p in named if p.offset]
                # Known under another device number with nothing read yet (D251): this
                # very file, not a new one.
                if before and not any(p.inode == info.st_ino for p in named):
                    last = max(before, key=lambda p: p.updated_at)
                    if self._handles.get((sid, last.device, last.inode)) is None:
                        self._maybe_missed.append((display_name(path.name)[:100], last))
            start = self._start(sid, fh, info)
            if start is None and pos is not None and pos.path == key and pos.offset:
                # The same name and inode with other content: emptied and refilled in
                # place (logrotate `copytruncate`), or a new file that was given the
                # deleted one's inode number. While the watcher still holds the file the
                # number cannot have been given away, so it is the first; otherwise the
                # two cannot be told apart. With copytruncate, lines written between the
                # copy and the truncate are gone before anything can read them, so Health
                # is told.
                held = self._handles.get(file) is not None
                self._restarted[sid] = (display_name(path.name)[:100], self._clock(), held)
                log.warning("ingest.file_restarted", source_id=sid, held=held)
            n = self._advance(source, fh, key, start, flush=flush, legacy=True, replaces=moved_from)
        except BaseException:
            fh.close()
            raise
        self._handles.keep(file, fh, path, key, self._clock())
        return n

    def _find_holders(self) -> None:
        """The holder of each file listed by two or more turned-on sources (D273), from
        their configuration only, so a rotation, a restart, a truncation, or a device change
        cannot move it: the most specific source that lists it (its path names the file,
        then a folder with a pattern, then a recursive pattern), then the source added
        first, then the lower id. One exception, ADR-0051 row 3: a file renamed away from its
        name is read to its end by the source this rule named for it before the rename,
        through the file it holds open. A source holding a file it is no longer the holder
        of (a more specific source was added) closes it."""
        created = self._sources.created()
        self._holders, self._listed, self._ranks, self._by_name = {}, {}, {}, {}
        files = [s for s in self._sources.list() if s.enabled and s.kind == "file"]
        files = [s for s in files if self._is_text(s)]  # .evtx: not covered yet (D273)
        for source in files:
            try:
                paths = files_for(source, self._sources.allowed_roots)
            except Exception:  # noqa: S112  # any failure: said by the source's own pass below
                continue  # left out of the holders; one source never stops another
            self._listed[source.source_id] = paths
            rank = 0 if os.path.isfile(source.path) else 2 if "**" in source.glob else 1
            self._ranks[source.source_id] = rank
            key = (rank, created.get(source.source_id, ""), source.source_id)
            for path in paths:
                self._by_name.setdefault(path_key(path), []).append(key)
                try:
                    st = path.stat()
                except OSError:
                    continue
                here = (st.st_dev, st.st_ino)
                if here not in self._holders or key < self._holders[here][0]:
                    self._holders[here] = (key, source.source_id)
        named = {here: found[1] for here, found in self._holders.items()}
        for source in files:  # also while the source's own path is missing (mid-rotation)
            sid = source.source_id
            for file, held in self._handles.items(sid):
                here = file[1:]
                try:
                    there = os.stat(held.path)
                    renamed = (there.st_dev, there.st_ino) != here
                except OSError:
                    renamed = True
                if renamed and self._named.get(here) == sid:
                    self._holders[here] = ((-1, "", sid), sid)
                    named[here] = sid  # still its file until the handle is closed
                elif (renamed or named.get(here, sid) != sid) and self._handles.get(file):
                    self._handles.drop(file)  # a former reader: no longer the holder
        self._named = named

    def _read_by_other(self, sid: str, here: tuple[int, int], path: Path, key: str | None) -> bool:
        """Does another source read this file (D273)? Decided when `sid` is about to read
        it, by the rule over the sources that list it: under this name (a file rotated in
        during the pass goes where the name goes) or under any name found for it this pass
        (a link). Then `sid` skips it, and a listed one (`key`) is noted for its status. A
        file no source lists goes to the first that reads it. Two files with the same lines
        are two files."""
        named = [(k, k[2]) for k in self._by_name.get(path_key(path), [])]
        known = self._holders.get(here)
        if known is None and not named:
            self._holders[here] = ((-2, "", sid), sid)
            return False
        found = min([*named, *([known] if known else [])])
        if found[1] == sid:
            return False
        if key is not None:
            tie = self._ranks.get(sid) == found[0][0]
            self._skips[key] = (display_name(path.name)[:100], found[1], tie)
        return True

    def _shared_status(self, sid: str, prev: SourceStatus, files: int) -> dict[str, Any]:
        """The source's files another source reads, from this pass, and that source when it
        reads every file this one lists."""
        shared = tuple(self._skips[k] for k in sorted(self._skips))  # by path: one per file
        readers = {reader for _, reader, _ in self._skips.values()}
        read_by = min(readers) if files and len(self._skips) >= files else None
        if shared != prev.shared and shared:
            log.warning("ingest.file_read_by_other_source", source_id=sid, others=sorted(readers))
        return {"shared": shared, "read_by": read_by}

    def _start(self, sid: str, fh: BinaryIO, info: os.stat_result) -> FilePosition | None:
        """Where `sid` reads this open text file from, on every path (a listed file, a
        held one after a rename, a takeover): the furthest position any source saved on it
        (`FilePositions.for_file`: device and inode, the device fallback) whose content
        checks match. None: from the start."""
        found = furthest(
            self._positions.for_file(info.st_dev, info.st_ino),
            lambda p: p.offset,
            lambda p: same_content(fh, p, info.st_size),
        )
        if found is None:
            return None
        # Only the offset and its content check carry over: the CSV header (and any other
        # parse state) is the reading source's own, so taken again from the file's first
        # line when another source's position is used (fifth review of #655).
        if found.source_id != sid:
            found = replace(found, csv_header=self._first_line(fh) if found.offset else None)
        return replace(found, source_id=sid)

    @staticmethod
    def _first_line(fh: BinaryIO) -> str | None:
        """The file's first line, as `_lines` takes a CSV header."""
        fh.seek(0)
        data = fh.read(MAX_LINE + 1)
        end = data.find(b"\n")
        if end < 0:
            return None
        frame = next(iter(Framer(max_len=MAX_LINE, mode="newline").frames([data[: end + 1]])))
        return decode_frame(frame).text

    def _advance(
        self,
        source: SourceConfig,
        fh: BinaryIO,
        key: str,
        pos: FilePosition | None,
        *,
        flush: bool,
        legacy: bool,
        replaces: FilePosition | None = None,
    ) -> int:
        """Read on from `pos` (or the start), store the complete lines, and save where the
        file is now. With `flush`, a last line without its newline is stored too, as
        `parse_status=partial`: the file was rotated away, or has not grown for
        PART_LINE_WAIT (row 5). `legacy`: also write the path-keyed row of the table before
        ADR-0051, for the file its name still points to."""
        sid = source.source_id
        info = os.fstat(fh.fileno())
        offset, csv_header, skipping = (
            (pos.offset, pos.csv_header, pos.skip_to_newline) if pos else (0, None, False)
        )
        fh.seek(offset)
        data = fh.read(READ_LIMIT)
        at_end = len(data) < READ_LIMIT
        rows, consumed, csv_header, skipping = self._lines(
            source, data, csv_header, skipping, part_line=flush and at_end
        )
        if rows:
            self._write(sid, rows)
        offset += consumed
        drained = at_end and not skipping
        head, tail = content_hashes(fh, offset)
        position = FilePosition(
            sid, info.st_dev, info.st_ino, key, offset,
            info.st_size if drained else NOT_DRAINED, info.st_mtime_ns, head, tail,
            csv_header, skipping,
        )  # fmt: skip
        if legacy:
            # Saved together with its row in the table before ADR-0051, which is still
            # written so that going back a version reads on from here (row 10): both or
            # neither, and a save that fails leaves the lines to be read again (H6).
            self._save_checkpoint(
                sid, key, info.st_ino, offset, csv_header, skipping, position=position,
                replaces=replaces,
            )  # fmt: skip
        else:
            self._positions.save(position)
            self._unsaved = []
        return len(rows)

    def _note_missed(self, source_id: str) -> None:
        """After a source's files were read: a name that went to a new file while the
        server was down is a warning, unless the source lists the old file under another
        name (it is then read like any file)."""
        # By inode number alone: the device number may have changed over the restart (D251).
        seen = self._seen_inodes.get(source_id, set())
        missed = [(name, old) for name, old in self._maybe_missed if old.inode not in seen]
        self._maybe_missed = []
        if not missed:
            return
        names, since, _ = self._missed.get(source_id, ([], "", self._clock()))
        names = [*names, *(n for n, _ in missed if n not in names)]
        since = min([s for s in (since, *(old.updated_at for _, old in missed)) if s])
        self._missed[source_id] = (names, since, self._clock())
        log.warning("ingest.rotated_unwatched", source_id=source_id, files=len(names))

    def _missed_warning(self, source_id: str, now: datetime) -> tuple[str, ...]:
        found = self._missed.get(source_id)
        if found is None or now - found[2] > RESTART_WARNING:
            self._missed.pop(source_id, None)
            return ()
        names, since, _ = found
        when = datetime.fromisoformat(since).astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
        shown = ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
        were = "was" if len(names) == 1 else "were"
        return (
            f"{shown} {were} replaced by a new file while the server was not running. Lines"
            f" written to the old file after {when}, if there were any, were not read.",
        )

    def sweep_positions(self) -> int:
        """The daily maintenance: forget files not listed or read for 30 days (row 8), of
        the sources whose last pass listed their files without an error."""
        with self._lock:
            listed = {
                sid for sid, st in self._status.items() if st.last_pass_at and st.error is None
            }
        return self._positions.sweep(self._clock() - POSITION_KEEP, listed)

    def _follow_safely(self, source: SourceConfig) -> int:
        """`_follow_renamed` for a source whose listing failed: its own failure is logged,
        and what it wrote without saving is taken back."""
        try:
            return self._follow_renamed(source)
        except Exception:
            self._undo_unsaved()
            log.exception("ingest_follow_failed", source_id=source.source_id)
            return 0

    def _follow_renamed(self, source: SourceConfig) -> int:
        """Read on each held file whose name now points to another file, or to none
        (ADR-0051 row 3): renamed by a rotation, or deleted. The handle is the file,
        wherever it went. A program may keep writing to it until it is told to reopen its
        log, so the handle is held for `LINGER` after the file was first read to its end
        (D252), and what is written meanwhile is read, and `KEEP`
        after the rename was seen at the latest. When it is closed, a last line without
        its newline is stored (row 5)."""
        sid, total = source.source_id, 0
        now = self._clock()
        for file, held in self._handles.items(sid):
            if self._read_by_other(sid, file[1:], held.path, None):
                continue  # another source reads it now (it lists the new name)
            try:
                there = os.stat(held.path)
                if (there.st_dev, there.st_ino) == file[1:]:
                    # The name points to it (again): an ordinary held file, closed when
                    # it was not read from for a while.
                    held.gone_at = held.ended_at = None
                    continue
            except OSError:
                pass  # no file of that name now
            held.gone_at = held.gone_at or now
            try:
                pos = self._start(sid, held.fh, os.fstat(held.fh.fileno()))
            except OSError as exc:
                # The file cannot be read any more (deleted on a file server, a disk
                # error): it is given up, and the other held files are still followed.
                self._handles.drop(file)
                log.warning("ingest.held_file_unreadable", source_id=sid, error=type(exc).__name__)
                continue
            if pos is None:
                self._handles.drop(file)  # emptied before it went: nothing left to read on
                continue
            last = closing(held, now)
            # A failure from here on (a write or a save that fails) keeps the handle: the
            # lines are taken back and read again on the next pass (H6). Not past its
            # time: then it is closed whatever happens, as every handle is.
            try:
                total += self._advance(source, held.fh, pos.path, pos, flush=last, legacy=False)
            except BaseException:
                if last:
                    self._handles.drop(file)
                raise
            if last:
                self._handles.drop(file)
                continue
            after = self._positions.get(*file)
            if after is not None and after.size != NOT_DRAINED and held.ended_at is None:
                held.ended_at = now  # first read to its end: the 30 seconds start
        return total

    def _lines(
        self,
        source: SourceConfig,
        data: bytes,
        csv_header: str | None,
        skipping: bool,
        part_line: bool = False,
    ) -> tuple[list[dict[str, Any]], int, str | None, bool]:
        """The rows of the complete lines in `data`, how many bytes they used, and the CSV
        header and over-long-line state to carry on with. A last line without its newline
        is not used: it is read again when the newline arrives. With `part_line` it is used
        as it is (ADR-0051 row 5), stored as `partial` with `no_newline`."""
        used = 0
        if skipping:
            # Still inside an over-long line already emitted as truncated: drop its tail.
            nl = data.find(b"\n")
            if nl < 0:
                return [], len(data), csv_header, True
            used = nl + 1
            data = data[used:]
            skipping = False

        end = data.rfind(b"\n")
        oversized: Frame | None = None
        # The bytes after the last newline, when they are to be stored without one.
        part = data[end + 1 :] if part_line and len(data) < READ_LIMIT else b""
        if end < 0 and not part:
            if len(data) < READ_LIMIT:
                return [], used, csv_header, False  # no complete line yet
            # A single line longer than one read (review finding S4): emit its start as a
            # truncated event, then skip to the next newline on later passes.
            oversized = Frame(data=data[:MAX_LINE], truncated=True)
            complete = b""
            used += len(data)
            skipping = True
        else:
            complete = data[: end + 1]
            used += len(complete)

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
        if part:
            frames.append(Frame(data=part[:MAX_LINE], truncated=len(part) > MAX_LINE))
            used += len(part)
        for frame in frames:
            line = decode_frame(frame)
            if generic_csv and csv_header is None:
                csv_header = line.text
            row = normalizer.normalize(line)
            if row is None:
                continue
            if part and frame is frames[-1]:
                mark_part_line(row)  # the line never got its end
            rows.append(row)
        return rows, used, csv_header, skipping

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
            self._write(source.source_id, rows)
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
            self._write(source.source_id, rows)
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

    def _refresh_missing(self, source: SourceConfig, prev: SourceStatus) -> None:
        """Between API polls: show or clear only the missing-template error, every pass, so
        it (and D236's clock) does not wait for the next poll. Other errors are left alone."""
        want = self._missing_error(source)
        was = prev.error if is_fallback_error(prev.error) else None
        if want == was or (prev.error is not None and was is None):
            return
        with self._lock:
            self._status[source.source_id] = replace(prev, error=want)

    def _missing_error(self, source: SourceConfig) -> str | None:
        """The source's error while its configured template is not in the registry
        (ADR-0050): shown even with no new data, until the template loads again."""
        if source.template_id is None or source.template_id == AUTO_PARSER:
            return None
        if self._templates is not None and self._templates.get(source.template_id) is not None:
            return None
        return fallback_error(source.source_id, source.template_id)

    def _normalizer(
        self, source: SourceConfig
    ) -> Normalizer | TemplateNormalizer | AutoNormalizer | TemplateMissingNormalizer:
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
            # ADR-0050: keep storing with the generic parser, every row marked
            # template_missing; never silently: run_once keeps the source's error set.
            return TemplateMissingNormalizer(source.spec(), source.template_id, clock=self._clock)
        return template_normalizer(
            source, template, self._templates.tables if self._templates else None, self._clock
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
        position: FilePosition | None = None,
        replaces: FilePosition | None = None,
    ) -> None:
        """`position`: a text file's own position (ADR-0051), saved in the same
        transaction."""
        now = self._clock().isoformat()
        with self._meta.connect() as con:
            if position is not None:
                self._positions.save(position, con, replaces, now)
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
                    now,
                ),
            )
        self._unsaved = []


def _json_object(text: Any) -> dict[str, Any]:
    if not text:
        return {}
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def furthest[T](found: list[T], offset: Callable[[T], int], fits: Callable[[T], bool]) -> T | None:
    """The one rule against storing a line twice (D273): a file is read on from the
    furthest position any source saved on it that still fits the file (its content
    checks), whichever source reads it and by whatever route (a listed file, a held file
    after a rename, a takeover). A change of reader can change which source new
    lines belong to, never store one twice."""
    for p in sorted(found, key=offset, reverse=True):
        if fits(p):
            return p
    return None
