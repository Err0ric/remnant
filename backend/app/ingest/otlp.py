"""OTLP/HTTP JSON receiver: logs and metrics to one JSON line per record (ADR-0015 rows 3-5).

Senders (Claude Code, the OpenTelemetry Collector, the MCP inventory script) post standard
OTLP JSON to `/api/otlp/v1/logs` or `/v1/metrics` with a per-source bearer token. Each log
record or metric data point becomes one JSON line, appended to the source's spool file;
the ingest worker then reads the spool like any file, through the source's parser.

The line written is the source's `raw`. Before it is written, content that usage
visibility does not need is dropped unless the admin chose to keep it: prompt text,
assistant responses, tool input and parameters, and raw API bodies. From tool parameters
only the MCP server, MCP tool, and skill names are kept.

Attribute keys keep their meaning but use `_` for `.` (`user.email` -> `user_email`), so
templates can address them with plain dotted paths (`attr.user_email`).
"""

from __future__ import annotations

import gzip
import json
import math
import os
import re
import threading
import zlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element

import defusedxml.ElementTree as SafeET
from defusedxml import DefusedXmlException

from app.ai.sensitive import scan
from app.core.errors import ParamInvalidError
from app.ingest.sources import SPOOL_SUFFIX, spool_name

MAX_BODY = 4 * 1024 * 1024  # bytes, after decompression
MAX_RECORDS = 2000  # log records plus data points in one request
MAX_VALUE = 8 * 1024  # characters kept of any one string value
MAX_FUTURE = timedelta(days=1)  # later timestamps fall back to the time observed or received
MAX_COST_USD = 1_000_000.0  # one cost point above this, or below 0, is not real
MAX_DEPTH = 8
SPOOL_CAP = 512 * 1024 * 1024  # bytes waiting per source before the receiver refuses

# Dropped unless the source keeps content (ADR-0015 row 4).
CONTENT_KEYS = frozenset(
    {
        "prompt",
        "response",
        "assistant_response",
        "tool_input",
        "tool_parameters",
        "request_body",
        "response_body",
        "raw_body",
        "body_text",
        # The hooks plugin (ADR-0026): tool output and the whole hook input, sent only when
        # the plugin was downloaded with content on, kept only when the source keeps it.
        "tool_response",
        "hook_payload",
    }
)
# Kept from tool_parameters even when content is dropped: names, never arguments.
TOOL_NAME_KEYS = ("mcp_server_name", "mcp_tool_name", "skill_name", "plugin_name")
# Events whose body may carry what a person typed or what the model answered.
CONTENT_EVENTS = frozenset({"user_prompt", "assistant_response", "api_request_body"})
CLAUDE_EVENTS = frozenset(
    {
        "user_prompt",
        "tool_result",
        "api_request",
        "api_error",
        "tool_decision",
        "assistant_response",
        "api_refusal",
        "api_retries_exhausted",
        "mcp_server_connection",
        "permission_mode_changed",
        "skill_activated",
        "plugin_loaded",
        "plugin_installed",
        "compaction",
        "subagent_completed",
    }
)


def decode_body(raw: bytes, encoding: str | None) -> Any:
    """The request JSON, refusing anything over MAX_BODY even when compressed."""
    data = raw
    enc = (encoding or "").strip().lower()
    if enc == "gzip":
        try:
            d = zlib.decompressobj(16 + zlib.MAX_WBITS)
            data = d.decompress(raw, MAX_BODY + 1)
            if len(data) > MAX_BODY or d.unconsumed_tail:
                raise ParamInvalidError("The request is too large once decompressed")
        except (zlib.error, gzip.BadGzipFile) as exc:
            raise ParamInvalidError("The request body is not valid gzip") from exc
    elif enc not in ("", "identity"):
        raise ParamInvalidError("Use gzip or no compression")
    if len(data) > MAX_BODY:
        raise ParamInvalidError("The request is too large")
    try:
        return json.loads(data)
    except (ValueError, RecursionError) as exc:
        raise ParamInvalidError("The body is not OTLP JSON") from exc


def _key(name: str) -> str:
    return name.replace(".", "_")[:128]


def _clip(text: str) -> str:
    return text if len(text) <= MAX_VALUE else text[:MAX_VALUE] + "…"


