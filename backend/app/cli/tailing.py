"""Follow one source through the query API: shared by `remnant tail -f` and `remnant tui`."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.cli.client import Api

TAIL_COLUMNS = "time, source_id, device_hostname, actor_process_name, message"


def _iso(value: str) -> str:
    """Re-render a server timestamp so only a valid ISO value reaches the SQL text."""
    return datetime.fromisoformat(value).isoformat()


def strip_cursor(data: dict[str, Any]) -> dict[str, Any]:
    """Drop the helper columns (_seen, _id) used to follow."""
    return {**data, "columns": data["columns"][:-2], "rows": [r[:-2] for r in data["rows"]]}


class TailCursor:
    """Remembers which events were shown so each new one is returned exactly once.

    `source` must already be validated as a source id by the caller; the server guard
    and the per-user events view apply to every query regardless.
    """

    def __init__(
        self,
        api: Api,
        source: str,
        columns: str = TAIL_COLUMNS,
        where: str | None = None,
        start: str | None = None,
    ) -> None:
        self._api = api
        self._cols = columns
        self._start = start
        extra = f" AND ({where})" if where else ""
        self._base = f"FROM events WHERE source_id = '{source}'{extra}"
        self._seen: set[Any] = set()
        self._newest: str | None = None

    def latest(self, lines: int) -> dict[str, Any]:
        """The most recent `lines` events, oldest first."""
        data = self._api.query(
            f"SELECT {self._cols}, time_observed AS _seen, event_id AS _id {self._base} "
            f"ORDER BY coalesce(time, time_observed) DESC, time_observed DESC LIMIT {int(lines)}",
            start=self._start,
        )
        self._remember(data["rows"])
        data["rows"] = list(reversed(data["rows"]))
        return strip_cursor(data)

    def poll(self) -> dict[str, Any]:
        """Events that arrived since the last call; `rows` is empty when there are none."""
        since = f" AND time_observed >= TIMESTAMPTZ '{_iso(self._newest)}'" if self._newest else ""
        data = self._api.query(
            f"SELECT {self._cols}, time_observed AS _seen, event_id AS _id {self._base}{since} "
            "ORDER BY time_observed, coalesce(time, time_observed) LIMIT 1000",
            start=None if self._newest else self._start,
        )
        data["rows"] = [r for r in data["rows"] if r[-1] not in self._seen]
        self._remember(data["rows"])
        return strip_cursor(data)

    def _remember(self, rows: list[list[Any]]) -> None:
        if rows:
            self._seen.update(r[-1] for r in rows)
            newest = max(r[-2] for r in rows)
            if self._newest is None or newest > self._newest:
                self._newest = newest
