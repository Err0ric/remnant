"""Turn decoded lines into event rows shaped exactly like core/schema.py.

Slice 1 uses generic parsers per source format (syslog envelope only, JSON
lines, CSV with header). `raw` is always the decoded line, unmodified.
"""

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core import jsonsafe
from app.core.ids import new_event_id
from app.core.schema import COLUMN_NAMES
from app.ingest.envelope import Envelope, EnvelopeParser, SyslogEnvelopeConfig
from app.ingest.payload.generic import (
    CsvRowParser,
    find_message,
    find_time,
    parse_json_object,
    summarize,
)
from app.ingest.records import DecodedLine

SourceFormat = Literal["syslog", "json", "csv"]
GENERIC_TEMPLATE_VERSION = "1.0.0"
_SOURCE_ID = re.compile(r"[a-z0-9][a-z0-9_]{0,63}")

# Syslog severity (0 emerg .. 7 debug) to OCSF severity_id (1 info .. 5 critical).
_SYSLOG_TO_OCSF = {0: 5, 1: 5, 2: 5, 3: 4, 4: 3, 5: 2, 6: 1, 7: 1}


class SourceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    format: SourceFormat
    classification: Literal["local_only", "cloud_allowed"] = "local_only"
    owner_id: str = "local"
    envelope: SyslogEnvelopeConfig = Field(default_factory=SyslogEnvelopeConfig)
    csv_delimiter: str = Field(default=",", min_length=1, max_length=1)

    @field_validator("source_id")
    @classmethod
    def _safe_source_id(cls, value: str) -> str:
        # Used as a path segment in the lake: lowercase, digits, underscore only.
        if not _SOURCE_ID.fullmatch(value):
            raise ValueError("source_id must match [a-z0-9][a-z0-9_]{0,63}")
        return value


class Normalizer:
    """One instance per file stream (CSV headers are per file)."""

    def __init__(
        self, spec: SourceSpec, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._spec = spec
        self._clock = clock
        self._tz = ZoneInfo(spec.envelope.timezone)
        self._envelope = EnvelopeParser(spec.envelope, clock=clock)
        self._csv = CsvRowParser(spec.csv_delimiter) if spec.format == "csv" else None

    def normalize(self, line: DecodedLine) -> dict[str, Any] | None:
        """Return a full event row, or None for a line that is not an event (CSV header)."""
        row: dict[str, Any] = dict.fromkeys(COLUMN_NAMES)
        errors: list[str] = []
        fmt = self._spec.format
        if fmt == "syslog":
            status = self._syslog(line.text, row, errors)
        elif fmt == "json":
            status = self._json(line.text, row, errors)
        else:
            result = self._csv_row(line.text, row, errors)
            if result is None:
                return None
            status = result

        if line.truncated:
            errors.insert(0, "truncated")
            if status in ("ok", "envelope_only"):
                status = "partial"

        row.update(
            event_id=new_event_id(),
            source_id=self._spec.source_id,
            template_id=f"generic_{fmt}",
            template_version=GENERIC_TEMPLATE_VERSION,
            time_observed=self._clock(),
            raw=line.text,
            raw_bytes_invalid=line.bytes_invalid,
            parse_status=status,
            parse_errors=",".join(errors) or None,
            classification=self._spec.classification,
            owner_id=self._spec.owner_id,
        )
        return row

    # -- formats ---------------------------------------------------------------------

    def _syslog(self, text: str, row: dict[str, Any], errors: list[str]) -> str:
        env: Envelope = self._envelope.parse(text)
        if env.rfc == "none":
            errors.append("no_syslog_header")
            row["message"] = text
            return "envelope_only"
        errors.extend(env.errors)
        row.update(
            time=env.timestamp,
            message=env.msg,
            device_hostname=env.hostname,
            actor_process_name=env.app_name,
            actor_process_pid=int(env.procid) if env.procid and env.procid.isdigit() else None,
            severity_id=None if env.severity is None else _SYSLOG_TO_OCSF[env.severity],
            envelope=json.dumps(env.to_column(), separators=(",", ":")),
        )
        return "envelope_only"

    def _json(self, text: str, row: dict[str, Any], errors: list[str]) -> str:
        obj = parse_json_object(text)
        if obj is None:
            errors.append("invalid_json")
            return "failed"
        row.update(
            time=find_time(obj, self._tz),
            message=find_message(obj) or summarize(obj),
            unmapped=jsonsafe.dumps(obj),
        )
        return "ok"

    def _csv_row(self, text: str, row: dict[str, Any], errors: list[str]) -> str | None:
        assert self._csv is not None  # constructed for csv sources
        parsed = self._csv.parse(text)
        if parsed is None:
            return None
        obj, columns_ok = parsed
        row.update(
            time=find_time(obj, self._tz),
            message=find_message(obj) or summarize(obj),
            unmapped=jsonsafe.dumps(obj),
        )
        if not columns_ok:
            errors.append("column_count_mismatch")
            return "partial"
        return "ok"
