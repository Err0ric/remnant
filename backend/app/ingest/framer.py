"""Split a byte stream into messages (SPEC 3.5).

Newline framing is the default. Octet-counted framing (RFC 6587, `<len> <msg>`)
is auto-detected from the first bytes of a stream. Messages longer than
`max_len` are truncated and flagged, never dropped. Memory use is bounded by
`max_len` regardless of input.
"""

import re
from collections.abc import Iterable, Iterator
from typing import Literal

from app.ingest.records import Frame

FramingMode = Literal["auto", "newline", "octet"]

_OCTET_START = re.compile(rb"\d{1,10} <\d")
_OCTET_HEADER = re.compile(rb"(\d{1,10}) ")
_PARTIAL_LEN = re.compile(rb"\d{0,10}")
_DETECT_BYTES = 16


class Framer:
    def __init__(
        self, max_len: int = 8192, mode: FramingMode = "auto", flush_partial: bool = True
    ) -> None:
        if max_len <= 0:
            raise ValueError("max_len must be positive")
        self._max_len = max_len
        self._mode = mode
        self._flush_partial = flush_partial

    def frames(self, chunks: Iterable[bytes]) -> Iterator[Frame]:
        """Yield frames from an iterable of byte chunks.

        `pos` marks how far into `buf` has been consumed; the buffer is cut once per chunk
        rather than after every message, so a large chunk costs linear time, not quadratic.
        """
        mode = self._mode
        buf = b""
        pos = 0
        discarding_line = False  # newline mode: skipping the tail of an overlong line
        skip_bytes = 0  # octet mode: bytes of an overlong message still to discard

        for chunk in chunks:
            buf = buf[pos:] + chunk if pos else buf + chunk
            pos = 0
            if mode == "auto":
                if len(buf) < _DETECT_BYTES:
                    continue
                mode = "octet" if _OCTET_START.match(buf) else "newline"

            while True:
                if mode == "octet":
                    if skip_bytes:
                        dropped = min(skip_bytes, len(buf) - pos)
                        pos, skip_bytes = pos + dropped, skip_bytes - dropped
                        if skip_bytes:
                            break
                    header = _OCTET_HEADER.match(buf, pos)
                    if header is None:
                        if _PARTIAL_LEN.fullmatch(buf, pos):
                            break  # length digits still arriving
                        mode = "newline"  # not octet-counted after all
                        continue
                    size, start = int(header.group(1)), header.end()
                    if size > self._max_len:
                        if len(buf) - start < self._max_len:
                            break
                        yield Frame(buf[start : start + self._max_len], truncated=True)
                        skip_bytes = size - self._max_len
                        pos = start + self._max_len
                        continue
                    if len(buf) - start < size:
                        break
                    yield Frame(buf[start : start + size])
                    pos = start + size
                    continue

                # newline mode
                if discarding_line:
                    nl = buf.find(b"\n", pos)
                    if nl < 0:
                        pos = len(buf)
                        break
                    pos, discarding_line = nl + 1, False
                nl = buf.find(b"\n", pos)
                if nl < 0:
                    if len(buf) - pos > self._max_len:
                        yield Frame(buf[pos : pos + self._max_len], truncated=True)
                        pos, discarding_line = len(buf), True
                    break
                line, pos = buf[pos:nl].rstrip(b"\r"), nl + 1
                if len(line) > self._max_len:
                    yield Frame(line[: self._max_len], truncated=True)
                elif line:
                    yield Frame(line)

        yield from self._tail(buf[pos:], mode, discarding_line, skip_bytes)

    def _tail(
        self, buf: bytes, mode: FramingMode, discarding_line: bool, skip_bytes: int
    ) -> Iterator[Frame]:
        if mode == "auto" and buf:
            # Short stream: decide now, then reuse the normal path.
            yield from Framer(self._max_len, _detect(buf), self._flush_partial).frames([buf])
            return
        if not self._flush_partial or not buf or discarding_line or skip_bytes:
            return
        if mode == "octet":
            header = _OCTET_HEADER.match(buf)
            body = buf[header.end() :] if header else buf
            if body:
                yield Frame(body[: self._max_len], truncated=True)
            return
        line = buf.rstrip(b"\r")
        if line:
            yield Frame(line[: self._max_len], truncated=len(line) > self._max_len)


def _detect(buf: bytes) -> FramingMode:
    return "octet" if _OCTET_START.match(buf) else "newline"
