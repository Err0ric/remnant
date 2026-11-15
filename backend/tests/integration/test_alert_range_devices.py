"""An alert item's range and devices as it keeps being raised (findings 2026-11, fix E;
owner 2026-11-14). An AI Watch service or MCP server item is kept current by the hourly
review (owner, 2026-10-23): its people, devices, counts, and wording are the review's, and
so is its range now, start included, so the people lookup and "Show events in Logs" read
the window the item counts. Devices keep host names first (they can name a person through
the hooks plugin), newest first, then addresses, and the item keeps how many there were."""

from datetime import timedelta
from typing import Any

import pytest

from app.ai.watch import _Review
from app.alerts.items import MAX_NAMES
from app.ingest.writer import LakeWriter
from tests.integration.test_ai_usage import lab as ai_lab  # noqa: F401  # the fixture
from tests.integration.test_alert_device_person import _hook
from tests.integration.test_schedules import NOW

H = timedelta(hours=1)
D = timedelta(days=1)


def iso(t: Any) -> str | None:
    return None if t is None else (NOW + (t or timedelta(0))).isoformat()


# (first raise, second raise, refresh and window on the second, closed in between) -> range
RANGE_CASES = [
    pytest.param((-H, 0), (-7 * D, H), (True, True), False, (-7 * D, H), id="the review's window"),
    pytest.param((-7 * D, 0), (-6 * D, H), (True, True), False, (-6 * D, H), id="it moves on"),
    pytest.param((-H, 0), (None, H), (True, True), False, (-H, H), id="no start given keeps it"),
    pytest.param((-H, 0), (-7 * D, H), (True, False), False, (-H, H), id="a slice keeps its start"),
    pytest.param((-H, 0), (-7 * D, H), (False, True), False, (-H, 0), id="no refresh: as it was"),
    pytest.param((-H, 0), (-7 * D, H), (True, True), True, (-H, 0), id="a closed item stays"),
]


@pytest.mark.parametrize(("first", "second", "how", "closed", "want"), RANGE_CASES)
def test_the_range_of_a_kept_current_item(
    ai_lab: dict[str, Any],  # noqa: F811
    first: tuple[Any, Any],
    second: tuple[Any, Any],
    how: tuple[bool, bool],
    closed: bool,
    want: tuple[Any, Any],
) -> None:
    items = ai_lab["app"].state.alert_items

    def raise_(span: tuple[Any, Any], refresh: bool, window: bool) -> Any:
        return items.raise_item(
            "ai_watch", "service:gemini", "AI service not reviewed: Gemini",
            ref_id="service:gemini", sources=["dns"], range_start=iso(span[0]),
            range_end=iso(span[1]), refresh=refresh, window=window,
        )  # fmt: skip

    item = raise_(first, False, False)
    if closed:
        with ai_lab["app"].state.meta.connect() as con:
            con.execute(
                "UPDATE alert_items SET state = 'closed' WHERE item_id = ?", (item.item_id,)
            )
    got = raise_(second, *how)
    assert (got.range_start, got.range_end) == (iso(want[0]), iso(want[1]))


def test_a_grouped_item_keeps_its_first_start(ai_lab: dict[str, Any]) -> None:  # noqa: F811
    """Repeats grouped per rule and day (ADR-0043) cover their first event to their last:
    only their end moves, as before."""
    items = ai_lab["app"].state.alert_items
    for n, span in enumerate(((-2 * H, -H), (-H, 0))):
        got = items.raise_item(
            "rule", f"refusals:10.0.0.{n}", "Refused credentials", ref_id=f"r-{n}",
            sources=["dns"], range_start=iso(span[0]), range_end=iso(span[1]),
            group=("refusals:10.0.0.9", "refusals"), change=f"try {n}",
        )  # fmt: skip
    assert (got.range_start, got.range_end) == (iso(-2 * H), iso(0))


