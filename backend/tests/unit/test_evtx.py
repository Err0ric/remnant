"""EVTX reader: id order, batching, bad input (SPEC 4.4, D4)."""

import io
from pathlib import Path

import pytest

from app.ingest.evtx import EvtxReader
from app.ingest.records import decode_frame

SAMPLE = Path(__file__).parent.parent / "fixtures" / "logs" / "windows_evtx" / "sample.evtx"


def test_batches_are_the_lowest_ids_after_the_checkpoint() -> None:
    data = SAMPLE.read_bytes()
    first = EvtxReader(max_records=7).read(io.BytesIO(data), 10)
    assert [i for i, _ in first.frames] == list(range(11, 18))
    assert first.highest_id == 60 and not first.complete and first.errors == 0
    last = EvtxReader(max_records=7).read(io.BytesIO(data), 55)
    assert [i for i, _ in last.frames] == list(range(56, 61)) and last.complete


def test_oversized_records_are_cut_and_flagged() -> None:
    batch = EvtxReader(max_len=256).read(io.BytesIO(SAMPLE.read_bytes()), 0)
    line = decode_frame(batch.frames[0][1])
    assert line.truncated and len(line.text.encode()) <= 256


def test_non_evtx_input_is_an_error_not_a_crash() -> None:
    for data in (b"", b"ElfFile\x00" + b"\x00" * 10, b"\xff" * 70_000):
        batch = EvtxReader().read(io.BytesIO(data), 0)
        assert batch.frames == [] and batch.errors >= 1


def test_join_skips_object_values() -> None:
    from datetime import UTC

    from app.templates.transforms import TransformRunner
    from app.templates.validator import Transform

    step = Transform.model_validate(
        {
            "field": "ch",
            "op": "join",
            "args": {"with": ["eid.#text", "eid"], "into": "key"},
        }
    )
    plain = {"ch": "System", "eid": 7036}
    qualified = {"ch": "System", "eid": {"#attributes": {"Qualifiers": 16384}, "#text": 7036}}
    for fields in (plain, qualified):
        TransformRunner([step], UTC).apply(fields)
        assert fields["key"] == "System:7036"


def test_only_chunks_after_the_checkpoint_are_parsed() -> None:
    data = SAMPLE.read_bytes()
    reader = EvtxReader(max_chunks=1)
    first = reader.read(io.BytesIO(data), 0)
    assert first.frames and not first.complete and first.highest_id == 60
    last_id = first.frames[-1][0]
    rest = reader.read(io.BytesIO(data), last_id)
    assert [i for i, _ in rest.frames] == list(range(last_id + 1, 61)) and rest.complete
    assert rest.after_digest == first.last_digest  # the checkpoint record is re-read


class _Panic(BaseException):
    """Stands in for pyo3's PanicException, which is not an Exception."""


def test_a_native_panic_ends_the_batch_but_not_the_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ingest import evtx as module

    class FakeParser:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        def records_json(self) -> object:
            yield {"event_record_id": 1, "data": "{}"}
            raise _Panic("boom")

    monkeypatch.setattr(module, "PyEvtxParser", FakeParser)
    batch = EvtxReader().read(io.BytesIO(SAMPLE.read_bytes()), 0)
    assert [i for i, _ in batch.frames] == [1] and batch.errors == 1


DAMAGED = SAMPLE.parent / "pathological.evtx"


def test_records_the_headers_list_but_cannot_be_read_are_counted() -> None:
    batch = EvtxReader().read(io.BytesIO(DAMAGED.read_bytes()), 0)
    assert len(batch.frames) == 59 and batch.errors == 0  # the library drops it silently
    assert batch.unreadable == 1  # ids 1 to 60 in the headers, 59 records read
    assert EvtxReader().read(io.BytesIO(DAMAGED.read_bytes()), 1).unreadable == 0  # past it
    clean = EvtxReader(max_records=7).read(io.BytesIO(SAMPLE.read_bytes()), 10)
    assert clean.unreadable == 0  # a batch smaller than what waits is not a loss
    garbage = EvtxReader().read(io.BytesIO(b"\xff" * 70_000), 0)
    assert garbage.unreadable >= 1


def test_the_batch_is_bounded_in_bytes_and_the_rest_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.ingest.evtx as evtx

    data = SAMPLE.read_bytes()
    whole = EvtxReader().read(io.BytesIO(data), 0)
    budget = sum(len(f.data) for _, f in whole.frames[:10])
    monkeypatch.setattr(evtx, "MAX_BATCH_BYTES", budget)
    seen: list[int] = []
    after = 0
    for _ in range(20):
        batch = EvtxReader().read(io.BytesIO(data), after)
        assert sum(len(f.data) for _, f in batch.frames) <= budget
        seen += [i for i, _ in batch.frames]
        if batch.complete:
            break
        after = batch.frames[-1][0]
    assert seen == [i for i, _ in whole.frames]  # every record once, in order


def test_a_forged_chunk_range_is_ignored() -> None:
    import struct

    data = bytearray(SAMPLE.read_bytes())
    head = 4096  # first chunk header
    struct.pack_into("<Q", data, head + 32, 2**62)  # last record id far past any chunk
    batch = EvtxReader().read(io.BytesIO(bytes(data)), 0)
    assert batch.highest_id == 60  # the forged range does not raise the highest id
    assert [i for i, _ in batch.frames] == list(range(38, 61))  # the honest chunk is read
    assert batch.unreadable >= 1  # and the ignored chunk is reported, not hidden


def _lagging(last: int = 30) -> bytes:
    """sample.evtx with the first chunk's header claiming fewer records than it holds, as a
    copy taken while Windows was still writing that chunk can."""
    import struct

    data = bytearray(SAMPLE.read_bytes())
    struct.pack_into("<Q", data, 4096 + 32, last)
    return bytes(data)


def test_a_gap_between_chunks_after_the_checkpoint_is_reported() -> None:
    batch = EvtxReader().read(io.BytesIO(_lagging()), 0)
    assert batch.gap == (31, 37)  # ids no chunk header lists, between two chunks
    assert EvtxReader().read(io.BytesIO(SAMPLE.read_bytes()), 0).gap is None
    assert EvtxReader().read(io.BytesIO(_lagging()), 40).gap is None  # behind the checkpoint
