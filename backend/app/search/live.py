"""Live mode on Search (ADR-0036): follow new event rows of one query.

The server keeps the cursor (newest `time_observed` sent, and the event ids sent at that
instant), polls every POLL_S on the caller's events view built at the start, through the
guard, on the read-only connection (rules 7 and 13), and pushes rows as server-sent
events. Only row queries qualify (row 2). At most MAX_STREAMS per user across browser,
CLI, and TUI (row 5); each stops after the administrator's time limit. Start and stop are
audited once each (row 6); polls are not.
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from app.core.errors import ConflictError, QueryRejectedError
from app.engine.duckdb import QueryEngine, QueryScope
from app.ingest.connectors import anthropic, loki, m365
from app.meta.db import MetaDB
from app.search.params import RESERVED, compile_sql, placeholders

POLL_S = 2.0
LAG_EVERY_S = 10.0
MAX_STREAMS = 2
PUSH_ROWS = 500  # rows per push; the rest wait for the next poll
STOP_ROWS = 1_000  # more new rows than this in one poll stops the stream
LOOKBACK = timedelta(days=1)  # event time window the cursor reads (partition pruning)
DEFAULT_LIMIT_MIN = 30
NOT_LIVE = "Live works on event rows. Remove {what}, or use Run."
MSG_LIMIT = "Live stopped after {minutes} minutes. Resume to keep following."
MSG_ACCESS = "Your access changed; start Live again."
MSG_BACKFILL = "More than 1,000 events since you paused; showing the newest 1,000."
MSG_TOO_MANY = "More than 1,000 new events in {secs:g} seconds; narrow the search."
Client = Literal["browser", "cli", "tui"]
PULL_EVERY = {
    "m365": m365.POLL_EVERY,
    "anthropic": anthropic.POLL_EVERY,
    "loki": loki.POLL_EVERY,
}
CLIENT_LABEL = {"browser": "Search in a browser", "cli": "tail -f", "tui": "the TUI tail pane"}


def live_sql(sql: str, newest: bool = False) -> str:
    """The query as a follow query, or QueryRejectedError saying why it cannot be (row 2).

    Adds the cursor columns and the cursor condition; `{{start}}` and `{{end}}` become the
    stream's start and an open end. The engine still guards the result."""
    names = placeholders(sql)
    if names - RESERVED:
        raise QueryRejectedError("Live takes no parameters other than {{start}} and {{end}}")
    text = compile_sql(sql).strip().rstrip(";").strip()
    try:
        trees = [t for t in sqlglot.parse(text, read="duckdb") if t is not None]
    except SqlglotError as exc:
        raise QueryRejectedError("Could not parse SQL as a single SELECT statement") from exc
    if len(trees) != 1:
        raise QueryRejectedError("Only one statement is allowed per query")
    tree = trees[0]
    if not isinstance(tree, exp.Select):
        raise QueryRejectedError(NOT_LIVE.format(what="UNION"))
    checks: list[tuple[bool, str]] = [
        (tree.args.get("with_") is not None or tree.args.get("with") is not None, "WITH"),
        (tree.args.get("group") is not None, "GROUP BY"),
        (tree.args.get("having") is not None, "HAVING"),
        (tree.args.get("distinct") is not None, "DISTINCT"),
        (tree.args.get("limit") is not None, "LIMIT"),
        (tree.args.get("joins") is not None and bool(tree.args.get("joins")), "the JOIN"),
        (tree.find(exp.AggFunc) is not None, "the aggregate"),
        (tree.find(exp.Window) is not None, "the window function"),
    ]
    for bad, what in checks:
        if bad:
            raise QueryRejectedError(NOT_LIVE.format(what=what))
    tables = [t for t in tree.find_all(exp.Table)]
    if len(tables) != 1 or tables[0].name != "events" or tree.find(exp.Subquery) is not None:
        raise QueryRejectedError(NOT_LIVE.format(what="subqueries and other tables"))
    tree = tree.select(
        exp.alias_(exp.column("time_observed"), "_live_t"),
        exp.alias_(exp.column("event_id"), "_live_id"),
        append=True,
        copy=True,
    )
    tree = tree.where("time_observed >= $since", append=True, copy=False)
    tree.set("order", None)
    order = ("time_observed DESC", "event_id DESC") if newest else ("time_observed", "event_id")
    tree = tree.order_by(*order, copy=False).limit(STOP_ROWS + 1, copy=False)
    return tree.sql(dialect="duckdb")


def sql_hash(sql: str) -> str:
    return hashlib.sha256(sql.encode()).hexdigest()


@dataclass(slots=True)
class Stream:
    stream_id: str
    user_id: str
    client: Client
    started_at: datetime
    stop: threading.Event = field(default_factory=threading.Event)

    def describe(self) -> str:
        return f"{CLIENT_LABEL[self.client]} since {self.started_at.strftime('%H:%M')} UTC"


