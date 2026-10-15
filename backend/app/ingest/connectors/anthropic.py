"""Anthropic usage and audit connector (ADR-0015 row 10).

Feeds (endpoint; key; when data is final):

- usage: /v1/organizations/usage_report/messages, 1h buckets by model, workspace,
  and key; Admin key; finished hours.
- cost: /v1/organizations/cost_report, 1d buckets by workspace and description;
  Admin key; finished days.
- claude_code: /v1/organizations/usage_report/claude_code, per user per day;
  Admin or Analytics key; days that ended over 2 h ago.
- analytics_users: /v1/organizations/analytics/users, claude.ai per user (Enterprise);
  Analytics key; the day after, from 14:00 UTC.
- compliance_activities: /v1/compliance/activities, the audit feed; Compliance or
  Admin key; every 5 minutes.

Each record is one JSON line `{"feed": "anthropic.<feed>", ...}` holding the provider's
object (for reports, the bucket's times and one result row). Chat content, files, and
projects (the Compliance content endpoints) are never read.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ingest.connectors.base import ConnectorError, Https, Pull, Record, RetryLaterError

Feed = Literal["usage", "cost", "claude_code", "analytics_users", "compliance_activities"]
HOST = "api.anthropic.com"
VERSION = "2023-06-01"
POLL_EVERY = timedelta(minutes=5)
MAX_PAGES = 20


def _default_feeds() -> list[Feed]:
    return ["usage", "cost", "claude_code"]


class AnthropicSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key_type: Literal["admin", "analytics", "compliance"] = "admin"
    feeds: list[Feed] = Field(default_factory=_default_feeds, min_length=1, max_length=5)
    backfill_days: int = Field(default=7, ge=0, le=31)

    @field_validator("feeds")
    @classmethod
    def _unique(cls, value: list[Feed]) -> list[Feed]:
        return list(dict.fromkeys(value))


class AnthropicClient:
    def __init__(self, key: str, transport: httpx.BaseTransport | None = None) -> None:
        if not key:
            raise ConnectorError("No API key is stored for this source")
        self._key = key
        self._http = Https(frozenset({HOST}), transport)

    def get(self, path: str, params: list[tuple[str, str]]) -> Any:
        url = f"https://{HOST}{path}?{urlencode(params)}"
        reply = self._http.request(
            "GET", url, headers={"x-api-key": self._key, "anthropic-version": VERSION}
        )
        if reply.status in (401, 403):
            raise ConnectorError(
                f"Anthropic refused the key for {path} (HTTP {reply.status}); "
                "check the key type and scopes"
            )
        if reply.status == 404:
            raise ConnectorError(f"{path} is not available to this organization or plan (HTTP 404)")
        if reply.status != 200:
            raise ConnectorError(f"Anthropic answered HTTP {reply.status} for {path}")
        return reply.json()


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(text: Any) -> datetime | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _rec(feed: str, obj: dict[str, Any], when: datetime | None) -> Record:
    body = {"feed": f"anthropic.{feed}", **obj}
    return Record(json.dumps(body, separators=(",", ":"), ensure_ascii=False), when)


class AnthropicConnector:
    poll_every = POLL_EVERY

    def __init__(self, settings: AnthropicSettings, client: AnthropicClient) -> None:
        self._s = settings
        self._c = client

    def pull(self, checkpoint: str | None, now: datetime) -> Pull:
        cp: dict[str, Any] = json.loads(checkpoint) if checkpoint else {}
        records: list[Record] = []
        warnings: list[str] = []
        for feed in self._s.feeds:
            try:
                state = cp.setdefault(feed, {})
                records.extend(getattr(self, f"_{feed}")(state, now))
            except RetryLaterError:
                raise  # the whole organization is rate limited: wait as asked
            except ConnectorError as exc:
                warnings.append(f"{feed}: {exc}")
        if warnings and len(warnings) == len(self._s.feeds) and not records:
            raise ConnectorError("; ".join(warnings)[:500])
        return Pull(records, json.dumps(cp), None, warnings)

    def _start(self, state: dict[str, Any], now: datetime) -> datetime:
        return _parse(state.get("end")) or (now - timedelta(days=self._s.backfill_days))

    def _buckets(
        self,
        path: str,
        feed: str,
        width: str,
        step: timedelta,
        state: dict[str, Any],
        now: datetime,
        group: list[str],
    ) -> list[Record]:
        """Finished buckets since the checkpoint, one record per result row."""
        start = self._start(state, now)
        if width == "1h":
            start = start.replace(minute=0, second=0, microsecond=0)
            end = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        else:
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            end = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if end <= start:
            return []
        params = [("starting_at", _iso(start)), ("ending_at", _iso(end)), ("bucket_width", width)]
        params += [("group_by[]", g) for g in group]
        out: list[Record] = []
        page: str | None = None
        for _ in range(MAX_PAGES):
            data = self._c.get(path, params + ([("page", page)] if page else []))
            for bucket in data.get("data") or []:
                b_start, b_end = bucket.get("starting_at"), bucket.get("ending_at")
                for row in bucket.get("results") or []:
                    if isinstance(row, dict):
                        out.append(
                            _rec(
                                feed,
                                {"starting_at": b_start, "ending_at": b_end, **row},
                                _parse(b_start),
                            )
                        )
            page = data.get("next_page") if data.get("has_more") else None
            if not page:
                break
        state["end"] = end.isoformat()
        return out

    def _usage(self, state: dict[str, Any], now: datetime) -> list[Record]:
        return self._buckets(
            "/v1/organizations/usage_report/messages",
            "usage",
            "1h",
            timedelta(hours=1),
            state,
            now,
            ["model", "workspace_id", "api_key_id"],
        )

    def _cost(self, state: dict[str, Any], now: datetime) -> list[Record]:
        return self._buckets(
            "/v1/organizations/cost_report",
            "cost",
            "1d",
            timedelta(days=1),
            state,
            now,
            ["workspace_id", "description"],
        )

    def _days(self, state: dict[str, Any], now: datetime, ready: timedelta) -> list[date]:
        """Days not yet read whose data is final (`ready` after the day ends)."""
        last = (
            date.fromisoformat(state["day"])
            if state.get("day")
            else (now - timedelta(days=self._s.backfill_days + 1)).date()
        )
        days: list[date] = []
        d = last + timedelta(days=1)
        while (
            datetime(d.year, d.month, d.day, tzinfo=UTC) + timedelta(days=1) + ready <= now
            and len(days) < 31
        ):
            days.append(d)
            d += timedelta(days=1)
        return days

    def _paged_day(
        self, path: str, feed: str, params: list[tuple[str, str]], when: datetime
    ) -> list[Record]:
        out: list[Record] = []
        page: str | None = None
        for _ in range(MAX_PAGES):
            data = self._c.get(path, params + ([("page", page)] if page else []))
            for item in data.get("data") or []:
                if isinstance(item, dict):
                    out.append(_rec(feed, item, _parse(item.get("date")) or when))
            page = data.get("next_page")
            if not page or (data.get("has_more") is False):
                break
        return out

    def _claude_code(self, state: dict[str, Any], now: datetime) -> list[Record]:
        out: list[Record] = []
        for d in self._days(state, now, timedelta(hours=2)):
            out += self._paged_day(
                "/v1/organizations/usage_report/claude_code",
                "claude_code",
                [("starting_at", d.isoformat()), ("limit", "1000")],
                datetime(d.year, d.month, d.day, tzinfo=UTC),
            )
            state["day"] = d.isoformat()
        return out

    def _analytics_users(self, state: dict[str, Any], now: datetime) -> list[Record]:
        out: list[Record] = []
        for d in self._days(state, now, timedelta(hours=14)):
            out += self._paged_day(
                "/v1/organizations/analytics/users",
                "analytics_users",
                [("date", d.isoformat()), ("limit", "1000")],
                datetime(d.year, d.month, d.day, tzinfo=UTC),
            )
            state["day"] = d.isoformat()
        return out

    def _compliance_activities(self, state: dict[str, Any], now: datetime) -> list[Record]:
        """New activities since the checkpoint. The feed is newest first; pages go older
        with after_id, so one poll reads back to the checkpoint and keeps the ids seen at
        its newest instant to skip them next time."""
        since = self._start(state, now)
        seen = set(state.get("seen", []))
        params = [("created_at.gte", _iso(since)), ("limit", "1000")]
        items: list[dict[str, Any]] = []
        after: str | None = None
        for _ in range(MAX_PAGES):
            data = self._c.get(
                "/v1/compliance/activities", params + ([("after_id", after)] if after else [])
            )
            items += [x for x in data.get("data") or [] if isinstance(x, dict)]
            after = data.get("last_id") if data.get("has_more") else None
            if not after:
                break
        fresh = [x for x in items if str(x.get("id")) not in seen]
        if items:
            newest = max((_parse(x.get("created_at")) or since) for x in items)
            state["end"] = newest.isoformat()
            state["seen"] = [
                str(x.get("id")) for x in items if _parse(x.get("created_at")) == newest
            ][:1000]
        fresh.sort(key=lambda x: str(x.get("created_at")))
        return [_rec("compliance_activities", x, _parse(x.get("created_at"))) for x in fresh]


def test_connection(
    settings: AnthropicSettings, client: AnthropicClient, now: datetime
) -> dict[str, str]:
    """One small request per enabled feed; says which work with this key."""
    probes = {
        "usage": (
            "/v1/organizations/usage_report/messages",
            [
                ("starting_at", _iso(now - timedelta(hours=2))),
                ("bucket_width", "1h"),
                ("limit", "1"),
            ],
        ),
        "cost": (
            "/v1/organizations/cost_report",
            [("starting_at", _iso(now - timedelta(days=2))), ("limit", "1")],
        ),
        "claude_code": (
            "/v1/organizations/usage_report/claude_code",
            [("starting_at", (now - timedelta(days=2)).date().isoformat()), ("limit", "1")],
        ),
        "analytics_users": (
            "/v1/organizations/analytics/users",
            [("date", (now - timedelta(days=2)).date().isoformat()), ("limit", "1")],
        ),
        "compliance_activities": ("/v1/compliance/activities", [("limit", "1")]),
    }
    out: dict[str, str] = {}
    for feed in settings.feeds:
        path, params = probes[feed]
        try:
            client.get(path, params)
            out[feed] = "ok"
        except ConnectorError as exc:
            out[feed] = str(exc)
    return out
