from collections.abc import Iterable

import pytest

from app.ingest.framer import Framer
from app.ingest.records import Frame, decode_frame


def frames(chunks: Iterable[bytes], **kwargs: object) -> list[Frame]:
    return list(Framer(**kwargs).frames(chunks))  # type: ignore[arg-type]  # test helper passthrough


def octet(msg: bytes) -> bytes:
    return str(len(msg)).encode() + b" " + msg


# --- newline framing ------------------------------------------------------------


def test_newline_split_crlf_and_blank_lines() -> None:
    out = frames([b"one\r\n\ntwo\nthree\n"])
    assert [f.data for f in out] == [b"one", b"two", b"three"]
    assert not any(f.truncated for f in out)


def test_newline_split_across_chunk_boundaries() -> None:
    out = frames([b"alp", b"ha\nbe", b"ta\ngam", b"ma\n"])
    assert [f.data for f in out] == [b"alpha", b"beta", b"gamma"]


def test_trailing_partial_line_flushed_by_default() -> None:
    assert [f.data for f in frames([b"a\nb"])] == [b"a", b"b"]


def test_trailing_partial_line_held_when_tailing() -> None:
    assert [f.data for f in frames([b"a\nb"], flush_partial=False)] == [b"a"]


def test_overlong_line_truncated_and_rest_discarded() -> None:
    out = frames([b"0123456789abcdef", b"XYZ\nnext\n"], max_len=8)
    assert out[0] == Frame(b"01234567", truncated=True)
    assert out[1] == Frame(b"next", truncated=False)


# --- octet-counted framing (RFC 6587) -------------------------------------------


def test_octet_counted_auto_detected() -> None:
    m1 = b"<13>1 2026-10-09T20:41:12Z h app - - - hello\nwith newline"
    m2 = b"<13>1 2026-10-09T20:41:13Z h app - - - second"
    out = frames([octet(m1) + octet(m2)])
    assert [f.data for f in out] == [m1, m2]


def test_octet_counted_across_chunk_boundaries() -> None:
    m1 = b"<13>Oct  9 20:41:12 h app: one"
    m2 = b"<13>Oct  9 20:41:12 h app: two"
    blob = octet(m1) + octet(m2)
    chunks = [blob[i : i + 5] for i in range(0, len(blob), 5)]
    assert [f.data for f in frames(chunks)] == [m1, m2]


def test_octet_counted_overlong_message_truncated() -> None:
    m1 = b"<13>Oct  9 20:41:12 h app: " + b"x" * 50
    m2 = b"<13>Oct  9 20:41:12 h app: ok"
    out = frames([octet(m1) + octet(m2)], max_len=40)
    assert out[0].truncated and len(out[0].data) == 40
    assert out[1] == Frame(m2, truncated=False)


def test_octet_mode_falls_back_to_newline_on_garbage() -> None:
    m1 = b"<13>Oct  9 20:41:12 h app: one"
    out = frames([octet(m1) + b"not a length\nplain line\n"])
    assert [f.data for f in out] == [m1, b"not a length", b"plain line"]


def test_plain_file_not_mistaken_for_octet() -> None:
    out = frames([b"12 apples were sold\n13 more\n"])
    assert [f.data for f in out] == [b"12 apples were sold", b"13 more"]


# --- decoding --------------------------------------------------------------------


def test_decode_valid_utf8() -> None:
    line = decode_frame(Frame("café ✓".encode()))
    assert line.text == "café ✓"
    assert line.bytes_invalid is False


def test_decode_invalid_utf8_replaced_and_flagged() -> None:
    line = decode_frame(Frame(b"user=\xff\xfe ok"))
    assert line.text == "user=�� ok"
    assert line.bytes_invalid is True


def test_decode_latin1_declared() -> None:
    line = decode_frame(Frame(b"caf\xe9"), encoding="latin-1")
    assert line.text == "café"
    assert line.bytes_invalid is False


def test_decode_carries_truncation() -> None:
    assert decode_frame(Frame(b"abc", truncated=True)).truncated is True


@pytest.mark.parametrize("max_len", [0, -1])
def test_max_len_must_be_positive(max_len: int) -> None:
    with pytest.raises(ValueError):
        Framer(max_len=max_len)


def test_one_big_chunk_and_many_small_chunks_frame_the_same() -> None:
    """The framer keeps an offset into its buffer; chunk boundaries must not matter."""
    import random

    from app.ingest.framer import Framer

    rng = random.Random(3)
    lines = [
        f"<13>Oct  9 20:00:{i % 60:02d} h app: line {i} " + "x" * rng.randint(0, 300)
        for i in range(5000)
    ]
    lines[100] = "y" * 20_000  # overlong, truncated
    data = ("\n".join(lines) + "\nlast without newline").encode()
    whole = list(Framer(max_len=8192, mode="newline").frames([data]))
    cuts = sorted(rng.sample(range(1, len(data)), 400))
    pieces = [data[a:b] for a, b in zip([0, *cuts], [*cuts, len(data)], strict=True)]
    split = list(Framer(max_len=8192, mode="newline").frames(pieces))
    assert whole == split
    assert len(whole) == 5001 and whole[100].truncated and whole[-1].data == b"last without newline"

    octet = b"".join(f"{len(m)} {m}".encode() for m in ["<13>a", "<13>" + "z" * 9000, "<13>c"])
    big = list(Framer(max_len=8192).frames([octet]))
    small = list(Framer(max_len=8192).frames([octet[i : i + 7] for i in range(0, len(octet), 7)]))
    assert big == small and [f.truncated for f in big] == [False, True, False]
