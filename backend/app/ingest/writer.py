"""Write event rows to the Parquet lake, partitioned by source and day (SPEC 3.3).

Layout: <lake>/source=<source_id>/day=YYYY-MM-DD/part-<uuid7>.parquet
Files are written to a temporary name, flushed to disk, and renamed (durable.publish),
so readers never see a half-written file, even after a power cut. Buffering,
compaction, and retention sit outside this class.
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import structlog

from app.core.ids import uuid7
from app.core.jsonsafe import clean_text
from app.core.schema import COLUMN_NAMES, arrow_schema
from app.ingest.durable import publish
from app.ingest.integrity import LakeEvents, NoEvents
from app.ingest.lakelock import lake_lock

log = structlog.get_logger()


class LakeWriter:
    def __init__(self, lake_dir: Path, events: LakeEvents | None = None) -> None:
        self._lake = lake_dir
        self._events = events or NoEvents()
        self._schema = arrow_schema()

    def write(self, rows: Sequence[dict[str, Any]]) -> list[Path]:
        """Write a batch. Returns the files created, one per (source, day) partition."""
        groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            groups[(row["source_id"], _day(row))].append(row)

        written: list[Path] = []
        try:
            for (source_id, day), batch in sorted(groups.items()):
                folder = self._lake / f"source={source_id}" / f"day={day}"
                folder.mkdir(parents=True, exist_ok=True)
                table = rows_table(batch, self._schema)
                final = folder / f"part-{uuid7().hex}.parquet"
                written.append(publish(table, final))
            self._events.added(written)  # the integrity ledger (ADR-0022)
        except BaseException:
            # All or nothing: the caller moves its checkpoint only after this returns and
            # reads the same lines again on the next pass, so a file left here would be
            # stored twice, and again on every pass while the fault lasts (a full disk, a
            # ledger that cannot be written). The ledger records the batch in one
            # transaction, so on a failure it knows none of these files.
            for path in written:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    log.warning("lake.write_undo_failed", file=path.name)
            raise
        return written

    def discard(self, paths: Sequence[Path], reason: str) -> list[Path]:
        """Take back files `write` returned whose caller could not save its position: the
        ledger records the removal, then they are deleted. Returns the files still owed:
        only when the ledger could not be written. A file that no longer matches the
        ledger is left for verification to report and is not owed (it would never go)."""
        # Under the lake lock, like every other removal of recorded files: an integrity
        # check that has read the ledger must not then find the file gone. While
        # maintenance or a backup holds the lock the files stay owed until the next pass.
        with lake_lock(self._lake, wait=False) as locked:
            if not locked:
                return [p for p in paths if p.exists()]
            try:
                ok = self._events.removed(list(paths), reason)
            except Exception:
                return [p for p in paths if p.exists()]
            for path in ok:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    log.warning("lake.write_undo_failed", file=path.name)
        kept = [p.name for p in paths if p not in ok and p.exists()]
        if kept:
            log.warning("lake.write_undo_skipped_changed", files=kept[:5], count=len(kept))
        return []


def rows_table(rows: Sequence[dict[str, Any]], schema: pa.Schema | None = None) -> pa.Table:
    """Event rows as a table in the lake's schema."""
    return pa.Table.from_pydict(
        {name: [_utf8(r[name]) for r in rows] for name in COLUMN_NAMES},
        schema=schema or arrow_schema(),
    )


def _utf8(value: Any) -> Any:
    """Parquet strings must be valid UTF-8. A JSON escape like \\ud800 in a log line yields
    a lone surrogate, which would fail the whole batch; it becomes U+FFFD instead. Decoded
    bytes (`raw`) never contain surrogates, so this never changes a raw line."""
    return clean_text(value) if isinstance(value, str) else value


def _day(row: dict[str, Any]) -> str:
    when: datetime = row["time"] or row["time_observed"]
    return when.astimezone(UTC).strftime("%Y-%m-%d")
