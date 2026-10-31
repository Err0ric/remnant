"""Follow one source: the latest lines through the query API, then the server's live stream
(ADR-0036 row 10). Shared by `remnant tail -f` and `remnant tui`."""

from __future__ import annotations

from typing import Any

from app.cli.client import Api

TAIL_COLUMNS = "time, source_id, device_hostname, actor_process_name, message"


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
        self._at_newest: set[str] = set()

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

    def _remember(self, rows: list[list[Any]]) -> None:
        if rows:
            self._seen.update(r[-1] for r in rows)
            newest = max(r[-2] for r in rows)
            if self._newest is None or newest > self._newest:
                self._newest = newest
            self._at_newest = {str(r[-1]) for r in rows if r[-2] == self._newest}

    # The live stream (ADR-0036 row 10): the server keeps the cursor from here on.

    def follow_sql(self) -> str:
        """The row query the server follows: the same columns and filter, no cursor."""
        return f"SELECT {self._cols} {self._base}"

    def cursor(self) -> tuple[str | None, list[str]]:
        """Where the stream starts: after the newest event shown, and its ids."""
        return self._newest, sorted(self._at_newest)

    def advance(self, cursor: dict[str, Any]) -> None:
        """Take the cursor a `rows` event carries, so a restart resumes from it."""
        self._newest = str(cursor["t"])
        self._at_newest = {str(i) for i in cursor.get("ids", [])}
