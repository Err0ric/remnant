"""Grafana Loki as a source (ADR-0011).

The ingest worker asks Loki for lines with `GET /loki/api/v1/query_range` (forward, a
`limit` per request) and feeds each line to the source's parser exactly as a line read
from a file; the line is `raw`, unchanged. Stream labels go to `envelope.loki_labels`.

Position is kept as the newest timestamp read plus the hashes of the lines read at that
exact nanosecond, so a restart or a page boundary never reads a line twice or skips one.
Each poll stops `LAG` before now, so lines that reach Loki a little late are still read.

Network rules are the webhook rules (ADR-0007 row 4): https for public hosts, http only to
private or loopback addresses, metadata and link-local addresses refused, the address
resolved once and pinned, no redirects, no proxies. Credentials are never logged or
returned; errors name the HTTP status or failure kind only.
"""

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.alerts.net import Destination, check_url
from app.core.errors import ParamInvalidError

LIMIT = 1000  # lines per request; Loki's default cap is 5000
MAX_PAGES = 20  # requests per poll, so one backlog cannot hold the worker for long
MAX_BODY = 32 * 1024 * 1024
POLL_EVERY = timedelta(seconds=30)
LAG = timedelta(seconds=30)
TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)

_STRING = r'"(?:[^"\\]|\\.)*"'
_MATCHER = rf"[A-Za-z_][A-Za-z0-9_]*\s*(?:=~|!~|!=|=)\s*{_STRING}"
_SELECTOR = re.compile(rf"\{{\s*{_MATCHER}(?:\s*,\s*{_MATCHER})*\s*,?\s*\}}")
_FILTER = re.compile(rf"\s*(?:\|=|!=|\|~|!~)\s*(?:{_STRING}|`[^`]*`)")


def check_query(query: str) -> str:
    """A stream selector, optionally followed by line filters; nothing else (ADR-0011
    row 1). Loki still checks the meaning; this keeps parsers and formatting stages out."""
    text = query.strip()
    m = _SELECTOR.match(text)
    if not m:
        raise ParamInvalidError(
            'Start with a label selector such as {job="syslog"} or {host=~"fw.*"}'
        )
    rest = text[m.end() :]
    filters = 0
    while rest.strip():
        f = _FILTER.match(rest)
        if not f:
            raise ParamInvalidError(
                'After the selector, only line filters are allowed: |= "text", != "text", '
                '|~ "regex", !~ "regex"'
            )
        filters += 1
        rest = rest[f.end() :]
    if filters > 5:
        raise ParamInvalidError("Use at most 5 line filters")
    return text


class LokiSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2048)  # the Loki root, e.g. http://loki:3100
    query: str = Field(min_length=3, max_length=1000)
    tenant: str | None = Field(default=None, max_length=200, pattern=r"^[A-Za-z0-9_.\-|]+$")
    auth: Literal["none", "basic", "bearer"] = "none"
    username: str | None = Field(default=None, max_length=200)
    backfill_hours: int = Field(default=24, ge=0, le=24 * 3650)

    @field_validator("query")
    @classmethod
    def _query(cls, value: str) -> str:
        return check_query(value)

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        parts = urlsplit(value.strip())
        if parts.query or parts.fragment:
            raise ValueError("Give the Loki root URL without a query string")
        return value.strip().rstrip("/")


@dataclass(frozen=True, slots=True)
class LokiLine:
    ns: int
    line: str
    labels: dict[str, str]
    digest: str


@dataclass(slots=True)
class Position:
    ns: int  # newest timestamp read, nanoseconds since the epoch
    seen: list[str] = field(default_factory=list)  # digests read at exactly `ns`

    def dump(self) -> str:
        return json.dumps({"ns": str(self.ns), "seen": self.seen})

    @classmethod
    def load(cls, text: str | None) -> "Position | None":
        if not text:
            return None
        try:
            data = json.loads(text)
            return cls(int(data["ns"]), [str(d) for d in data.get("seen", [])][:LIMIT])
        except (ValueError, KeyError, TypeError):
            return None


@dataclass(frozen=True, slots=True)
class PollResult:
    lines: list[LokiLine]
    position: Position
    behind: timedelta  # how far the position is behind now


def to_ns(moment: datetime) -> int:
    return int(moment.astimezone(UTC).timestamp()) * 1_000_000_000 + moment.microsecond * 1000


def from_ns(ns: int) -> datetime:
    return datetime.fromtimestamp(ns / 1_000_000_000, tz=UTC)


def _digest(labels: dict[str, str], line: str) -> str:
    key = json.dumps(labels, sort_keys=True, separators=(",", ":")) + "\n" + line
    return hashlib.sha256(key.encode("utf-8", "replace")).hexdigest()[:24]


