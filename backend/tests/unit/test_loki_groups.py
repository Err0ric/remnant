"""Loki Test connection groups streams that differ only by a per-id label (finding 12)."""

from app.ingest.connectors.loki import group_streams


def test_twenty_streams_differing_by_proc_id_are_one_group() -> None:
    sets = [{"hostname": "web01", "app_name": "sshd", "proc_id": str(1000 + i)} for i in range(20)]
    groups, ignored = group_streams(sets)
    assert groups == [{"labels": {"hostname": "web01", "app_name": "sshd"}, "streams": 20}]
    assert ignored == ["proc_id"]


def test_groups_sort_largest_first_and_keep_other_labels() -> None:
    sets = [
        {"host": "a", "pid": "1"},
        {"host": "b", "pid": "2"},
        {"host": "b", "pid": "3"},
        {"host": "c", "instance": "web-1"},  # a name, not an id: kept
        {"host": "c", "instance": "3f9a2c1d7e"},  # an id: ignored
    ]
    groups, ignored = group_streams(sets)
    assert groups[0] == {"labels": {"host": "b"}, "streams": 2}
    assert {"labels": {"host": "c", "instance": "web-1"}, "streams": 1} in groups
    assert {"labels": {"host": "c"}, "streams": 1} in groups
    assert ignored == ["instance", "pid"]
