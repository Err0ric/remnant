"""The SQL each Ask answer produced, held for a short while so it can run (ADR-0042 slice
1a). The client runs an answer by its id, never by sending SQL back: what runs is exactly
what the model wrote and the self-check passed, for the person who asked."""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.core.errors import NotFoundError

KEEP_FOR = timedelta(minutes=30)
KEEP_AT_MOST = 500


@dataclass(frozen=True, slots=True)
class AskRun:
    ask_id: str
    user_id: str
    sql: str
    start: datetime | None
    end: datetime | None
    sources: list[str] | None  # the client's filter; the scope is rebuilt from grants
    call_ids: list[str]
    at: datetime
    origin: str = "generated"  # or a library query id (slice 1b)
    question: str = field(default="", repr=False)


class AskRuns:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._kept: OrderedDict[str, AskRun] = OrderedDict()

    def keep(
        self,
        user_id: str,
        sql: str,
        start: datetime | None,
        end: datetime | None,
        sources: list[str] | None,
        call_ids: list[str],
        now: datetime,
        question: str = "",
    ) -> AskRun:
        run = AskRun(
            str(uuid.uuid4()), user_id, sql, start, end, sources, list(call_ids), now,
            question=question,
        )  # fmt: skip
        with self._lock:
            self._kept[run.ask_id] = run
            while len(self._kept) > KEEP_AT_MOST:
                self._kept.popitem(last=False)
        return run

    def get(self, ask_id: str, user_id: str, now: datetime) -> AskRun:
        """The answer, only for the person who asked and only while it is fresh."""
        with self._lock:
            run = self._kept.get(ask_id)
        if run is None or run.user_id != user_id or now - run.at > KEEP_FOR:
            raise NotFoundError("That answer has expired. Ask again.")
        return run
