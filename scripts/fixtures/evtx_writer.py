"""Minimal EVTX writer for synthetic test fixtures (no real event logs in the repo).

Writes the Windows XML Event Log container: a 4 KiB file header, then 64 KiB chunks of
event records whose BinXML uses direct elements with inline names (no templates, no
shared string table). That subset is valid per MS-EVEN6 and is what the `evtx` parser
reads in records it did not template. Checksums are real CRC32 values.

Layout references: MS-EVEN6 (BinXml), libyal libevtx format notes, and the field offsets
the `evtx` crate reads (file header 0..128, chunk header 0..512, records from 512).
"""

import struct
import zlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

CHUNK_SIZE = 65_536
FILE_HEADER_SIZE = 4_096
CHUNK_HEADER_SIZE = 512
EVENT_NS = "http://schemas.microsoft.com/win/2004/08/events/event"

# BinXML value types used here (MS-EVEN6 2.2.12).
STRING, UINT8, UINT16, UINT32, UINT64, FILETIME, HEXINT64 = 0x01, 0x04, 0x06, 0x08, 0x0A, 0x11, 0x15


@dataclass
class Value:
    kind: int
    value: object

    def encode(self) -> bytes:
        k, v = self.kind, self.value
        if k == STRING:
            text = str(v).encode("utf-16-le")
            return struct.pack("<BH", k, len(text) // 2) + text
        fmt = {UINT8: "<BB", UINT16: "<BH", UINT32: "<BI", UINT64: "<BQ", FILETIME: "<BQ",
               HEXINT64: "<BQ"}[k]
        return struct.pack(fmt, k, v)


@dataclass
class Element:
    name: str
    attrs: list[tuple[str, Value]] = field(default_factory=list)
    children: list["Element | Value"] = field(default_factory=list)


def text(name: str, value: object, kind: int = STRING, **attrs: Value) -> Element:
    return Element(name, list(attrs.items()), [Value(kind, value)])


def filetime(t: datetime) -> int:
    delta = t - datetime(1601, 1, 1, tzinfo=UTC)
    return (delta.days * 86_400 + delta.seconds) * 10_000_000 + delta.microseconds * 10


def _name_hash(name: str) -> int:
    h = 0
    for unit in struct.unpack(f"<{len(name)}H", name.encode("utf-16-le")):
        h = (h * 65_599 + unit) & 0xFFFFFFFF
    return h & 0xFFFF


class _BinXml:
    """Serializes elements at known chunk offsets, so inline names point at themselves."""

    def __init__(self, base: int) -> None:
        self.base = base  # chunk offset of buf[0]
        self.buf = bytearray()

    def name(self, name: str) -> None:
        here = self.base + len(self.buf) + 4  # the name follows its own offset field
        self.buf += struct.pack("<I", here)
        encoded = name.encode("utf-16-le")
        self.buf += struct.pack("<IHH", 0, _name_hash(name), len(name)) + encoded + b"\x00\x00"

    def element(self, el: Element) -> None:
        self.buf.append(0x41 if el.attrs else 0x01)
        size_at = len(self.buf)
        self.buf += b"\x00\x00\x00\x00"  # data size, patched below
        self.name(el.name)
        if el.attrs:
            list_at = len(self.buf)
            self.buf += b"\x00\x00\x00\x00"
            for i, (attr, value) in enumerate(el.attrs):
                self.buf.append(0x46 if i < len(el.attrs) - 1 else 0x06)
                self.name(attr)
                self.buf.append(0x05)
                self.buf += value.encode()
            struct.pack_into("<I", self.buf, list_at, len(self.buf) - list_at - 4)
        if el.children:
            self.buf.append(0x02)
            for child in el.children:
                if isinstance(child, Value):
                    self.buf.append(0x05)
                    self.buf += child.encode()
                else:
                    self.element(child)
            self.buf.append(0x04)
        else:
            self.buf.append(0x03)
        struct.pack_into("<I", self.buf, size_at, len(self.buf) - size_at - 4)


def record_bytes(record_id: int, written: datetime, root: Element, offset: int) -> bytes:
    """One event record placed at `offset` within its chunk."""
    xml = _BinXml(offset + 24)
    xml.buf += b"\x0f\x01\x01\x00"  # fragment header 1.1
    xml.element(root)
    xml.buf.append(0x00)  # end of stream
    size = 24 + len(xml.buf) + 4
    return (
        struct.pack("<4sIQQ", b"**\x00\x00", size, record_id, filetime(written))
        + bytes(xml.buf)
        + struct.pack("<I", size)
    )


def _chunk(records: Sequence[tuple[int, datetime, Element]]) -> tuple[bytes, list[int]]:
    body = bytearray()
    offsets: list[int] = []
    placed: list[int] = []
    for record_id, written, root in records:
        offset = CHUNK_HEADER_SIZE + len(body)
        data = record_bytes(record_id, written, root, offset)
        if offset + len(data) > CHUNK_SIZE:
            break
        body += data
        offsets.append(offset)
        placed.append(record_id)
    free = CHUNK_HEADER_SIZE + len(body)
    header = bytearray(CHUNK_HEADER_SIZE)
    first, last = placed[0], placed[-1]
    struct.pack_into("<8sQQQQIIII", header, 0, b"ElfChnk\x00", first, last, first, last, 128,
                     offsets[-1], free, zlib.crc32(body))
    struct.pack_into("<I", header, 120, 0)
    crc = zlib.crc32(bytes(header[:120]) + bytes(header[128:512]))
    struct.pack_into("<I", header, 124, crc)
    chunk = bytes(header) + bytes(body)
    return chunk + b"\x00" * (CHUNK_SIZE - len(chunk)), placed


def write_evtx(records: Sequence[tuple[int, datetime, Element]]) -> bytes:
    """A complete .evtx file. Records are (record id, written time, root element)."""
    chunks: list[bytes] = []
    pending = list(records)
    while pending:
        chunk, placed = _chunk(pending)
        if not placed:
            raise ValueError("record larger than a chunk")
        chunks.append(chunk)
        pending = pending[len(placed):]
    header = bytearray(FILE_HEADER_SIZE)
    next_id = records[-1][0] + 1 if records else 1
    struct.pack_into("<8sQQQIHHHH", header, 0, b"ElfFile\x00", 0, len(chunks) - 1, next_id, 128,
                     2, 3, FILE_HEADER_SIZE, len(chunks))
    struct.pack_into("<I", header, 120, 0)  # flags: clean
    struct.pack_into("<I", header, 124, zlib.crc32(bytes(header[:120])))
    return bytes(header) + b"".join(chunks)


def event(
    *,
    provider: str,
    provider_guid: str | None,
    event_id: int,
    qualifiers: int | None,
    level: int,
    task: int,
    keywords: int,
    created: datetime,
    record_id: int,
    channel: str,
    computer: str,
    data: dict[str, str],
    process_id: int = 4,
    thread_id: int = 100,
) -> Element:
    """The <Event> element the way Windows writes Security and System events."""
    provider_attrs = [("Name", Value(STRING, provider))]
    if provider_guid:
        provider_attrs.append(("Guid", Value(STRING, provider_guid)))
    eid = Element("EventID", [("Qualifiers", Value(UINT16, qualifiers))] if qualifiers is not None
                  else [], [Value(UINT16, event_id)])
    system = Element("System", children=[
        Element("Provider", provider_attrs),
        eid,
        text("Version", 0, UINT8),
        text("Level", level, UINT8),
        text("Task", task, UINT16),
        text("Opcode", 0, UINT8),
        text("Keywords", keywords, HEXINT64),
        Element("TimeCreated", [("SystemTime", Value(FILETIME, filetime(created)))]),
        text("EventRecordID", record_id, UINT64),
        Element("Correlation"),
        Element("Execution", [("ProcessID", Value(UINT32, process_id)),
                              ("ThreadID", Value(UINT32, thread_id))]),
        text("Channel", channel),
        text("Computer", computer),
        Element("Security"),
    ])
    items = [Element("Data", [("Name", Value(STRING, k))], [Value(STRING, v)]) for k, v in data.items()]
    return Element("Event", [("xmlns", Value(STRING, EVENT_NS))],
                   [system, Element("EventData", children=items)])
