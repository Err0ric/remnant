"""A log line goes to stderr as it is when written (a flaky "I/O operation on closed file"
on #500: logging was configured with a test's captured stream, closed after that test)."""

import io
import sys

import pytest
import structlog

from app.core.logging import configure_logging


def test_a_replaced_stderr_is_used_and_a_closed_one_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = io.StringIO()
    monkeypatch.setattr(sys, "stderr", first)
    configure_logging()
    first.close()  # the stream configured with is gone, as after a captured test
    second = io.StringIO()
    monkeypatch.setattr(sys, "stderr", second)
    structlog.get_logger("t").warning("late.bound")
    assert '"event": "late.bound"' in second.getvalue()
