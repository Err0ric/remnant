"""Apply a validated template to decoded lines: envelope, payload, transforms, mapping.

`TemplateNormalizer.normalize` has the same contract as the generic Normalizer: it returns
a full row shaped like core/schema.py, `raw` is the decoded line untouched, and hostile
input never raises. Parsed fields that no mapping reads are kept in `unmapped`.
"""

import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import structlog

from app.core import jsonsafe
from app.core.ids import new_event_id
from app.core.schema import COLUMN_NAMES, COLUMNS_BY_NAME, ColumnType
from app.ingest.envelope import Envelope, EnvelopeParser, SyslogEnvelopeConfig
from app.ingest.payload.base import PayloadParser, PayloadResult
from app.ingest.payload.cef import CefParser
from app.ingest.payload.delimited import CsvParser
from app.ingest.payload.jsonpayload import JsonParser
from app.ingest.payload.kv import KvParser
from app.ingest.payload.leef import LeefParser
from app.ingest.payload.regexpayload import PlainParser, RegexParser
from app.ingest.payload.xmlpayload import XmlParser
from app.ingest.records import DecodedLine
from app.templates.tables import LookupTable
from app.templates.transforms import MISSING, TransformRunner, get_path
from app.templates.validator import PayloadSpec, Template

log = structlog.get_logger(__name__)

# Syslog severity (0 emerg .. 7 debug) to OCSF severity_id, used when a template has none.
_SYSLOG_TO_OCSF = {0: 5, 1: 5, 2: 5, 3: 4, 4: 3, 5: 2, 6: 1, 7: 1}
_HEADER_MARKERS = {"cef": "CEF:", "leef": "LEEF:"}
_NO_VALUE: tuple[Any, ...] = (MISSING, None, "", "-")
_OCSF_SEVERITIES = frozenset({"0", "1", "2", "3", "4", "5", "6", "99"})
# Filled from the envelope when the template does not map them.
_ENVELOPE_DEFAULTS = {
    "time": "timestamp",
    "device_hostname": "hostname",
    "actor_process_name": "app_name",
    "actor_process_pid": "procid",
    "message": "msg",
}


def build_payload_parser(spec: PayloadSpec) -> PayloadParser:
    fmt = spec.format
    if fmt == "regex" and spec.regex:
        return RegexParser(list(spec.regex.patterns))
    if fmt == "kv":
        kv = spec.kv
        return KvParser(kv.pair_sep, kv.kv_sep, kv.quote) if kv else KvParser()
    if fmt == "csv" and spec.csv:
        return CsvParser(
            list(spec.csv.columns), spec.csv.delimiter, spec.csv.quote, spec.csv.trailing
        )
    if fmt == "json":
        return JsonParser(spec.json_.root if spec.json_ else "$")
    if fmt == "xml" and spec.xml:
        return XmlParser(dict(spec.xml.fields), dict(spec.xml.namespaces))
    if fmt == "cef":
        return CefParser()
    if fmt == "leef":
        return LeefParser()
    return PlainParser()


