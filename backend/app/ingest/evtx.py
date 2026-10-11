"""Native Windows .evtx reading (SPEC 4.4, decision D4).

An .evtx file is a binary ring buffer of 64 KiB chunks, not lines, so it gets its own
reader. Each record is rendered to JSON by the `evtx` library (Rust, memory safe) and that
JSON text is the frame, and so the event's `raw`.

Work per pass is bounded: chunk headers name their record-id range, so only the chunks
holding ids after the checkpoint are handed to the library (rebuilt into a small in-memory
file), lowest ids first, up to a record and chunk budget. The record at the checkpoint id is
re-read too and its digest returned, so the caller can tell the same log grown from a
different log (another host, or a cleared log) that reuses the same ids. A corrupt record is
counted and skipped; it never stops the rest of the file.
"""

import hashlib
import heapq
import io
import itertools
import struct
import zlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, BinaryIO

from evtx import PyEvtxParser

from app.ingest.records import Frame

MAX_RECORDS_PER_PASS = 5_000
MAX_CHUNKS_PER_PASS = 256  # 16 MiB of chunk data handed to the parser per pass
MAX_ERRORS = 1_000  # past this many bad records the rest of the batch is abandoned
FILE_HEADER = 4_096
CHUNK = 65_536
_PER_CHUNK_CAP = 4_096  # no chunk holds more records than this; caps hostile header ranges
MAX_BATCH_BYTES = 32 << 20  # rendered JSON kept per pass, whatever the record count
_MAX_CHUNKS = 0xFFFF  # the file header counts chunks in 16 bits


@dataclass(frozen=True, slots=True)
class EvtxBatch:
    frames: list[tuple[int, Frame]]  # (record id, frame), ascending ids
    highest_id: int  # the largest record id any chunk header names
    errors: int  # records the library could not render
    complete: bool  # False when more records after the batch are waiting
    after_digest: str | None  # digest of the record at the checkpoint id, if still present
    last_digest: str | None  # digest of the last record in `frames`
    short: bool = False  # smaller than its header says: a copy still being written
    # Records after the checkpoint that could not be read: ids the parsed chunk headers
    # list but no record carried (the library drops some damage silently), or more
    # explicit errors if that is larger.
    unreadable: int = 0
    # Ids after the checkpoint that no chunk header lists, between two chunks: (first, last).
    # Seen when a copy is taken while Windows is still writing a chunk (its header lags).
    gap: tuple[int, int] | None = None
    digests: list[str] = field(default_factory=list)  # one per frame, same order