def test_refused_credentials_keep_the_burst_s_first_start(ai_lab: dict[str, Any]) -> None:  # noqa: F811
    """As the detector raises: every minute, the same item per address and hour, a sliding
    10-minute window. Guessing from 10:00 to 10:30 is one item from 10:00 to 10:30."""
    from app.search.refusals import WINDOW, RefusalWatch

    app = ai_lab["app"]
    watch = RefusalWatch(app.state.engine, app.state.meta, app.state.alert_items)
    ten = NOW.replace(hour=10, minute=0)
    for m in range(1, 31):
        now = ten + timedelta(minutes=m)
        first = max(ten, now - WINDOW)
        watch._raise("198.51.100.7", 25, ["password"], first.isoformat(), now.isoformat(), now)
    with app.state.meta.connect() as con:
        rows = con.execute(
            "SELECT range_start, range_end FROM alert_items WHERE subject LIKE 'refusals:%'"
        ).fetchall()
    assert [tuple(r) for r in rows] == [
        (ten.isoformat(), (ten + 30 * timedelta(minutes=1)).isoformat())
    ]


def test_sensitive_data_per_day_keeps_its_first_start(ai_lab: dict[str, Any]) -> None:  # noqa: F811
    watch = _watch(ai_lab)
    for back in (H, timedelta(0)):  # the 30-second check, then the hourly review
        since = NOW - (7 * D if back == timedelta(0) else back)
        watch._raise_sensitive("ws-0042", {"secret": 1}, ["claude"], since, NOW,
                               day=NOW.date().isoformat(), refresh=back == timedelta(0),
                               machine=True)  # fmt: skip
    with ai_lab["app"].state.meta.connect() as con:
        (row,) = con.execute(
            "SELECT range_start, range_end FROM alert_items WHERE subject LIKE 'sensitive:%'"
        ).fetchall()
    assert tuple(row) == ((NOW - H).isoformat(), NOW.isoformat())


def test_an_agent_s_item_keeps_its_first_raise(ai_lab: dict[str, Any]) -> None:  # noqa: F811
    watch = _watch(ai_lab)
    first = watch._raise_agent("cc|ws-0042", "agent", "Claude Code on ws-0042", "In use", NOW - H)
    again = watch._raise_agent(
        "cc|ws-0042", "agent", "Claude Code on ws-0042", "In use", NOW, refresh=True
    )
    assert first is not None and again is not None and again.item_id == first.item_id
    assert (again.range_start, again.range_end) == (None, NOW.isoformat())


def test_the_30_second_check_lists_devices_newest_first(ai_lab: dict[str, Any]) -> None:  # noqa: F811
    """Its rows come oldest first; an item it raises keeps the newest 20 host names, as
    the hourly review does."""
    from tests.integration.test_schedules import _lake_rows

    app = ai_lab["app"]
    watch = _watch(ai_lab)
    now = NOW + 2 * H
    watch._clock = lambda: now
    watch._reviewed_at = now  # the hourly review has just run: only the new rows are read
    rows = []
    for n in range(25):  # ws-0100 seen first, ws-0124 last; ws-0100 again at the end
        (r,) = _lake_rows("dns", "dns_bind", now - timedelta(minutes=50 - n), 1)
        rows.append({**r, "dst_endpoint_hostname": "gemini.google.com",
                     "src_endpoint_hostname": f"ws-{100 + n:04d}"})  # fmt: skip
    (r,) = _lake_rows("dns", "dns_bind", now - timedelta(minutes=5), 1)
    rows.append({**r, "dst_endpoint_hostname": "gemini.google.com",
                 "src_endpoint_hostname": "ws-0100"})  # fmt: skip
    LakeWriter(app.state.engine._lake).write(rows)
    watch.tick()
    (item,) = [i for i in ai_lab["admin"].get("/api/alerts").json()["items"]
               if i["subject"] == "service:gemini"]  # fmt: skip
    hosts = [d for d in item["devices"] if d.startswith("ws-01")]
    assert hosts[:3] == ["ws-0100", "ws-0124", "ws-0123"]
    assert len(hosts) == MAX_NAMES and "ws-0101" not in hosts  # the oldest are the ones cut


