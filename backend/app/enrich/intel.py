"""Threat intel lists (ADR-0023 rows 1 and 7): parsing, storage, and matching.

Every list is normalized to the same rows (indicator, type, feed, threat, first_seen,
last_seen) and kept as Parquet per feed. The enabled feeds are combined into one file,
`data/enrichment/intel/indicators.parquet`, which the query engine shows as the read-only
`threat_intel` table and the matcher uses to mark values in results. All text from a feed
is untrusted: strings only, capped, rendered as text, never sent to a model.
"""

from __future__ import annotations

import csv
import ipaddress
import json
import os
import re
import threading
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import duckdb

IndicatorType = Literal["ip", "domain", "url", "md5", "sha1", "sha256"]
MAX_MATCH_VALUES = 5000  # distinct values checked per response
MAX_HITS = 3  # listings shown per value
KEEP_DAYS = 90  # rolling window for feeds delivered as recent additions (ThreatFox)
COLUMNS = ("indicator", "type", "feed", "threat", "first_seen", "last_seen")

_DOMAIN = re.compile(r"^(?=.{4,253}$)([a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_HEX = re.compile(r"^[0-9a-f]+$")
_HASH_TYPES: dict[int, IndicatorType] = {32: "md5", 40: "sha1", 64: "sha256"}


@dataclass(frozen=True, slots=True)
class Indicator:
    indicator: str
    type: IndicatorType
    feed: str
    threat: str
    first_seen: str | None = None
    last_seen: str | None = None


def _cap(value: Any, n: int) -> str:
    return value.strip()[:n] if isinstance(value, str) else ""


def classify(value: str) -> tuple[str, IndicatorType] | None:
    """The normalized indicator and its type, or None when it is not one we can match
    exactly (CIDR ranges and wildcards are not supported)."""
    v = value.strip()
    if not v or len(v) > 2048:
        return None
    if v.lower().startswith(("http://", "https://")):
        return v, "url"
    low = v.lower()
    try:
        return str(ipaddress.ip_address(low)), "ip"
    except ValueError:
        pass
    if _HEX.match(low) and len(low) in _HASH_TYPES:
        return low, _HASH_TYPES[len(low)]
    host = low.rstrip(".")
    if _DOMAIN.match(host):
        return host, "domain"
    return None


def _stamp(value: Any) -> str | None:
    """'2026-10-15 10:00:00 UTC' or ISO text to ISO, or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().removesuffix(" UTC").replace(" ", "T")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).isoformat()


# --- parsers --------------------------------------------------------------------------


def parse_feodo(raw: bytes) -> tuple[list[Indicator], int]:
    """Feodo Tracker's ipblocklist.csv: comment lines start with #, then
    first_seen_utc, dst_ip, dst_port, c2_status, last_online, malware."""
    rows, bad = [], 0
    text = raw.decode("utf-8", "replace")
    data = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    for rec in csv.reader(data):
        if not rec or rec[0] == "first_seen_utc":
            continue
        if len(rec) < 6:
            bad += 1
            continue
        found = classify(rec[1])
        if found is None or found[1] != "ip":
            bad += 1
            continue
        malware = _cap(rec[5], 60) or "Unknown"
        rows.append(
            Indicator(
                found[0], "ip", "feodo", f"{malware} botnet C2", _stamp(rec[0]), _stamp(rec[4])
            )
        )
    return rows, bad


_THREATFOX_TYPES = {"ip:port": "ip", "domain": "domain", "url": "url"}


def parse_threatfox(raw: bytes) -> tuple[list[Indicator], int]:
    """The ThreatFox API's get_iocs answer."""
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("ThreatFox answered with something that is not JSON") from exc
    if not isinstance(doc, dict):
        raise ValueError("ThreatFox answered with an unexpected shape")
    status = doc.get("query_status")
    if status == "no_result":
        return [], 0
    if isinstance(status, str) and "auth" in status.lower():
        raise ValueError("abuse.ch refused the Auth-Key; check it on the Enrichment page")
    if status != "ok" or not isinstance(doc.get("data"), list):
        raise ValueError(f"ThreatFox answered: {_cap(status, 60) or 'no status'}")
    rows, bad = [], 0
    for item in doc["data"]:
        if not isinstance(item, dict):
            bad += 1
            continue
        ioc = _cap(item.get("ioc"), 2048)
        kind = _cap(item.get("ioc_type"), 30)
        if kind == "ip:port":
            ioc = ioc.rsplit(":", 1)[0].strip("[]")
        found = classify(ioc)
        expected = _THREATFOX_TYPES.get(kind) or ("md5" if "md5" in kind else None)
        if "sha256" in kind:
            expected = "sha256"
        elif "sha1" in kind:
            expected = "sha1"
        if found is None or (expected is not None and found[1] != expected):
            bad += 1
            continue
        malware = _cap(item.get("malware_printable"), 60) or "Unknown"
        threat_type = _cap(item.get("threat_type"), 40).replace("botnet_cc", "botnet C2")
        threat = f"{malware} ({threat_type.replace('_', ' ')})" if threat_type else malware
        rows.append(
            Indicator(
                found[0],
                found[1],
                "threatfox",
                threat[:120],
                _stamp(item.get("first_seen")),
                _stamp(item.get("last_seen")),
            )
        )
    return rows, bad


def parse_custom(raw: bytes) -> tuple[list[Indicator], int]:
    """An admin's list: one indicator per line, optionally `indicator,description`.
    Lines starting with # are comments."""
    rows, bad = [], 0
    text = raw.decode("utf-8", "replace")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        value, _, note = line.partition(",")
        found = classify(value)
        if found is None:
            bad += 1
            continue
        threat = _cap(note.strip().strip('"'), 120) or "Your list"
        rows.append(Indicator(found[0], found[1], "custom", threat))
    return rows, bad


def merge_recent(
    old: Iterable[Indicator], new: Iterable[Indicator], now: datetime
) -> list[Indicator]:
    """New listings replace old ones for the same indicator; anything not seen within
    KEEP_DAYS drops out."""
    cutoff = (now - timedelta(days=KEEP_DAYS)).isoformat()
    merged: dict[tuple[str, str], Indicator] = {}
    for item in [*old, *new]:
        merged[(item.indicator, item.type)] = item
    return [
        i for i in merged.values() if (i.last_seen or i.first_seen or now.isoformat()) >= cutoff
    ]


# --- storage --------------------------------------------------------------------------


def write_parquet(rows: Iterable[Indicator], path: Path) -> int:
    """Write rows to `path` through a temporary file and a rename. Returns the count."""
    tmp = path.with_name(f".{path.stem}.{uuid.uuid4().hex}.tmp")  # never shared by two writers
    con = duckdb.connect(":memory:")
    try:
        con.execute(
            "CREATE TABLE t (indicator VARCHAR, type VARCHAR, feed VARCHAR, threat VARCHAR,"
            " first_seen VARCHAR, last_seen VARCHAR)"
        )
        data = [(r.indicator, r.type, r.feed, r.threat, r.first_seen, r.last_seen) for r in rows]
        if data:
            con.executemany("INSERT INTO t VALUES (?, ?, ?, ?, ?, ?)", data)
        con.execute(f"COPY t TO '{_sql_path(tmp)}' (FORMAT PARQUET)")
    finally:
        con.close()
    os.replace(tmp, path)
    return len(data)


def read_parquet(path: Path) -> list[Indicator]:
    if not path.is_file():
        return []
    con = duckdb.connect(":memory:")
    try:
        rows = con.execute(
            f"SELECT indicator, type, feed, threat, first_seen, last_seen"  # noqa: S608  # server path, quoted
            f" FROM read_parquet('{_sql_path(path)}')"
        ).fetchall()
    finally:
        con.close()
    return [Indicator(*r) for r in rows]


def combine(files: Iterable[Path], out: Path) -> int:
    """The enabled feeds' rows in one file for the engine and the matcher."""
    out.parent.mkdir(parents=True, exist_ok=True)
    rows: list[Indicator] = []
    for f in files:
        rows.extend(read_parquet(f))
    return write_parquet(rows, out)


def _sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


# --- matching -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Hit:
    feed: str
    type: str
    threat: str
    last_seen: str | None


FEED_NAMES = {"feodo": "Feodo Tracker", "threatfox": "ThreatFox", "custom": "Your list"}


class ThreatIntel:
    """Marks values in results that appear in the combined list. Reloaded when the file
    changes on disk."""

    def __init__(self, combined: Path) -> None:
        self._path = combined
        self._stamp: tuple[float, int] | None = None
        self._index: dict[str, list[Hit]] = {}
        self._lock = threading.Lock()

    def _load(self) -> dict[str, list[Hit]]:
        with self._lock:
            try:
                st = self._path.stat()
            except OSError:
                self._index, self._stamp = {}, None
                return self._index
            stamp = (st.st_mtime, st.st_size)
            if stamp != self._stamp:
                index: dict[str, list[Hit]] = {}
                for r in read_parquet(self._path):
                    hits = index.setdefault(r.indicator, [])
                    if len(hits) < MAX_HITS:
                        hits.append(
                            Hit(FEED_NAMES.get(r.feed, r.feed), r.type, r.threat, r.last_seen)
                        )
                self._index, self._stamp = index, stamp
            return self._index

    def match(self, values: Iterable[Any]) -> dict[str, list[Hit]]:
        index = self._load()
        if not index:
            return {}
        out: dict[str, list[Hit]] = {}
        seen: set[str] = set()
        for v in values:
            if not isinstance(v, str) or v in seen:
                continue
            seen.add(v)
            if len(seen) > MAX_MATCH_VALUES:
                break
            key = v if v in index else v.strip().lower()
            if key in index:
                out[v] = index[key]
        return out


def parse_for(feed_id: str, raw: bytes) -> tuple[list[Indicator], int]:
    if feed_id == "intel_feodo":
        return parse_feodo(raw)
    if feed_id == "intel_threatfox":
        return parse_threatfox(raw)
    return parse_custom(raw)
