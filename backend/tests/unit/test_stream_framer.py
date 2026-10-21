"""Streaming framer for the syslog listener (ADR-0021 row 3) and sender rules (row 4)."""

import pytest

from app.ingest.framer import StreamFramer
from app.ingest.listener_settings import SyslogSettings
from app.ingest.records import Frame


def feed_all(chunks: list[bytes], max_len: int = 64) -> list[Frame]:
    f = StreamFramer(max_len)
    out = [frame for c in chunks for frame in f.feed(c)]
    return out + f.close()


def test_octet_counted_across_chunks_keeps_newlines_inside() -> None:
    msg = b"<13>1 - h a - - - line one\nline two"
    data = f"{len(msg)} ".encode() + msg + b"5 <14>x"
    for cut in range(1, len(data)):
        assert feed_all([data[:cut], data[cut:]]) == [Frame(msg), Frame(b"<14>x")]


def test_newline_framing_and_crlf() -> None:
    assert feed_all([b"<13>a\r\n<13>b\n\n<13>", b"c"]) == [
        Frame(b"<13>a"),
        Frame(b"<13>b"),
        Frame(b"<13>c"),
    ]


def test_newlines_between_octet_frames_are_tolerated() -> None:
    assert feed_all([b"5 <14>a\n5 <14>b\r\n"]) == [Frame(b"<14>a"), Frame(b"<14>b")]


def test_overlong_messages_are_cut_flagged_and_the_rest_skipped() -> None:
    big = b"<13>" + b"x" * 100
    octet = feed_all([f"{len(big)} ".encode() + big + b"5 <14>y"], max_len=10)
    assert octet == [Frame(big[:10], truncated=True), Frame(b"<14>y")]
    lines = feed_all([big[:50], big[50:] + b"\n<13>z\n"], max_len=10)
    assert lines == [Frame(big[:10], truncated=True), Frame(b"<13>z")]


def test_short_stream_and_unterminated_tail() -> None:
    assert feed_all([b"<13>hi"]) == [Frame(b"<13>hi")]
    assert feed_all([b"20 <13>short"]) == [Frame(b"<13>short", truncated=True)]
    assert feed_all([b""]) == []


def test_buffer_stays_bounded_on_endless_garbage() -> None:
    f = StreamFramer(32)
    for _ in range(1000):
        f.feed(b"y" * 1000)
    assert len(f._buf) <= 32 + 1000


@pytest.mark.parametrize(
    ("allowed", "address", "ok"),
    [
        ([], "192.168.1.10", True),
        ([], "10.1.2.3", True),
        ([], "::1", True),
        ([], "::ffff:192.168.1.10", True),
        ([], "203.0.113.9", False),
        ([], "2001:db8::1", False),
        (["203.0.113.0/24"], "203.0.113.9", True),
        (["203.0.113.0/24"], "192.168.1.10", False),
        (["0.0.0.0/0"], "198.51.100.7", True),
        (["0.0.0.0/0"], "2001:db8::1", False),
        ([], "not-an-ip", False),
    ],
)
def test_sender_rules(allowed: list[str], address: str, ok: bool) -> None:
    assert SyslogSettings(allowed_senders=allowed).allows(address) is ok


def test_sender_list_is_validated() -> None:
    with pytest.raises(ValueError, match="Not an address"):
        SyslogSettings(allowed_senders=["192.168.1.0/33"])
    assert SyslogSettings(allowed_senders=[" 10.0.0.5/8 "]).allowed_senders == ["10.0.0.0/8"]
