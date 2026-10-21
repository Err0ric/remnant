"""Loki connector (ADR-0011): query rules, paging without gaps or doubles, auth, errors."""

import base64
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.core.errors import ParamInvalidError
from app.ingest.connectors import loki
from app.ingest.connectors.loki import (
    LokiClient,
    LokiSettings,
    Position,
    check_query,
    poll,
    to_ns,
)
from tests.fake_loki import FakeLoki

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
URL = "http://127.0.0.1:3100"


def settings(**kw: object) -> LokiSettings:
    return LokiSettings(**{"url": URL, "query": '{job="syslog"}', **kw})  # type: ignore[arg-type]  # test data


def client(fake: FakeLoki, s: LokiSettings | None = None, secret: str | None = None) -> LokiClient:
    return LokiClient(s or settings(), secret, transport=fake.transport())


@pytest.mark.parametrize(
    "query",
    [
        '{job="syslog"}',
        '{job="syslog", host=~"fw.*"}',
        '{app!="x"} |= "sshd" != "CRON"',
        '{a="b"} |~ `fail(ed)?`',
        '{a="say \\"hi\\""}',
    ],
)
def test_selectors_and_line_filters_are_accepted(query: str) -> None:
    assert check_query(query) == query


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ("job=syslog", "label selector"),
        ('{job="syslog"} | json', "only line filters"),
        ('{job="syslog"} | line_format "{{.x}}"', "only line filters"),
        ('sum(rate({job="syslog"}[5m]))', "label selector"),
        ('{job="a"}' + ' |= "x"' * 6, "at most 5"),
    ],
)
def test_other_logql_is_refused(query: str, message: str) -> None:
    with pytest.raises(ParamInvalidError, match=message):
        check_query(query)


def test_backfill_then_nothing_twice() -> None:
    fake = FakeLoki()
    for i in range(10):
        fake.add(to_ns(NOW - timedelta(hours=2, minutes=i)), f"line {i}")
    fake.add(to_ns(NOW - timedelta(hours=30)), "too old for the default back-fill")
    first = poll(client(fake), settings(), None, NOW)
    assert sorted(x.line for x in first.lines) == [f"line {i}" for i in range(10)]
    again = poll(client(fake), settings(), first.position, NOW + timedelta(seconds=30))
    assert again.lines == []
    assert first.behind <= loki.LAG


def test_pages_with_shared_timestamps_read_every_line_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loki, "LIMIT", 7)
    fake = FakeLoki()
    base = to_ns(NOW - timedelta(hours=1))
    expected = []
    for i in range(40):
        ns = base + (i // 3) * 1000  # three lines share each timestamp
        fake.add(ns, f"l{i}", host=f"h{i % 2}")
        expected.append(f"l{i}")
    pos: Position | None = None
    got: list[str] = []
    for step in range(10):  # MAX_PAGES per poll is plenty here; restart-like polls
        res = poll(client(fake), settings(), pos, NOW + timedelta(seconds=step))
        got += [x.line for x in res.lines]
        pos = Position.load(res.position.dump())  # survives a restart
    assert sorted(got) == sorted(expected) and len(got) == len(set(got))
    assert len(fake.calls) > 40 // 7  # it really paged


def test_late_lines_inside_the_lag_are_still_read() -> None:
    fake = FakeLoki()
    first = poll(client(fake), settings(backfill_hours=1), None, NOW)
    fake.add(to_ns(NOW - timedelta(seconds=10)), "arrived late")
    later = poll(client(fake), settings(), first.position, NOW + timedelta(seconds=60))
    assert [x.line for x in later.lines] == ["arrived late"]


def test_a_full_page_at_one_instant_does_not_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loki, "LIMIT", 3)
    fake = FakeLoki()
    ns = to_ns(NOW - timedelta(minutes=5))
    for i in range(5):
        fake.add(ns, f"same {i}")
    res = poll(client(fake), settings(backfill_hours=1), Position(ns), NOW)
    assert len(res.lines) == 3 and res.position.ns >= ns + 1


def test_auth_headers_and_tenant() -> None:
    fake = FakeLoki()
    poll(
        client(fake, settings(auth="basic", username="svc", tenant="team-a"), "pw"),
        settings(),
        None,
        NOW,
    )
    req = fake.calls[-1]
    assert req.headers["authorization"] == "Basic " + base64.b64encode(b"svc:pw").decode()
    assert req.headers["x-scope-orgid"] == "team-a"
    poll(client(fake, settings(auth="bearer"), "tok"), settings(), None, NOW)
    assert fake.calls[-1].headers["authorization"] == "Bearer tok"
    poll(client(fake), settings(), None, NOW)
    assert "authorization" not in fake.calls[-1].headers


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (401, "refused the credentials"),
        (400, "rejected the query"),
        (404, "No Loki API"),
        (500, "HTTP 500"),
    ],
)
def test_errors_say_what_went_wrong_without_secrets(status: int, message: str) -> None:
    fake = FakeLoki(status=status)
    with pytest.raises(ParamInvalidError, match=message) as exc:
        poll(client(fake, settings(auth="bearer"), "s3cret-token"), settings(), None, NOW)
    assert "s3cret" not in str(exc.value)


def test_unsafe_addresses_and_redirects_are_refused() -> None:
    fake = FakeLoki()
    with pytest.raises(ParamInvalidError, match="not allowed"):
        poll(client(fake, settings(url="http://169.254.169.254")), settings(), None, NOW)

    def redirect(req: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://203.0.113.9/"})

    c = LokiClient(settings(), None, transport=httpx.MockTransport(redirect))
    with pytest.raises(ParamInvalidError, match="HTTP 302"):
        c.query_range(1, 2)


def test_settings_reject_a_url_with_a_query() -> None:
    with pytest.raises(ValueError, match="root URL"):
        settings(url=URL + "/loki/api/v1/query_range?x=1")
