"""Write event rows to the Parquet lake, partitioned by source and day (SPEC 3.3).

Layout: <lake>/source=<source_id>/day=YYYY-MM-DD/part-<uuid7>.parquet
Files are written to a temporary name and renamed, so readers never see a
half-written file. Buffering, compaction, and retention sit outside this class.
"""

import os
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from app.core.ids import uuid7
from app.core.jsonsafe import clean_text
from app.core.schema import COLUMN_NAMES, arrow_schema


class LakeWriter:
    def __init__(self, lake_dir: Path) -> None:
        self._lake = lake_dir
        self._schema = arrow_schema()

    def write(self, rows: Sequence[dict[str, Any]]) -> list[Path]:
        """Write a batch. Returns the files created, one per (source, day) partition."""
        groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            groups[(row["source_id"], _day(row))].append(row)

        written: list[Path] = []
        for (source_id, day), batch in sorted(groups.items()):
            folder = self._lake / f"source={source_id}" / f"day={day}"
            folder.mkdir(parents=True, exist_ok=True)
            table = pa.Table.from_pydict(
                {name: [_utf8(r[name]) for r in batch] for name in COLUMN_NAMES},
                schema=self._schema,
            )
            final = folder / f"part-{uuid7().hex}.parquet"
            tmp = folder / f".{final.name}.tmp"
            pq.write_table(table, tmp, compression="zstd")
            os.replace(tmp, final)
            written.append(final)
        return written


def _utf8(value: Any) -> Any:
    """Parquet strings must be valid UTF-8. A JSON escape like \\ud800 in a log line yields
    a lone surrogate, which would fail the whole batch; it becomes U+FFFD instead. Decoded
    bytes (`raw`) never contain surrogates, so this never changes a raw line."""
    return clean_text(value) if isinstance(value, str) else value


def _day(row: dict[str, Any]) -> str:
    when: datetime = row["time"] or row["time_observed"]
    return when.astimezone(UTC).strftime("%Y-%m-%d")
