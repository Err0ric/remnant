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
from app.search.ask_summary import Sample

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
    origin: str = "generated"  # or a library query, "<pack>/<id>@<version>" (slice 1b)
    question: str = field(default="", repr=False)
    params: dict[str, str | int | float | bool] = field(default_factory=dict)
    provider_id: str = ""  # the provider that answered; the summary uses the same one
    template: str | None = None  # a library query's headline template (`answer`)


@dataclass(frozen=True, slots=True)
class Ran:
    """What the run returned, kept for the answer step (slice 1c): the rows a model may
    see, never sent back by the client, and the sources the query read."""

    sample: Sample | None
    sources: list[str]
    headline: str


class AskRuns:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._kept: OrderedDict[str, AskRun] = OrderedDict()
        self._ran: dict[str, Ran] = {}

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
        origin: str = "generated",
        params: dict[str, str | int | float | bool] | None = None,
        provider_id: str = "",
        template: str | None = None,
    ) -> AskRun:
        run = AskRun(
            str(uuid.uuid4()), user_id, sql, start, end, sources, list(call_ids), now,
            origin=origin, question=question, params=dict(params or {}),
            provider_id=provider_id, template=template,
        )  # fmt: skip
        with self._lock:
            self._kept[run.ask_id] = run
            while len(self._kept) > KEEP_AT_MOST:
                gone, _ = self._kept.popitem(last=False)
                self._ran.pop(gone, None)
        return run

    def ran(self, ask_id: str, result: Ran) -> None:
        with self._lock:
            if ask_id in self._kept:
                self._ran[ask_id] = result

    def result(self, ask_id: str, user_id: str, now: datetime) -> tuple[AskRun, Ran]:
        """The run and what it returned, for the person who asked, while fresh."""
        run = self.get(ask_id, user_id, now)
        with self._lock:
            got = self._ran.get(ask_id)
        if got is None:
            raise NotFoundError("Run the query first")
        return run, got

    def get(self, ask_id: str, user_id: str, now: datetime) -> AskRun:
        """The answer, only for the person who asked and only while it is fresh."""
        with self._lock:
            run = self._kept.get(ask_id)
        if run is None or run.user_id != user_id or now - run.at > KEEP_FOR:
            raise NotFoundError("That answer has expired. Ask again.")
        return run