def _watch(lab: dict[str, Any]) -> Any:
    return lab["app"].state.ai_watch


def _review(hosts: list[str], addresses: dict[str, list[str]], ip_only: list[str]) -> _Review:
    r = _Review("Gemini", "not_approved")
    for d in [*hosts, *ip_only]:
        r.add_device(d)
    for host, ips in addresses.items():
        for ip in ips:
            r.saw(host, ip)
    r.sources = {"dns"}
    return r


def test_the_cap_keeps_host_names_first_and_says_how_many(ai_lab: dict[str, Any]) -> None:  # noqa: F811
    # 25 hosts, newest first as the review lists them, each seen at two addresses, and 10
    # addresses with no host name: 25 + 50 + 10 devices and addresses.
    hosts = [f"ws-{i:04d}.corp.internal" for i in range(25, 0, -1)]
    addresses = {h: [f"10.1.{i}.1", f"10.2.{i}.1"] for i, h in enumerate(hosts)}
    ip_only = [f"192.168.0.{i}" for i in range(10)]
    _watch(ai_lab)._raise_use(
        "service", "gemini", _review(hosts, addresses, ip_only), NOW - 7 * D, NOW, refresh=True
    )
    (item,) = [i for i in ai_lab["admin"].get("/api/alerts").json()["items"]
               if i["subject"] == "service:gemini"]  # fmt: skip
    assert item["devices"] == hosts[:MAX_NAMES]  # the newest 20 host names, nothing cut first
    assert item["devices_total"] == 25 + 50 + 10
    assert (item["range_start"], item["range_end"]) == ((NOW - 7 * D).isoformat(), NOW.isoformat())


def test_few_devices_keep_hosts_then_their_addresses_then_the_rest(
    ai_lab: dict[str, Any],  # noqa: F811
) -> None:
    hosts = ["ws-0002", "ws-0001"]
    _watch(ai_lab)._raise_use(
        "service", "gemini",
        _review(hosts, {"ws-0002": ["10.0.0.2"], "ws-0001": ["10.0.0.1"]}, ["10.9.9.9"]),
        NOW - 7 * D, NOW, refresh=True,
    )  # fmt: skip
    (item,) = [i for i in ai_lab["admin"].get("/api/alerts").json()["items"]
               if i["subject"] == "service:gemini"]  # fmt: skip
    assert item["devices"] == ["ws-0002", "ws-0001", "10.0.0.2", "10.0.0.1", "10.9.9.9"]
    assert item["devices_total"] == 5


def test_the_people_lookup_reads_the_refreshed_window_and_stays_masked(
    ai_lab: dict[str, Any],  # noqa: F811
) -> None:
    """A person seen on a device days ago, inside the review's 7 days but before the item
    was first raised, is named for a viewer who may see people, and for no one else."""
    host = "ws-0101.corp.internal"
    LakeWriter(ai_lab["app"].state.engine._lake).write(
        [_hook("erin@example.com", host, 60 * 24 * 3)]  # three days ago
    )
    watch = _watch(ai_lab)
    watch._raise_use("service", "gemini", _review([host], {}, []), NOW - H, NOW)  # first sight
    watch._raise_use("service", "gemini", _review([host], {}, []), NOW - 7 * D, NOW, refresh=True)
    (listed,) = [i for i in ai_lab["admin"].get("/api/alerts").json()["items"]
                 if i["subject"] == "service:gemini"]  # fmt: skip
    assert (listed["range_start"], listed["devices"]) == ((NOW - 7 * D).isoformat(), [host])
    (dp,) = listed["device_people"]
    assert dp["people"] == ["erin@example.com"] and dp["level"] == "attributed"
    # ana reads the AI sources but has no View people in AI usage (D242).
    body = {"source_ids": ["dns", "claude"]}
    admin, h = ai_lab["admin"], ai_lab["h"]
    assert admin.put(f"/api/groups/{ai_lab['gid']}/sources", json=body, headers=h).is_success
    (masked,) = ai_lab["ana"].get(f"/api/alerts/{listed['item_id']}").json()["device_people"]
    assert masked == {**dp, "people": []}
    # The stored item holds no name (#517): its text is the review's, with devices only.
    with ai_lab["app"].state.meta.connect() as con:
        row = con.execute(
            "SELECT title, detail, why, people FROM alert_items WHERE item_id = ?",
            (listed["item_id"],),
        ).fetchone()
    assert "erin" not in " ".join(str(v) for v in row)


