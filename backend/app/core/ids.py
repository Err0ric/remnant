"""Identifier helpers.

event_id is UUIDv7 (RFC 9562), time-sortable. Python 3.12 has no uuid.uuid7,
so it is implemented here. Other ids are UUIDv4.
"""

import os
import threading
import time
import uuid

# Source id under which pasted parser-draft samples are declared to the LLM gate. Ids with
# this prefix can never be configured, and the gate treats them as local_only regardless.
RESERVED_SOURCE_PREFIX = "draft_sample"
LOCAL_ONLY_SAMPLE_SOURCE = "draft_sample_local_only"

_lock = threading.Lock()
_last_ms = 0
_counter = 0


def uuid7() -> uuid.UUID:
    """Return a UUIDv7 that is monotonic within this process.

    Layout: 48-bit unix ms, 4-bit version, 12-bit counter, 2-bit variant, 62 random bits.
    The 12-bit counter keeps ordering stable for ids minted in the same millisecond.
    """
    global _last_ms, _counter
    with _lock:
        ms = time.time_ns() // 1_000_000
        if ms <= _last_ms:
            ms = _last_ms
            _counter += 1
            if _counter > 0xFFF:
                ms += 1
                _counter = 0
        else:
            _counter = int.from_bytes(os.urandom(2), "big") & 0x3FF  # leave headroom
        _last_ms = ms
        counter = _counter

    rand = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    value = (ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76
    value |= counter << 64
    value |= 0b10 << 62
    value |= rand
    return uuid.UUID(int=value)


def new_event_id() -> str:
    return str(uuid7())


def new_id() -> str:
    return str(uuid.uuid4())


# Reserved parser id: a source with this template_id picks a template per line (ADR-0012).
AUTO_PARSER = "auto"