def any_value(v: Any, depth: int = 0, clip: bool = True) -> Any:
    """An OTLP AnyValue as plain JSON. Strings are cut to MAX_VALUE unless `clip` is
    off (the sensitive-data scan reads the full text before anything is stored)."""
    if not isinstance(v, dict) or depth > MAX_DEPTH:
        return None
    if "stringValue" in v:
        text = str(v["stringValue"])
        return _clip(text) if clip else text
    if "boolValue" in v:
        return bool(v["boolValue"])
    if "intValue" in v:  # 64-bit integers arrive as strings in OTLP JSON
        try:
            return int(v["intValue"])
        except (TypeError, ValueError):
            return None
    if "doubleValue" in v:
        return _num(v["doubleValue"])
    if "arrayValue" in v:
        values = (v["arrayValue"] or {}).get("values") or []
        return [any_value(x, depth + 1, clip) for x in values[:200]]
    if "kvlistValue" in v:
        return attributes((v["kvlistValue"] or {}).get("values") or [], depth + 1, clip)
    if "bytesValue" in v:
        return "(bytes)"
    return None


def attributes(items: Any, depth: int = 0, clip: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not isinstance(items, list):
        return out
    for kv in items[:500]:
        if isinstance(kv, dict) and isinstance(kv.get("key"), str):
            out[_key(kv["key"])] = any_value(kv.get("value"), depth, clip)
    return out


def _time(nanos: Any) -> str | None:
    try:
        n = int(nanos)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    try:
        when = datetime.fromtimestamp(n / 1e9, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
    if when > datetime.now(UTC) + MAX_FUTURE:  # a bad clock or a forged record: never kept
        return None  # as "latest", and never stuck past retention
    return when.isoformat()


def _service(resource: dict[str, Any]) -> str | None:
    name = resource.get("service_name")
    return str(name) if name else None


def _event_name(attr: dict[str, Any], body: Any, service: str | None) -> str | None:
    name = attr.get("event_name")
    if not name and isinstance(body, str) and len(body) <= 128 and " " not in body:
        name = body
    if not name:
        return None
    name = str(name)
    if name.startswith("claude_hooks."):  # the hooks plugin names its own events
        return name
    claude = (service or "").lower().startswith("claude") or name in CLAUDE_EVENTS
    if claude and not name.startswith("claude_code."):
        name = "claude_code." + name
    return name


@dataclass(frozen=True, slots=True)
class NativeLine:
    """A record written as a plain line in the shape an existing template reads
    (ADR-0017 row 4): a file line as written, journald as RFC 5424, Windows XML as the
    `evtx` JSON shape."""

    text: str


MAX_LINE = 64 * 1024
_EVENT_NS = re.compile(r"^\{[^}]*\}")
_INT_FIELDS = frozenset({"EventID", "Version", "Level", "Task", "Opcode", "EventRecordID"})


def _local(tag: str) -> str:
    return _EVENT_NS.sub("", tag)


def _element(el: Element) -> Any:
    """An XML element in the evtx crate's JSON shape: attributes under `#attributes`,
    text alone as the value, or both as `#text` and `#attributes`."""
    attrs = {_local(k): v for k, v in el.attrib.items()}
    children = list(el)
    text = (el.text or "").strip()
    if children:
        out: dict[str, Any] = {"#attributes": attrs} if attrs else {}
        for child in children:
            out[_local(child.tag)] = _element(child)
        return out
    value: Any = text if text else None
    if _local(el.tag) in _INT_FIELDS and text.isdigit():
        value = int(text)
    if attrs and value is not None:
        return {"#attributes": attrs, "#text": value}
    if attrs:
        return {"#attributes": attrs}
    return value


def windows_event_json(xml: str) -> dict[str, Any] | None:
    """Windows event XML as `{"Event": {...}}` in the shape the windows_evtx template
    reads, with EventData `<Data Name="X">v</Data>` as `{"X": "v"}`. None if it is not
    an event."""
    try:
        root = SafeET.fromstring(xml, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (SafeET.ParseError, DefusedXmlException, ValueError):
        return None
    if _local(root.tag) != "Event":
        return None
    event: dict[str, Any] = {}
    for part in root:
        name = _local(part.tag)
        if name == "EventData":
            data: dict[str, Any] = {}
            for i, d in enumerate(part):
                key = d.attrib.get("Name") or f"Data{i}"
                data[key] = (d.text or "").strip() or None
            event[name] = data
        else:
            event[name] = _element(part)
    return {"Event": event}


def journald_line(entry: dict[str, Any], fallback_time: str | None, host: str | None) -> str | None:
    """A journal entry as an RFC 5424 line, so the Linux syslog templates read it."""
    message = entry.get("MESSAGE")
    if not isinstance(message, str):
        return None
    when = fallback_time
    usec = entry.get("__REALTIME_TIMESTAMP")
    try:
        if usec is not None:
            when = datetime.fromtimestamp(int(usec) / 1e6, tz=UTC).isoformat()
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        prio = min(max(int(entry.get("PRIORITY", 6)), 0), 7)
        facility = min(max(int(entry.get("SYSLOG_FACILITY", 1)), 0), 23)
    except (TypeError, ValueError):
        prio, facility = 6, 1
    hostname = entry.get("_HOSTNAME") or host or "-"
    ident = entry.get("SYSLOG_IDENTIFIER") or entry.get("_COMM") or "-"
    pid = entry.get("SYSLOG_PID") or entry.get("_PID") or "-"

    def token(v: Any) -> str:
        t = re.sub(r"\s", "_", str(v))[:255]
        return t or "-"

    line = (
        f"<{facility * 8 + prio}>1 {when or '-'} {token(hostname)} {token(ident)} {token(pid)}"
        f" - - {message}"
    )
    return line.replace("\n", " ")[:MAX_LINE]


def native_line(
    attr: dict[str, Any], body: Any, record_time: str | None, host: str | None
) -> NativeLine | None:
    if isinstance(body, str):
        text = body.lstrip("\ufeff")
        if text.startswith("<Event") and len(text) <= MAX_LINE:
            event = windows_event_json(text)
            if event is not None:
                return NativeLine(json.dumps(event, separators=(",", ":"), ensure_ascii=False))
        if "log_file_name" in attr or "log_file_path" in attr:
            return NativeLine(text.rstrip("\r\n")[:MAX_LINE].replace("\n", " "))
    if (
        isinstance(body, dict)
        and "MESSAGE" in body
        and ("_HOSTNAME" in body or "_COMM" in body or "SYSLOG_IDENTIFIER" in body)
    ):
        line = journald_line(body, record_time, host)
        if line is not None:
            return NativeLine(line)
    return None


def signals(
    record: dict[str, Any], full: dict[str, Any] | None = None, full_body: Any = None
) -> None:
    """Sensitive-data counts from what a person sent (ADR-0015 row 13), before any drop.
    `full` and `full_body` are the values before the 8 KB cut, so a secret late in a long
    paste is still counted (QA F2)."""
    attr = record.get("attr")
    if not isinstance(attr, dict):
        return
    src = full if isinstance(full, dict) else attr
    prompt_event = str(record.get("event") or "").endswith("user_prompt")
    body = (full_body if full_body is not None else record.get("body")) if prompt_event else None
    payload = src.get("hook_payload")
    # The hooks plugin's whole input holds the prompt, tool input, and tool output: what
    # the model sees. Scan it once rather than its parts twice.
    found = (
        scan(payload)
        if isinstance(payload, str) and payload
        else scan(src.get("prompt"), src.get("tool_input"), src.get("tool_parameters"), body)
    )
    if found:
        attr["sensitive"] = found
        attr["sensitive_total"] = sum(found.values())


def minimize(record: dict[str, Any]) -> dict[str, Any]:
    """Drop prompt, response, tool argument, and raw body content (ADR-0015 row 4)."""
    attr = record.get("attr")
    if isinstance(attr, dict):
        params = attr.get("tool_parameters")
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except ValueError:
                params = None
        if isinstance(params, dict):
            for k in TOOL_NAME_KEYS:
                if params.get(k) and k not in attr:
                    attr[k] = _clip(str(params[k]))
        for k in list(attr):
            if k in CONTENT_KEYS:
                attr.pop(k)
        if any(k in attr for k in ("prompt_length",)) or attr.get("event_name") in CONTENT_EVENTS:
            record.pop("body", None)
    event = str(record.get("event") or "")
    if event.split(".")[-1] in CONTENT_EVENTS:
        record.pop("body", None)
    record["content"] = "dropped"
    return record


def log_records(payload: Any, keep_content: bool) -> Iterator[dict[str, Any] | NativeLine]:
    if not isinstance(payload, dict):
        raise ParamInvalidError("The body is not OTLP JSON")
    for rl in payload.get("resourceLogs") or []:
        resource = attributes(((rl or {}).get("resource") or {}).get("attributes"))
        service = _service(resource)
        for sl in (rl or {}).get("scopeLogs") or []:
            scope = ((sl or {}).get("scope") or {}).get("name")
            for lr in (sl or {}).get("logRecords") or []:
                if not isinstance(lr, dict):
                    continue
                attr = attributes(lr.get("attributes"))
                body = any_value(lr.get("body"))
                when = _time(lr.get("timeUnixNano")) or _time(lr.get("observedTimeUnixNano"))
                native = native_line(attr, body, when, resource.get("host_name"))
                if native is not None:
                    yield native
                    continue
                record: dict[str, Any] = {
                    "signal": "log",
                    "time": when,
                    "service": service,
                    "event": _event_name(attr, body, service),
                    "severity": lr.get("severityText") or None,
                    "attr": attr,
                    "body": body,
                    "resource": resource,
                    "scope": scope,
                }
                signals(
                    record,
                    attributes(lr.get("attributes"), clip=False),
                    any_value(lr.get("body"), clip=False),
                )
                yield record if keep_content else minimize(record)


def metric_records(payload: Any) -> Iterator[dict[str, Any]]:
    """One record per data point. Histograms keep count and sum."""
    if not isinstance(payload, dict):
        raise ParamInvalidError("The body is not OTLP JSON")
    for rm in payload.get("resourceMetrics") or []:
        resource = attributes(((rm or {}).get("resource") or {}).get("attributes"))
        service = _service(resource)
        for sm in (rm or {}).get("scopeMetrics") or []:
            for m in (sm or {}).get("metrics") or []:
                if not isinstance(m, dict):
                    continue
                for kind in ("sum", "gauge", "histogram", "exponentialHistogram", "summary"):
                    data = m.get(kind)
                    if not isinstance(data, dict):
                        continue
                    for dp in data.get("dataPoints") or []:
                        if not isinstance(dp, dict):
                            continue
                        value: Any
                        if "asDouble" in dp:
                            value = _num(dp["asDouble"])
                        elif "asInt" in dp:
                            value = _num(dp["asInt"])
                        else:
                            value = None
                        name = str(m.get("name") or "")
                        if name.endswith("cost.usage") and value is not None:
                            if not 0 <= value <= MAX_COST_USD:  # QA F7
                                value = None
                        yield {
                            "signal": "metric",
                            "time": _time(dp.get("timeUnixNano")),
                            "service": service,
                            "metric": str(m.get("name") or "")[:200] or None,
                            "unit": m.get("unit") or None,
                            "kind": kind,
                            "value": value,
                            "count": _num(dp.get("count")),
                            "sum": _num(dp.get("sum")),
                            "temporality": data.get("aggregationTemporality"),
                            "attr": attributes(dp.get("attributes")),
                            "resource": resource,
                        }


def _num(v: Any) -> float | int | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(f):  # NaN or infinity break every sum they touch (QA F1)
        return None
    return int(f) if f.is_integer() and abs(f) < 2**53 else f


def lines(records: Iterable[dict[str, Any] | NativeLine]) -> list[bytes]:
    out = []
    for i, r in enumerate(records):
        if i >= MAX_RECORDS:
            raise ParamInvalidError(f"At most {MAX_RECORDS} records a request")
        if isinstance(r, NativeLine):
            out.append(r.text.encode("utf-8", "replace") + b"\n")
        else:
            out.append(json.dumps(r, separators=(",", ":"), ensure_ascii=False).encode() + b"\n")
    return out


class Spool:
    """Appends whole records to `<root>/<source_id>/<hour>.<suffix>`, one writer at a time
    per source, so the ingest worker (which only reads complete records) never sees half of
    one. `kind` is the source kind: OTLP JSON lines, or syslog records (ADR-0021 row 2)."""

    def __init__(self, root: Path, kind: str = "otlp") -> None:
        self._root = root
        self._kind = kind
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def _lock(self, source_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(source_id, threading.Lock())

    def waiting(self, source_id: str) -> int:
        folder = self._root / source_id
        if not folder.is_dir():
            return 0
        pattern = f"*{SPOOL_SUFFIX[self._kind]}"
        return sum(p.stat().st_size for p in folder.glob(pattern) if p.is_file())

    def append(self, source_id: str, chunk: list[bytes], now: datetime) -> int:
        if not chunk:
            return 0
        folder = self._root / source_id
        with self._lock(source_id):
            if self.waiting(source_id) > SPOOL_CAP:
                raise SpoolFullError(source_id)
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = folder / spool_name(now, self._kind)
            fd = _open_append(path)
            try:
                start = os.fstat(fd).st_size
                data = memoryview(b"".join(chunk))
                try:
                    while data:
                        data = data[os.write(fd, data) :]
                except OSError:
                    # A short write (disk full) must not leave half a record for the reader.
                    os.ftruncate(fd, start)
                    raise
            finally:
                os.close(fd)
        return len(chunk)


class SpoolFullError(Exception):
    pass


def _open_append(path: Path) -> int:
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    return os.open(path, flags, 0o600)