class TemplateNormalizer:
    def __init__(
        self,
        template: Template,
        source_id: str,
        classification: str = "local_only",
        owner_id: str = "local",
        envelope: SyslogEnvelopeConfig | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        tables: Mapping[str, LookupTable] | None = None,
    ) -> None:
        self._t = template
        self._table: LookupTable | None = None
        if template.mapping.lookup is not None:
            self._table = (tables or {}).get(template.mapping.lookup.table)
            if self._table is None:
                raise ValueError(f"lookup table {template.mapping.lookup.table} is not loaded")
        self._source_id = source_id
        self._classification = classification
        self._owner = owner_id
        self._clock = clock
        # A source's own envelope settings (year, time zone) win over the template's.
        env_cfg = envelope or template.envelope.syslog
        self._tz = ZoneInfo(env_cfg.timezone)
        self._envelope = (
            EnvelopeParser(env_cfg, clock=clock) if template.envelope.type == "syslog" else None
        )
        self._payload = build_payload_parser(template.payload)
        self._transforms = TransformRunner(list(template.transforms), self._tz, clock)
        self._used = {ref for m in template.mapping.fields.values() for ref in m.sources}
        if template.mapping.lookup:
            self._used.add(template.mapping.lookup.field)
            # Actor refs count as used only when read for this event (see _map): the
            # account an event acts on (TargetUserName on 4720) must stay in unmapped.
        if template.mapping.severity:
            self._used.add(template.mapping.severity.from_)
        if template.mapping.class_by:
            self._used.add(template.mapping.class_by.field)

    def normalize(self, line: DecodedLine) -> dict[str, Any]:
        try:
            return self._normalize(line)
        except Exception as exc:  # last resort: one hostile line must never stop ingest
            # Logged without content (CLAUDE.md logging rule); the tester fails on it.
            log.warning("template.internal_error", template=self._t.id, error=type(exc).__name__)
            row: dict[str, Any] = dict.fromkeys(COLUMN_NAMES)
            self._stamp(row, line, "failed", [f"internal:{type(exc).__name__}"])
            row["message"] = None
            return row

    def _normalize(self, line: DecodedLine) -> dict[str, Any]:
        row: dict[str, Any] = dict.fromkeys(COLUMN_NAMES)
        errors: list[str] = []
        text = line.text
        env: Envelope | None = None
        if self._envelope is not None:
            env = self._envelope.parse(text, line.hint)
            if env.rfc == "none":
                if not self._t.envelope.optional:
                    errors.append("no_syslog_header")
                env = None
            else:
                # A bare PRI with no header is how some devices always send; not a fault.
                errors.extend(e for e in env.errors if e != "no_header")
                text = env.msg
                marker = _HEADER_MARKERS.get(self._t.payload.format)
                if env.app_name and env.app_name.startswith("%"):
                    # Cisco "%ASA-6-302013:" is a message id, not a program: give it back.
                    text = f"{env.app_name}: {env.msg}"
                    env = replace(env, app_name=None)
                elif env.app_name and env.app_name.isdigit():
                    # IOS sequence numbers ("123:") read as a tag; they name no process.
                    text = f"{env.app_name}: {env.msg}"
                    env = replace(env, app_name=None)
                elif marker and env.app_name == marker[:-1]:
                    # "host CEF:0|..." reads as a tag named CEF; the header belongs to
                    # the payload, and CEF is not a process name.
                    text = f"{marker}{env.msg}"
                    env = replace(env, app_name=None)
                row["envelope"] = json.dumps(env.to_column(), separators=(",", ":"))

        result: PayloadResult = self._payload.parse(text)
        fields = result.fields
        consumed: set[str] = set()
        if result.ok:
            errors.extend(self._transforms.apply(fields))
            consumed = self._map(fields, env, row, errors)
            status = "partial" if (result.partial or errors) else "ok"
        else:
            errors.append(f"payload:{result.error}"[:80])
            if env is not None:
                self._envelope_only(env, row)
                status = "envelope_only"
            else:
                row["message"] = text
                status = "failed"
        if line.truncated:
            errors.insert(0, "truncated")
            if status in ("ok", "envelope_only"):
                status = "partial"
        leftover = {k: v for k, v in fields.items() if k not in self._used and k not in consumed}
        if leftover:
            row["unmapped"] = _json(leftover)
        self._stamp(row, line, status, errors)
        return row

    def _stamp(
        self, row: dict[str, Any], line: DecodedLine, status: str, errors: list[str]
    ) -> None:
        row.update(
            event_id=new_event_id(),
            source_id=self._source_id,
            template_id=self._t.id,
            template_version=self._t.version,
            time_observed=self._clock(),
            raw=line.text,
            raw_bytes_invalid=line.bytes_invalid,
            parse_status=status,
            parse_errors=",".join(dict.fromkeys(errors))[:500] or None,
            classification=self._classification,
            owner_id=self._owner,
        )

    # --- mapping ----------------------------------------------------------------------

    def _lookup(self, ref: str, fields: dict[str, Any], env: Envelope | None) -> Any:
        if ref.startswith("envelope."):
            if env is None:
                return MISSING
            return getattr(env, ref.removeprefix("envelope."), None)
        return get_path(fields, ref)

    def _map(
        self, fields: dict[str, Any], env: Envelope | None, row: dict[str, Any], errors: list[str]
    ) -> set[str]:
        """Fill `row` from `fields`; return the per-event refs read (the actor's field)."""
        consumed: set[str] = set()
        m = self._t.mapping
        class_uid = m.class_uid
        if m.class_by:
            key = self._lookup(m.class_by.field, fields, env)
            class_uid = m.class_by.values.get(str(key), class_uid)
        entry = None
        if self._table is not None and m.lookup is not None:
            key = self._lookup(m.lookup.field, fields, env)
            entry = self._table.entries.get(str(key)) if key is not MISSING else None
            if entry is not None and not (
                m.class_by and str(self._lookup(m.class_by.field, fields, env)) in m.class_by.values
            ):
                class_uid = entry.class_uid
        row["class_uid"] = class_uid
        row["category_uid"] = class_uid // 1000 if class_uid else None

        for column, spec in m.fields.items():
            value: Any = MISSING
            for ref in spec.sources:  # the first source with a value wins
                value = self._lookup(ref, fields, env)
                if value not in _NO_VALUE:
                    break
            if value in _NO_VALUE:
                value = MISSING  # "key=" or "-" with nothing after it means no value
            if value is not MISSING and value is not None and spec.map is not None:
                value = spec.map.get(str(value), MISSING)
            if value is MISSING or value is None:
                value = spec.default
            if value is not None:
                self._set(row, column, value, errors)

        if m.severity:
            raw_sev = self._lookup(m.severity.from_, fields, env)
            if raw_sev is not MISSING and raw_sev is not None:
                # A mapped value, else the value itself when it already is an OCSF
                # severity id (0 to 6, or 99); anything else leaves severity unset.
                sev: int | None = m.severity.map.get(str(raw_sev))
                if sev is None and str(raw_sev).strip() in _OCSF_SEVERITIES:
                    sev = int(str(raw_sev).strip())
                if sev is not None:
                    row["severity_id"] = sev
        if m.lookup is not None and m.lookup.actor is not None:
            # Only the refs for this event's role: falling back to the other role would
            # name the wrong user (a computer account, or the account that was created).
            role = entry.actor if entry is not None else "subject"
            for ref in m.lookup.actor.target if role == "target" else m.lookup.actor.subject:
                value = self._lookup(ref, fields, env)
                if value not in _NO_VALUE:
                    self._set(row, "actor_user_name", value, errors)
                    consumed.add(ref)
                    break
        if entry is not None:  # table values fill what the template did not map
            for column in ("activity_id", "status_id", "severity_id"):
                if row[column] is None and getattr(entry, column) is not None:
                    row[column] = getattr(entry, column)
            if row["message"] is None and entry.label:
                row["message"] = entry.label
        if env is not None:
            for column, attr in _ENVELOPE_DEFAULTS.items():
                if row[column] is None and column in self._t.envelope.defaults:
                    self._set(row, column, getattr(env, attr), errors, quiet=True)
            if row["severity_id"] is None and env.severity is not None:
                row["severity_id"] = _SYSLOG_TO_OCSF[env.severity]
        return consumed

    def _envelope_only(self, env: Envelope, row: dict[str, Any]) -> None:
        for column, attr in _ENVELOPE_DEFAULTS.items():
            self._set(row, column, getattr(env, attr), [], quiet=True)
        if env.severity is not None:
            row["severity_id"] = _SYSLOG_TO_OCSF[env.severity]

    def _set(
        self, row: dict[str, Any], column: str, value: Any, errors: list[str], quiet: bool = False
    ) -> None:
        if value is None:
            return
        try:
            row[column] = _coerce(value, COLUMNS_BY_NAME[column].type, self._tz)
        except (ValueError, TypeError, OverflowError):
            row[column] = None
            if not quiet:
                errors.append(f"bad_value:{column}")


def _coerce(value: Any, kind: ColumnType, tz: ZoneInfo) -> Any:
    if kind is ColumnType.INT:
        if isinstance(value, bool):
            raise TypeError("bool")
        if isinstance(value, float) and not value.is_integer():
            raise ValueError("fraction")
        number = int(value) if not isinstance(value, str) else int(value.strip())
        if not -(2**63) <= number < 2**63:
            raise OverflowError("int64")
        return number
    if kind is ColumnType.TIMESTAMPTZ:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            text = value.strip()
            parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
        else:
            raise TypeError("timestamp")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        return parsed.astimezone(UTC)
    if kind is ColumnType.BOOL:
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("true", "1", "yes"):
            return True
        if text in ("false", "0", "no"):
            return False
        raise ValueError("bool")
    if kind is ColumnType.JSON or isinstance(value, dict | list):
        return _json(value)
    return str(value)


def _json(value: Any) -> str:
    return jsonsafe.dumps(value)