def record_digest(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8", errors="replace")).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class _Chunk:
    index: int
    first: int
    last: int
    head: bytes  # the first 128 header bytes: id range, free space, records checksum


class EvtxReader:
    def __init__(
        self,
        max_records: int = MAX_RECORDS_PER_PASS,
        max_len: int = 65_536,
        max_chunks: int = MAX_CHUNKS_PER_PASS,
    ) -> None:
        self._max_records = max_records
        self._max_len = max_len
        self._max_chunks = max_chunks

    def read(self, fh: BinaryIO, after_id: int) -> EvtxBatch:
        """Records with an id above `after_id`, lowest first, within the pass budget."""
        header, chunks, forged = _chunk_scan(fh)
        if header is None:
            return EvtxBatch([], 0, 1, True, None, None, unreadable=1)
        # Each ignored chunk past the checkpoint hides at least one record: never silent.
        hidden = sum(1 for first in forged if first > after_id)
        (declared,) = struct.unpack_from("<H", header, 42)
        fh.seek(0, io.SEEK_END)
        short = fh.tell() < FILE_HEADER + declared * CHUNK
        highest = max((c.last for c in chunks), default=0)
        wanted = sorted((c for c in chunks if c.last > after_id), key=lambda c: c.first)
        selected: list[_Chunk] = []
        budget = 0
        for chunk in wanted:
            if budget >= self._max_records or len(selected) >= self._max_chunks:
                break
            selected.append(chunk)
            new = chunk.last - max(chunk.first, after_id + 1) + 1
            budget += min(max(new, 0), _PER_CHUNK_CAP)
        pending = len(selected) < len(wanted)
        # The chunk holding the checkpoint record is read too (for its digest), off budget.
        selected += [c for c in chunks if c.first <= after_id <= c.last and c not in selected][:1]

        listed = sum(max(c.last - max(c.first, after_id + 1) + 1, 0) for c in selected)
        errors = 0
        waiting = 0
        kept = 0  # bytes of rendered JSON in the batch
        ceiling: int | None = None  # ids from here up were dropped for the byte budget
        after_digest: str | None = None
        batch: list[tuple[int, bytes, bool, str]] = []  # heap of (-id, frame, cut, digest)
        for item in _records(_rebuild(fh, header, selected)):
            if not isinstance(item, dict):
                errors += 1
                if errors > MAX_ERRORS:
                    break
                continue
            record_id = item.get("event_record_id")
            data = item.get("data")
            if (
                not isinstance(record_id, int)
                or isinstance(record_id, bool)
                or record_id < 0
                or not isinstance(data, str)
            ):
                errors += 1
                continue
            if record_id == after_id:
                after_digest = record_digest(data)
            if record_id <= after_id:
                continue
            waiting += 1
            if len(batch) >= self._max_records and -batch[0][0] < record_id:
                continue  # a lower id already fills the batch; this one waits
            if ceiling is not None and record_id >= ceiling:
                continue  # waits for a later pass, after the lower ids already kept
            encoded = data.encode("utf-8", errors="replace")
            entry = (
                -record_id,
                encoded[: self._max_len],
                len(encoded) > self._max_len,
                record_digest(data),
            )
            if len(batch) < self._max_records:
                heapq.heappush(batch, entry)
            else:
                kept -= len(heapq.heapreplace(batch, entry)[1])
            kept += len(entry[1])
            # Small records can render to large JSON (templates live in the chunk), so the
            # batch is also bounded in bytes: the highest ids wait for the next pass.
            while kept > MAX_BATCH_BYTES and len(batch) > 1:
                dropped = heapq.heappop(batch)
                kept -= len(dropped[1])
                ceiling = -dropped[0] if ceiling is None else min(ceiling, -dropped[0])
        ordered = sorted(batch, reverse=True)
        gap = None
        by_first = sorted(chunks, key=lambda c: c.first)
        for a, b in itertools.pairwise(by_first):
            if a.last >= after_id and b.first > a.last + 1:
                gap = (a.last + 1, b.first - 1)
                break
        frames = [(-neg, Frame(data=data, truncated=cut)) for neg, data, cut, _ in ordered]
        return EvtxBatch(
            frames=frames,
            highest_id=highest,
            errors=errors,
            complete=not pending and waiting <= self._max_records and ceiling is None,
            after_digest=after_digest,
            last_digest=ordered[-1][3] if ordered else None,
            short=short,
            unreadable=max(listed - waiting, errors) + hidden,
            gap=gap,
            digests=[d for _, _, _, d in ordered],
        )


def file_signature(fh: BinaryIO) -> str:
    """Changes whenever records are added or replaced: size, the file header (next record
    id), and every chunk header (id range, free space, records checksum). mtime is not
    used: Windows does not always update it on a live log, and copy tools preserve it."""
    header, chunks = _chunk_index(fh)
    fh.seek(0, io.SEEK_END)
    digest = hashlib.sha256(header or b"")
    for c in chunks:
        digest.update(struct.pack("<I", c.index) + c.head)
    return f"{fh.tell()}:{digest.hexdigest()[:32]}"


def _chunk_index(fh: BinaryIO) -> tuple[bytes | None, list[_Chunk]]:
    """The file header and the record-id range of every chunk with a valid header."""
    header, chunks, _ = _chunk_scan(fh)
    return header, chunks


def _chunk_scan(fh: BinaryIO) -> tuple[bytes | None, list[_Chunk], list[int]]:
    """As _chunk_index, plus the first record id of each chunk whose range is forged."""
    fh.seek(0)
    header = fh.read(FILE_HEADER)
    if len(header) < 128 or header[:8] != b"ElfFile\x00":
        return None, [], []
    chunks: list[_Chunk] = []
    forged: list[int] = []
    index = 0
    while True:
        fh.seek(FILE_HEADER + index * CHUNK)
        head = fh.read(128)
        if len(head) < 40:
            break
        if head[:8] == b"ElfChnk\x00":
            first, last = struct.unpack_from("<QQ", head, 24)
            # A range wider than any chunk can hold is a forged header: ignored, so it can
            # neither inflate counts nor hide a log swap behind a huge highest id.
            if first <= last and last - first < _PER_CHUNK_CAP:
                chunks.append(_Chunk(index, first, last, head))
            else:
                forged.append(first)
        index += 1
        if index >= _MAX_CHUNKS:
            break
    return header, chunks, forged


def _rebuild(fh: BinaryIO, header: bytes, chunks: list[_Chunk]) -> io.BytesIO:
    """A valid .evtx holding only `chunks`: chunks are self-contained, so this is safe."""
    out = bytearray(header)
    struct.pack_into("<QQ", out, 8, 0, max(len(chunks) - 1, 0))
    struct.pack_into("<H", out, 42, len(chunks))
    struct.pack_into("<I", out, 124, zlib.crc32(bytes(out[:120])))
    for chunk in sorted(chunks, key=lambda c: c.index):
        fh.seek(FILE_HEADER + chunk.index * CHUNK)
        out += fh.read(CHUNK).ljust(CHUNK, b"\x00")
    return io.BytesIO(bytes(out))


def _records(fh: BinaryIO) -> Iterator[Any]:
    """Records from the library; errors become items. A panic in the native parser
    (pyo3 raises it as a BaseException) ends this file's batch, never the ingest loop."""
    try:
        records = iter(PyEvtxParser(fh, number_of_threads=1).records_json())
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:  # native parser: any failure is bad input
        yield RuntimeError(f"not an evtx file: {type(exc).__name__}")
        return
    while True:
        try:
            yield next(records)
        except StopIteration:
            return
        except (RuntimeError, OSError, ValueError) as exc:
            yield exc
        except (KeyboardInterrupt, SystemExit, GeneratorExit):
            raise
        except BaseException as exc:  # a native panic arrives as BaseException
            yield RuntimeError(f"evtx parser stopped: {type(exc).__name__}")
            return
