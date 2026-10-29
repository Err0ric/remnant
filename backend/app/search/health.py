"""Health page data (ADR-0019): per-machine agent status and watched devices.

Watched devices are listed by an administrator (an IP address or a host name). A device
is healthy while it appears in events, unhealthy when silent longer than allowed, and
needs attention when its last two hours run well under its usual volume. Nothing here
connects to a device. The background check runs as the system over every source, like
the quiet-source watch (ADR-0014), and reads only match keys, times, and counts; what a
person sees is computed in their own scope.
"""

from __future__ import annotations

import ipaddress
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from app.alerts.dispatch import AlertDispatcher
from app.alerts.render import Alert
from app.core.branding import PRODUCT_NAME
from app.core.errors import NotFoundError, ParamInvalidError
from app.core.ids import new_id
from app.engine.duckdb import QueryEngine, QueryScope
from app.ingest.quiet import human
from app.meta.audit import AuditLog
from app.meta.db import MetaDB

MIN_SILENCE_S = 300
MAX_SILENCE_S = 86400
MAX_DEVICES = 200
MAX_TARGETS = 10
NAME_MAX = 80
HOURS = 24
LOW_RATIO = 0.25  # last two hours under a quarter of the usual hourly volume
LOW_MIN_USUAL = 10.0  # ...only when the device usually logs at least this much an hour
AGENT_ATTENTION = timedelta(hours=24)
INVENTORY_ATTENTION = timedelta(hours=48)  # the inventory script runs daily
AGENT_UNHEALTHY = timedelta(days=7)
TIMEOUT_S = 20

State = Literal["healthy", "attention", "unhealthy", "unknown"]
HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62})(\.[a-z0-9]([a-z0-9-]{0,62}))*\.?$")

# Every event matched by any address or host column, as one lower-case key per value;
# host names also match by their first label, so "fs01" finds FS01.corp.example. Times
# are the event's own, never later than when it was received (a clock running ahead
# cannot make a silent device look alive).
DEVICE_SQL = """
WITH k AS (
  SELECT least(coalesce(time, time_observed), time_observed) AS t, unnest(list_distinct([
    lower(src_endpoint_ip), lower(dst_endpoint_ip), lower(device_ip),
    lower(device_hostname), lower(src_endpoint_hostname), lower(dst_endpoint_hostname),
    split_part(lower(device_hostname), '.', 1),
    split_part(lower(src_endpoint_hostname), '.', 1),
    split_part(lower(dst_endpoint_hostname), '.', 1)
  ])) AS key
  FROM events
)
SELECT key, date_trunc('hour', t) AS hour, count(*) AS n, max(t) AS last
FROM k WHERE list_contains($keys, key)
GROUP BY 1, 2
LIMIT 20000"""

AGENT_SQL = """
SELECT source_id, coalesce(nullif(device_hostname, ''), nullif(src_endpoint_hostname, ''),
                           src_endpoint_ip, '(unknown machine)') AS machine,
       max(time_observed) AS last,
       count(*) FILTER (WHERE time_observed >= $since) AS n24,
       bool_or(template_id = 'claude_hooks') AS hooks,
       -- Records the hooks plugin could not send, reported by its next record (ADR-0026).
       coalesce(sum(TRY_CAST(json_extract_string(unmapped, '$.attr.dropped_since_last')
         AS BIGINT)) FILTER (WHERE time_observed >= $since), 0) AS dropped
FROM events
WHERE list_contains($sources, source_id) OR template_id = 'mcp_inventory'
GROUP BY 1, 2
ORDER BY 3 DESC
LIMIT 2000"""