def test_the_review_lists_devices_newest_first(ai_lab: dict[str, Any]) -> None:  # noqa: F811
    """The hourly review reads the same rows as before; only the order of its devices is
    new: most recently seen first, so a cut list keeps the devices in use now."""
    from app.engine.duckdb import QueryScope
    from tests.integration.test_schedules import _lake_rows

    rows = []
    for n, hours in enumerate((30, 2, 50, 10)):
        (r,) = _lake_rows("dns", "dns_bind", NOW - timedelta(hours=hours), 1)
        rows.append({**r, "dst_endpoint_hostname": "gemini.google.com",
                     "src_endpoint_hostname": f"ws-07{n}0"})  # fmt: skip
    LakeWriter(ai_lab["app"].state.engine._lake).write(rows)
    usage = ai_lab["app"].state.ai_usage
    (gemini,) = [r for r in usage.review(QueryScope(None, NOW - 7 * D, NOW)) if r[0] == "gemini"]
    assert [d for d in gemini[3] if d.startswith("ws-07")] == [
        "ws-0710",
        "ws-0730",
        "ws-0700",
        "ws-0720",
    ]


def test_the_mcp_review_lists_devices_newest_first(ai_lab: dict[str, Any]) -> None:  # noqa: F811
    """The MCP server review orders its devices as the service review does."""
    from app.engine.duckdb import QueryScope
    from tests.integration.test_schedules import _lake_rows

    rows = []
    for n, hours in enumerate((30, 2, 50, 10)):
        (r,) = _lake_rows("claude", "mcp_inventory", NOW - timedelta(hours=hours), 1)
        rows.append({**r, "message": "tickets-mcp", "device_hostname": f"ws-08{n}0",
                     "actor_user_name": None})  # fmt: skip
    LakeWriter(ai_lab["app"].state.engine._lake).write(rows)
    usage = ai_lab["app"].state.ai_usage
    (found,) = [r for r in usage.review_mcp(QueryScope(None, NOW - 7 * D, NOW))
                if r[0] == "tickets-mcp"]  # fmt: skip
    assert found[3] == ["ws-0810", "ws-0830", "ws-0800", "ws-0820"]


def test_the_alert_text_names_host_names_before_addresses(ai_lab: dict[str, Any]) -> None:  # noqa: F811
    """Five newer address-only devices do not push the one host name out of the text."""
    r = _Review("Gemini", "not_approved")
    for d in ["10.0.9.1", "10.0.9.2", "10.0.9.3", "10.0.9.4", "10.0.9.5", "ws-0900.corp.internal"]:
        r.add_device(d)
    r.sources = {"dns"}
    _watch(ai_lab)._raise_use("service", "gemini", r, NOW - H, NOW)
    (listed,) = [i for i in ai_lab["admin"].get("/api/alerts").json()["items"]
                 if i["subject"] == "service:gemini"]  # fmt: skip
    detail = ai_lab["admin"].get(f"/api/alerts/{listed['item_id']}").json()["detail"]
    assert "ws-0900.corp.internal" in detail and detail.index("ws-0900") < detail.index("10.0.9.1")
