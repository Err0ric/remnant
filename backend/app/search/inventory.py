"""Which Proxmox guest held an address (ADR-0045 A5, A6).

Reads the `proxmox_inventory` events in the caller's own `events` view, so a person sees
only guests from Proxmox sources they may read (rule 13). A match is exact: an IP in the
guest's recorded addresses, a MAC in its MACs, or, on a host page, the guest name equal to
the host (case-insensitive; D215, proposed). Nothing is matched by similarity.

Each guest that held the value gets its own line, with the first and last inventory event
showing it, so an address that two guests held at different times shows both. Inventory
events are written on a change and once a day, so the window starts a day and an hour
before the range: the snapshot before the range still counts.
"""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from app.engine.duckdb import QueryEngine, QueryScope
from app.search.entities import quote

TEMPLATE = "proxmox_inventory"
LOOKBACK = timedelta(days=1, hours=1)
MAX_ROWS = 20_000
_MAC = re.compile(r"^[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}$")
Kind = Literal["ip", "mac", "name"]

ROWS_SQL = f"""SELECT source_id, coalesce(time, time_observed) AS t, raw
FROM events
WHERE template_id = '{TEMPLATE}'
ORDER BY t"""  # noqa: S608  # fixed SQL text


@dataclass(frozen=True, slots=True)
class Match:
    source_id: str
    vmid: int
    type: str  # qemu | lxc
    name: str
    node: str
    first_seen: str
    last_seen: str
    current: bool  # the guest's latest event still shows the value
    search_sql: str  # Show events


def classify(value: str) -> tuple[Kind, str]:
    """An IP, a MAC (lowercase, colons), or a name, as the inventory records it."""
    text = value.strip()
    try:
        return "ip", str(ipaddress.ip_address(text))
    except ValueError:
        pass
    if _MAC.fullmatch(text):
        return "mac", text.lower().replace("-", ":")
    return "name", text.lower()


def _holds(rec: dict[str, Any], kind: Kind, value: str) -> bool:
    if rec.get("event") == "disappeared":
        return False
    if kind == "ip":
        return any(isinstance(x, dict) and x.get("ip") == value for x in rec.get("ips") or [])
    if kind == "mac":
        return value in (rec.get("macs") or [])
    return str(rec.get("name", "")).lower() == value


def events_sql(source_id: str, vmid: int) -> str:
    return (
        "SELECT time, source_id, raw\nFROM events\n"
        f"WHERE template_id = '{TEMPLATE}' AND source_id = {quote(source_id)}\n"
        f"  AND json_extract_string(raw, '$.vmid') = '{int(vmid)}'\nORDER BY time DESC"
    )


def _iso(t: Any) -> str:
    return t.astimezone(UTC).isoformat() if isinstance(t, datetime) else str(t)


def inventory_rows(
    engine: QueryEngine, scope: QueryScope
) -> list[tuple[str, datetime, dict[str, Any]]]:
    start = scope.start - LOOKBACK if scope.start else None
    window = QueryScope(scope.sources, start, scope.end)
    out = []
    for src, t, raw in engine.run(ROWS_SQL, window, row_cap=MAX_ROWS, timeout_s=20).rows:
        try:
            rec = json.loads(raw)
        except (TypeError, ValueError):
            continue
        when = t if isinstance(t, datetime) else datetime.fromisoformat(str(t))
        if isinstance(rec, dict) and isinstance(rec.get("vmid"), int):
            out.append((str(src), when if when.tzinfo else when.replace(tzinfo=UTC), rec))
    return out


def match_rows(
    rows: list[tuple[str, datetime, dict[str, Any]]], value: str, start: datetime | None = None
) -> list[Match]:
    """The guests that held `value` during the range, current holders first, then newest
    last seen. A guest whose hold ended (a later event without the value) before `start`
    is left out: the lookback rows only carry a hold into the range."""
    kind, clean = classify(value)
    seen: dict[tuple[str, int], dict[str, Any]] = {}
    latest: dict[tuple[str, int], dict[str, Any]] = {}
    for src, t, rec in rows:
        key = (src, int(rec["vmid"]))
        latest[key] = rec
        if not _holds(rec, kind, clean):
            if key in seen and "ended" not in seen[key]:
                seen[key]["ended"] = t
            continue
        got = seen.setdefault(key, {"first": t, "rec": rec})
        got["last"], got["rec"] = t, rec
        got.pop("ended", None)
    out = [
        Match(
            source_id=src,
            vmid=vmid,
            type=str(g["rec"].get("type", "")),
            name=str(g["rec"].get("name", "")),
            node=str(g["rec"].get("node", "")),
            first_seen=_iso(g["first"]),
            last_seen=_iso(g["last"]),
            current=_holds(latest[(src, vmid)], kind, clean),
            search_sql=events_sql(src, vmid),
        )
        for (src, vmid), g in seen.items()
        if not (start and "ended" in g and g["ended"] <= start)
    ]
    out.sort(key=lambda m: m.last_seen, reverse=True)
    return sorted(out, key=lambda m: not m.current)
