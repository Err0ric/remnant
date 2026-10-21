"""Internal pipeline records shared by ingest stages."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Frame:
    """One framed message as bytes, before decoding."""

    data: bytes
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class DecodedLine:
    """A frame decoded to text. `text` becomes the `raw` column unchanged."""

    text: str
    bytes_invalid: bool
    truncated: bool


def decode_frame(frame: Frame, encoding: str = "utf-8") -> DecodedLine:
    """Decode a frame, replacing invalid bytes and flagging that it happened."""
    try:
        text = frame.data.decode(encoding)
        invalid = False
    except UnicodeDecodeError:
        text = frame.data.decode(encoding, errors="replace")
        invalid = True
    return DecodedLine(text=text, bytes_invalid=invalid, truncated=frame.truncated)