def auth_headers(settings: LokiSettings, secret: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if settings.tenant:
        headers["X-Scope-OrgID"] = settings.tenant
    if settings.auth == "basic":
        token = base64.b64encode(f"{settings.username or ''}:{secret or ''}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    elif settings.auth == "bearer":
        headers["Authorization"] = f"Bearer {secret or ''}"
    return headers


class LokiClient:
    def __init__(
        self,
        settings: LokiSettings,
        secret: str | None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._secret = secret
        self._transport = transport

    def _get(self, path: str, params: dict[str, str]) -> Any:
        # Checked on every request: a name that now resolves somewhere else is refused.
        dest: Destination = check_url("webhook", self._settings.url + path)
        parts = urlsplit(dest.url)
        literal = f"[{dest.pin}]" if ":" in dest.pin else dest.pin
        target = urlunsplit(
            parts._replace(netloc=f"{literal}:{dest.port}", query=urlencode(params))
        )
        name = f"[{dest.host}]" if ":" in dest.host else dest.host
        headers = {
            **auth_headers(self._settings, self._secret),
            "Host": f"{name}:{dest.port}",
            "Accept": "application/json",
        }
        ext: dict[str, Any] = {"sni_hostname": dest.host} if dest.scheme == "https" else {}
        try:
            with (
                httpx.Client(
                    timeout=TIMEOUT,
                    follow_redirects=False,
                    trust_env=False,
                    transport=self._transport,
                ) as client,
                client.stream("GET", target, headers=headers, extensions=ext) as res,
            ):
                if res.status_code != 200:
                    raise ParamInvalidError(_status_message(res.status_code))
                data = b""
                for chunk in res.iter_bytes():
                    data += chunk
                    if len(data) > MAX_BODY:
                        raise ParamInvalidError("Loki sent more than 32 MB in one reply")
        except httpx.HTTPError as exc:
            raise ParamInvalidError(f"Cannot reach Loki ({type(exc).__name__})") from None
        try:
            return json.loads(data)
        except ValueError:
            raise ParamInvalidError("Loki did not answer with JSON") from None

    def query_range(self, start_ns: int, end_ns: int, limit: int | None = None) -> list[LokiLine]:
        data = self._get(
            "/loki/api/v1/query_range",
            {
                "query": self._settings.query,
                "start": str(start_ns),
                "end": str(end_ns),
                "limit": str(limit or LIMIT),
                "direction": "forward",
            },
        )
        try:
            if data.get("status") != "success" or data["data"]["resultType"] != "streams":
                raise ParamInvalidError("Loki did not return log streams for this query")
            out: list[LokiLine] = []
            for stream in data["data"]["result"]:
                labels = {str(k): str(v) for k, v in (stream.get("stream") or {}).items()}
                for value in stream.get("values") or []:
                    ns, line = int(value[0]), str(value[1])
                    out.append(LokiLine(ns, line, labels, _digest(labels, line)))
        except (KeyError, TypeError, ValueError, IndexError, AttributeError):
            raise ParamInvalidError("Loki's reply was not in the expected format") from None
        out.sort(key=lambda x: (x.ns, x.digest))
        return out


def _status_message(status: int) -> str:
    if status in (401, 403):
        return f"Loki refused the credentials (HTTP {status})"
    if status == 400:
        return "Loki rejected the query (HTTP 400); check the label selector"
    if status == 404:
        return "No Loki API at this URL (HTTP 404); give the Loki root, e.g. http://loki:3100"
    return f"Loki answered HTTP {status}"


def poll(
    client: LokiClient, settings: LokiSettings, position: Position | None, now: datetime
) -> PollResult:
    """New lines since `position`, oldest first, up to MAX_PAGES requests."""
    end_ns = to_ns(now - LAG)
    pos = position or Position(to_ns(now - timedelta(hours=settings.backfill_hours)))
    pos = Position(pos.ns, list(pos.seen))
    lines: list[LokiLine] = []
    for _ in range(MAX_PAGES):
        if pos.ns >= end_ns:
            break
        page = client.query_range(pos.ns, end_ns)
        seen = set(pos.seen)
        new = [x for x in page if not (x.ns == pos.ns and x.digest in seen)]
        lines.extend(new)
        if len(page) < LIMIT:
            # Everything up to end_ns is read; lines older than that are final.
            if new and new[-1].ns == end_ns:
                pos = Position(end_ns, [x.digest for x in new if x.ns == end_ns])
            else:
                pos = Position(end_ns, [])
            break
        top = page[-1].ns
        at_top = [x.digest for x in page if x.ns == top]
        if top == pos.ns:
            # A full page at one nanosecond: step past it rather than loop on it.
            pos = Position(top + 1, [])
        else:
            pos = Position(top, at_top)
    return PollResult(lines, pos, max(timedelta(0), now - from_ns(pos.ns)))


def test_connection(client: LokiClient, now: datetime) -> dict[str, Any]:
    """One small query over the last hour: how many lines and which streams matched."""
    page = client.query_range(to_ns(now - timedelta(hours=1)), to_ns(now), limit=100)
    streams = sorted({json.dumps(x.labels, sort_keys=True) for x in page})
    return {
        "lines": len(page),
        "streams": [json.loads(s) for s in streams[:20]],
        "newest": from_ns(page[-1].ns).isoformat() if page else None,
    }