_HOOK = "json_extract_string(unmapped, '$.attr.{}')"
# The hooks plugin per machine over 8 days (its queue keeps 7): records queued at its last
# check-in, records delivered more than 5 minutes after they happened in the last 24 hours
# (ADR-0026 offline queue).
HOOKS_SQL = f"""
SELECT source_id, coalesce(nullif(device_hostname, ''), '(unknown machine)') AS machine,
       arg_max(TRY_CAST({_HOOK.format("queued_at_send")} AS BIGINT), time_observed)
         FILTER (WHERE {_HOOK.format("queued_at_send")} IS NOT NULL) AS queued,
       count(*) FILTER (WHERE time_observed >= $since
         AND epoch(time_observed) - epoch(time) > 300) AS late
FROM events
WHERE template_id = 'claude_hooks'
GROUP BY 1, 2
LIMIT 2000"""  # noqa: S608  # fixed SQL text

# Sequence numbers that never arrived, per machine and install (a reinstall starts a new
# install id at 1, so it is not a gap). Each row is one gap: the numbers on either side
# and the times they happened.
GAP_SQL = f"""
WITH s AS (
  SELECT source_id, coalesce(nullif(device_hostname, ''), '(unknown machine)') AS machine,
         {_HOOK.format("install_id")} AS install_id,
         TRY_CAST({_HOOK.format("seq")} AS BIGINT) AS n, min(time) AS t
  FROM events
  WHERE template_id = 'claude_hooks' AND {_HOOK.format("seq")} IS NOT NULL
  GROUP BY 1, 2, 3, 4
), g AS (
  SELECT source_id, machine, install_id, n, t,
         lag(n) OVER (PARTITION BY source_id, machine, install_id ORDER BY n) AS prev,
         lag(t) OVER (PARTITION BY source_id, machine, install_id ORDER BY n) AS prev_t
  FROM s
)
SELECT source_id, machine, n - prev - 1 AS missing, prev_t, t
FROM g WHERE n - prev > 1
ORDER BY t DESC
LIMIT 500"""  # noqa: S608  # fixed SQL text


def normalize(value: str) -> str:
    """An IP address (any form) or a host name, lower case; anything else is refused."""
    v = value.strip().lower().rstrip(".")
    try:
        return str(ipaddress.ip_address(v))
    except ValueError:
        pass
    if not v or len(v) > 253 or not HOST_RE.fullmatch(v):
        raise ParamInvalidError("Give an IP address or a host name")
    return v


def _utc(value: Any) -> str:
    """'2026-10-27 09:00 UTC', for a sentence."""
    t = _parse(value)
    return t.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC") if t else str(value)


