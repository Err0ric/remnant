import uuid

from app.core.ids import new_event_id, new_id, uuid7


def test_uuid7_version_and_variant() -> None:
    value = uuid7()
    assert value.version == 7
    assert value.variant == uuid.RFC_4122


def test_uuid7_monotonic_within_process() -> None:
    ids = [uuid7() for _ in range(5000)]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


def test_string_helpers() -> None:
    assert uuid.UUID(new_event_id()).version == 7
    assert uuid.UUID(new_id()).version == 4
