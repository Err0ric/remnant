"""A time without a zone means UTC, everywhere (owner order 2026-11-14).

Python reads a naive datetime as the server's local time in `astimezone`, while the
engine's scope filter wrote it as UTC: on a server outside UTC a naive start or end chose
other day folders and rollup days than the rows it filtered, so a window near midnight
skipped or added a day. Request times are read with `UtcDateTime` at the API's edge, and
the engine's `QueryScope` applies `utc` again, so nothing downstream sees a naive time.
"""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator


def utc(value: datetime) -> datetime:
    """The same instant in UTC; a time without a zone is taken to be UTC."""
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC)


def zoned(value: datetime) -> datetime:
    """A time without a zone as UTC (as `utc` reads it); one with a zone stays as given."""
    return value if value.tzinfo else utc(value)


# Every time a request sends (query, path, or body). A zone given is kept as given.
UtcDateTime = Annotated[datetime, AfterValidator(zoned)]