def _parse(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class DeviceWatch:
    device_id: str
    name: str
    match: str
    silence_s: int
    target_ids: list[str]
    state: str  # ok | quiet (alerting state, set by the background check)
    quiet_since: str | None
    created_by: str | None
    updated_at: str


@dataclass(slots=True)
class DeviceStatus:
    device: DeviceWatch
    state: State
    reason: str | None
    last_seen: str | None
    hourly: list[int] = field(default_factory=list)  # oldest first, HOURS values


@dataclass(slots=True)
class AgentStatus:
    kind: str  # "OpenTelemetry", "Claude hooks plugin", or "MCP inventory"
    source_id: str
    machine: str
    last_seen: str | None
    events_24h: int
    state: State
    reason: str | None
    dropped_24h: int = 0  # records the hooks plugin lost (queue full or over 7 days old)
    queued: int = 0  # records waiting on the machine at its last check-in
    late_24h: int = 0  # delivered more than 5 minutes after they happened
    missing: int = 0  # sequence numbers that never arrived, over 8 days
    gaps: list[str] = field(default_factory=list)  # "120 missing between Oct 27 9:00 and ..."


def evaluate(
    devices: list[DeviceWatch], rows: list[list[Any]], now: datetime
) -> list[DeviceStatus]:
    """States from DEVICE_SQL rows (key, hour, n, last)."""
    hour0 = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(
        hours=HOURS - 1
    )
    by_key: dict[str, tuple[datetime | None, list[int]]] = {}
    for key, hour, n, last in rows:
        last_t, counts = by_key.get(str(key), (None, [0] * HOURS))
        h = _parse(hour)
        if h is not None:
            i = int((h - hour0).total_seconds() // 3600)
            if 0 <= i < HOURS:
                counts[i] += int(n)
        t = _parse(last)
        if t is not None and (last_t is None or t > last_t):
            last_t = t
        by_key[str(key)] = (last_t, counts)
    out = []
    for d in devices:
        last, counts = by_key.get(d.match, (None, [0] * HOURS))
        if last is None:
            out.append(DeviceStatus(d, "unknown", "Not seen in the last 24 hours", None, counts))
            continue
        silent = (now - last).total_seconds()
        state: State = "healthy"
        reason = None
        if silent > d.silence_s:
            state, reason = "unhealthy", f"Silent {human(silent)} (allowed {human(d.silence_s)})"
        else:
            usual = sum(counts[: HOURS - 2]) / (HOURS - 2)
            recent = sum(counts[HOURS - 2 :]) / 2
            if usual >= LOW_MIN_USUAL and recent < LOW_RATIO * usual:
                pct = round(100 * recent / usual)
                state, reason = "attention", f"Quieter than usual: {pct}% of its normal volume"
        out.append(DeviceStatus(d, state, reason, last.isoformat(), counts))
    return out


class HealthService:
    def __init__(
        self,
        meta: MetaDB,
        engine: QueryEngine,
        otlp_sources: Callable[[], list[str]],
        dispatcher: AlertDispatcher,
        audit: AuditLog,
        link: str | None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._meta = meta
        self._engine = engine
        self._otlp_sources = otlp_sources
        self._dispatcher = dispatcher
        self._audit = audit
        self._link = link
        self._clock = clock

    # --- watched devices: settings -------------------------------------------------------

    def devices(self) -> list[DeviceWatch]:
        with self._meta.connect() as con:
            rows = con.execute("SELECT * FROM device_watches ORDER BY name, match").fetchall()
        return [_device(r) for r in rows]

    def save_device(
        self,
        device_id: str | None,
        name: str,
        match: str,
        silence_s: int,
        target_ids: list[str],
        actor: str | None,
        ip: str | None,
    ) -> DeviceWatch:
        label = re.sub(r"[\x00-\x1f\x7f]+", " ", name).strip()[:NAME_MAX]
        if not label:
            raise ParamInvalidError("Give the device a name")
        key = normalize(match)
        if not MIN_SILENCE_S <= silence_s <= MAX_SILENCE_S:
            raise ParamInvalidError("Allowed silence must be between 5 minutes and 24 hours")
        wanted = sorted(set(target_ids))
        if len(wanted) > MAX_TARGETS:
            raise ParamInvalidError(f"At most {MAX_TARGETS} alert targets")
        now = self._clock().astimezone(UTC).isoformat()
        existing = {d.device_id: d for d in self.devices()}
        old = existing.get(device_id) if device_id else None
        if device_id and old is None:
            raise NotFoundError("No such watched device")
        if any(d.match == key and d.device_id != device_id for d in existing.values()):
            raise ParamInvalidError("That address or host name is already watched")
        if old is None and len(existing) >= MAX_DEVICES:
            raise ParamInvalidError(f"At most {MAX_DEVICES} watched devices")
        with self._meta.connect() as con:
            known = {r[0] for r in con.execute("SELECT target_id FROM alert_targets")}
            if set(wanted) - known:
                raise ParamInvalidError("Unknown alert target")
            if old is None:
                device_id = new_id()
                con.execute(
                    "INSERT INTO device_watches (device_id, name, match, silence_s, target_ids,"
                    " state, quiet_since, created_by, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, 'ok', NULL, ?, ?, ?)",
                    (device_id, label, key, silence_s, json.dumps(wanted), actor, now, now),
                )
            else:
                # A change of address restarts the alert state, like ADR-0014.
                con.execute(
                    "UPDATE device_watches SET name = ?, match = ?, silence_s = ?,"
                    " target_ids = ?, updated_at = ?,"
                    " state = CASE WHEN match = ? THEN state ELSE 'ok' END,"
                    " quiet_since = CASE WHEN match = ? THEN quiet_since ELSE NULL END"
                    " WHERE device_id = ?",
                    (label, key, silence_s, json.dumps(wanted), now, key, key, device_id),
                )
        new = next(d for d in self.devices() if d.device_id == device_id)
        self._audit.write(
            "device_watch.change",
            "success",
            actor,
            ip,
            {"device_id": device_id, "from": _setting(old), "to": _setting(new)},
        )
        return new

    def delete_device(self, device_id: str, actor: str | None, ip: str | None) -> None:
        old = next((d for d in self.devices() if d.device_id == device_id), None)
        if old is None:
            raise NotFoundError("No such watched device")
        with self._meta.connect() as con:
            con.execute("DELETE FROM device_watches WHERE device_id = ?", (device_id,))
        self._audit.write(
            "device_watch.change",
            "success",
            actor,
            ip,
            {"device_id": device_id, "from": _setting(old), "to": None},
        )

    # --- status ---------------------------------------------------------------------------

    def device_status(self, allowed: list[str] | None) -> list[DeviceStatus]:
        """Each watched device as the viewer's sources show it."""
        devices = self.devices()
        if not devices:
            return []
        now = self._clock().astimezone(UTC)
        rows = self._rows(devices, QueryScope(allowed, now - timedelta(hours=HOURS), now))
        return evaluate(devices, rows, now)

    def agents(self, allowed: list[str] | None) -> list[AgentStatus]:
        now = self._clock().astimezone(UTC)
        otlp = self._otlp_sources()
        scope = QueryScope(allowed, now - AGENT_UNHEALTHY * 2, now)
        result = self._engine.run(
            AGENT_SQL,
            scope,
            {"sources": otlp or [""], "since": now - timedelta(hours=24)},
            timeout_s=TIMEOUT_S,
        )
        out = []
        for source_id, machine, last, n24, hooks, dropped in result.rows:
            t = _parse(last)
            inventory = str(source_id) not in otlp
            limit = INVENTORY_ATTENTION if inventory else AGENT_ATTENTION
            state: State = "healthy"
            reason = None
            if t is not None:
                gap = now - t
                if gap > AGENT_UNHEALTHY:
                    state, reason = "unhealthy", f"Last reported {human(gap.total_seconds())} ago"
                elif gap > limit:
                    state, reason = "attention", f"Last reported {human(gap.total_seconds())} ago"
            lost = int(dropped or 0)
            if lost and state == "healthy":
                noun = "event" if lost == 1 else "events"
                state = "attention"
                reason = (
                    f"{lost} {noun} lost in 24 hours: the queue on the machine was full or "
                    "older than 7 days"
                )
            kind = "MCP inventory" if inventory else "OpenTelemetry"
            if hooks and not inventory:
                kind = "Claude hooks plugin"
            out.append(
                AgentStatus(
                    kind,
                    str(source_id),
                    str(machine),
                    t.isoformat() if t else None,
                    int(n24 or 0),
                    state,
                    reason,
                    lost,
                )
            )
        self._hook_detail(out, allowed, now)
        return out

    def _hook_detail(
        self, out: list[AgentStatus], allowed: list[str] | None, now: datetime
    ) -> None:
        """Queue, late, and gap figures for the hooks plugin's machines (ADR-0026)."""
        rows = [a for a in out if a.kind == "Claude hooks plugin"]
        if not rows:
            return
        sources = sorted({a.source_id for a in rows})
        if allowed is not None:
            sources = [x for x in sources if x in set(allowed)]
        scope = QueryScope(sources, now - timedelta(days=8), now)
        by = {(a.source_id, a.machine): a for a in rows}
        since = {"since": now - timedelta(hours=24)}
        for src, machine, queued, late in self._engine.run(
            HOOKS_SQL, scope, since, timeout_s=TIMEOUT_S
        ).rows:
            a = by.get((str(src), str(machine)))
            if a is not None:
                a.queued, a.late_24h = int(queued or 0), int(late or 0)
        for src, machine, missing, before, after in self._engine.run(
            GAP_SQL, scope, timeout_s=TIMEOUT_S
        ).rows:
            a = by.get((str(src), str(machine)))
            if a is None:
                continue
            a.missing += int(missing)
            if len(a.gaps) < 5:
                a.gaps.append(f"{int(missing)} missing between {_utc(before)} and {_utc(after)}")
        for a in rows:
            if a.missing and a.state == "healthy":
                noun = "event" if a.missing == 1 else "events"
                a.state = "attention"
                a.reason = (
                    f"{a.missing} {noun} never arrived (gaps in the plugin's sequence): "
                    "lost on the machine, or removed"
                )

    def _rows(self, devices: list[DeviceWatch], scope: QueryScope) -> list[list[Any]]:
        keys = sorted({d.match for d in devices})
        return self._engine.run(DEVICE_SQL, scope, {"keys": keys}, timeout_s=TIMEOUT_S).rows

    # --- background check -------------------------------------------------------------------

    def tick(self) -> int:
        """Alert on devices that went silent or came back; returns how many changed."""
        devices = self.devices()
        if not devices:
            return 0
        now = self._clock().astimezone(UTC)
        rows = self._rows(devices, QueryScope(None, now - timedelta(hours=HOURS + 1), now))
        changed = 0
        for st in evaluate(devices, rows, now):
            d = st.device
            # Not seen at all since being added or changed: give it the allowed silence first.
            changed_at = _parse(d.updated_at) or now
            if st.last_seen is None and (now - changed_at).total_seconds() < d.silence_s:
                continue
            silent = st.state == "unhealthy" or st.last_seen is None
            if d.state == "ok" and silent:
                self._set(d.device_id, "quiet", now.isoformat())
                self._alert(d, "device_quiet", st.reason or "Not seen", st.last_seen)
                changed += 1
            elif d.state == "quiet" and not silent:
                self._set(d.device_id, "ok", None)
                self._alert(d, "device_resumed", "Seen in events again", st.last_seen)
                changed += 1
        return changed

    def _set(self, device_id: str, state: str, since: str | None) -> None:
        with self._meta.connect() as con:
            con.execute(
                "UPDATE device_watches SET state = ?, quiet_since = ? WHERE device_id = ?",
                (state, since, device_id),
            )

    def _alert(self, d: DeviceWatch, kind: str, detail: str, last: str | None) -> None:
        self._audit.write(
            "device.quiet" if kind == "device_quiet" else "device.resumed",
            "success",
            None,
            None,
            {"device_id": d.device_id, "last_seen": last},
        )
        if not d.target_ids:
            return
        alert = Alert(
            kind="device_quiet" if kind == "device_quiet" else "device_resumed",
            title=d.name,
            detail=detail,
            count=None,
            reason=None,
            range_start=last,
            range_end=None,
            link=f"{self._link}/health" if self._link else None,
            product=PRODUCT_NAME,
        )
        self._dispatcher.enqueue(alert, d.target_ids, None, None)


def _setting(d: DeviceWatch | None) -> dict[str, Any] | None:
    if d is None:
        return None
    return {"name": d.name, "match": d.match, "silence_s": d.silence_s, "targets": d.target_ids}


def _device(r: Any) -> DeviceWatch:
    return DeviceWatch(
        r["device_id"],
        r["name"],
        r["match"],
        int(r["silence_s"]),
        list(json.loads(r["target_ids"] or "[]")),
        r["state"],
        r["quiet_since"],
        r["created_by"],
        r["updated_at"],
    )