class LiveRegistry:
    """Open streams per user (row 5). Thread-safe; lives for the server's life."""

    def __init__(self, meta: MetaDB, poll_s: float = POLL_S) -> None:
        self._meta = meta
        self._lock = threading.Lock()
        self._streams: dict[str, Stream] = {}
        self.poll_s = poll_s
        self.limit_override_s: float | None = None  # tests only

    def mine(self, user_id: str) -> list[Stream]:
        with self._lock:
            return sorted(
                (s for s in self._streams.values() if s.user_id == user_id),
                key=lambda s: s.started_at,
            )

    def open(self, user_id: str, client: Client, now: datetime) -> Stream:
        with self._lock:
            have = [s for s in self._streams.values() if s.user_id == user_id]
            if len(have) >= MAX_STREAMS:
                names = ", ".join(s.describe() for s in sorted(have, key=lambda s: s.started_at))
                raise ConflictError(
                    f"You have {len(have)} live searches open: {names}. Stop one to start another."
                )
            s = Stream(str(uuid.uuid4()), user_id, client, now)
            self._streams[s.stream_id] = s
            return s

    def close(self, stream_id: str) -> None:
        with self._lock:
            self._streams.pop(stream_id, None)

    def stop(self, user_id: str, stream_id: str) -> bool:
        with self._lock:
            s = self._streams.get(stream_id)
            if s is None or s.user_id != user_id:
                return False
            s.stop.set()
            return True

    def limit_s(self) -> float:
        if self.limit_override_s is not None:
            return self.limit_override_s
        return float(limit_minutes(self._meta) * 60)


def limit_minutes(meta: MetaDB) -> int:
    with meta.connect() as con:
        row = con.execute("SELECT live_limit_minutes FROM install_settings WHERE id = 1").fetchone()
    return int(row[0]) if row and row[0] else DEFAULT_LIMIT_MIN


def set_limit_minutes(meta: MetaDB, minutes: int, user_id: str) -> int:
    with meta.connect() as con:
        con.execute(
            "INSERT INTO install_settings (id, live_limit_minutes, updated_by) VALUES (1, ?, ?)"
            " ON CONFLICT (id) DO UPDATE SET live_limit_minutes = excluded.live_limit_minutes,"
            " updated_by = excluded.updated_by",
            (minutes, user_id),
        )
    return limit_minutes(meta)


@dataclass(slots=True)
class Cursor:
    """Newest time_observed sent, and the ids sent at exactly that time."""

    t: datetime
    ids: set[str] = field(default_factory=set)


@dataclass(slots=True)
class Poll:
    columns: list[str]
    rows: list[list[Any]]
    total: int  # new rows found this poll (before the push cap)
    too_many: bool


def poll(
    engine: QueryEngine,
    sql: str,
    sources: list[str] | None,
    cursor: Cursor,
    start: datetime,
    newest: bool = False,
) -> Poll:
    """New rows after the cursor, oldest first; advances the cursor over what it returns.
    With `newest` (Resume after a long pause, row 12), `sql` is the newest-first form and
    the newest STOP_ROWS are returned instead of stopping."""
    res = engine.run(
        sql, QueryScope(sources, start - LOOKBACK, None), {"since": cursor.t},
        row_cap=STOP_ROWS + 1, intel=False, name="search.live",
    )  # fmt: skip
    cols = list(res.columns)
    ti, ii = cols.index("_live_t"), cols.index("_live_id")
    fresh = [r for r in res.rows if str(r[ii]) not in cursor.ids]
    if newest:
        fresh = list(reversed(fresh[:STOP_ROWS]))
        sent = fresh
    elif len(fresh) > STOP_ROWS:
        return Poll(cols[:-2], [], len(fresh), True)
    else:
        sent = fresh[:PUSH_ROWS]
    for r in sent:
        t = _utc(r[ti])
        if t > cursor.t:
            cursor.t, cursor.ids = t, {str(r[ii])}
        elif t == cursor.t:
            cursor.ids.add(str(r[ii]))
    rows = [[_cell(v) for v in r[:-2]] for r in sent]
    return Poll(cols[:-2], rows, len(fresh), False)


def lag(
    engine: QueryEngine, sources: list[str] | None, kinds: dict[str, str], now: datetime
) -> list[dict[str, Any]]:
    """Per source in scope: newest time_observed and its age; a connector's pull interval
    so a minutes-long gap reads as normal (row 7)."""
    res = engine.run(
        "SELECT source_id, max(time_observed) FROM events GROUP BY 1",
        QueryScope(sources, now - LOOKBACK, None), intel=False, name="search.live_lag",
    )  # fmt: skip
    out = []
    for src, newest in sorted(res.rows):
        t = _utc(newest) if newest is not None else None
        every = PULL_EVERY.get(kinds.get(str(src), ""))
        out.append(
            {
                "source": str(src),
                "newest": t.isoformat() if t else None,
                "age_s": round((now - t).total_seconds()) if t else None,
                "pull_every_s": int(every.total_seconds()) if every else None,
            }
        )
    return out


def _utc(v: Any) -> datetime:
    t = v if isinstance(v, datetime) else datetime.fromisoformat(str(v))
    return (t if t.tzinfo else t.replace(tzinfo=UTC)).astimezone(UTC)


def _cell(v: Any) -> Any:
    return v.isoformat() if isinstance(v, datetime) else v
