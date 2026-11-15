"""Internal pipeline records shared by ingest stages."""

from dataclasses import dataclass

from app.ingest.envelope import Envelope


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
    # An envelope from outside the line (Loki stream labels), used when the line has no
    # syslog header of its own. Never changes `text`.
    hint: Envelope | None = None


def decode_frame(frame: Frame, encoding: str = "utf-8") -> DecodedLine:
    """Decode a frame, replacing invalid bytes and flagging that it happened."""
    try:
        text = frame.data.decode(encoding)
        invalid = False
    except UnicodeDecodeError:
        text = frame.data.decode(encoding, errors="replace")
        invalid = True
    return DecodedLine(text=text, bytes_invalid=invalid, truncated=frame.truncated)


NO_NEWLINE = "no_newline"


def mark_part_line(row: dict[str, object]) -> None:
    """A last line stored without its newline (ADR-0051 row 5): `partial` whatever the
    parser made of it (a cut JSON object does not parse), except that a missing template
    stays said, with `no_newline` first among its reasons."""
    if row["parse_status"] != "template_missing":
        row["parse_status"] = "partial"
    errors = [e for e in str(row.get("parse_errors") or "").split(",") if e and e != NO_NEWLINE]
    row["parse_errors"] = ",".join([NO_NEWLINE, *errors])
