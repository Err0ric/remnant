"""Structured JSON logging (CLAUDE.md section 4).

Never log raw event content at INFO or above, provider keys, prompt bodies,
passwords, tokens, or query strings.
"""

import io
import logging
import sys
from typing import TextIO, cast

import structlog


class _Stderr(io.TextIOBase):
    """`sys.stderr` as it is at each write, not as it was at configure time. A server's
    stderr never changes; under a test runner it is swapped per test, and a stream kept
    from an earlier test is closed ("I/O operation on closed file")."""

    def write(self, text: str) -> int:
        return sys.stderr.write(text)

    def flush(self) -> None:
        sys.stderr.flush()


_STDERR = cast(TextIO, _Stderr())  # write and flush are all PrintLogger uses


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=level)
    # The HTTP client logs every request at INFO (each Loki poll, each connector call):
    # noise, and URLs can carry query text. Warnings and errors still show.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.PrintLoggerFactory(file=_STDERR),
        cache_logger_on_first_use=False,  # lets tests capture; negligible cost here
    )
