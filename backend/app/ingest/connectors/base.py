"""The pull connector interface (SPEC 3.7) and its HTTPS helper.

A connector turns a checkpoint into new records and the next checkpoint. The ingest
worker calls `pull` no more often than `poll_every`, backs off after errors, writes the
records through the source's parser, and saves the checkpoint only after the lake write,
so a crash can repeat records but never lose them.

Every request goes to a host on the connector's allowlist, over https, to the address
checked by the webhook rules (ADR-0007 row 4) and pinned for the connection, with no
redirects, no environment proxies, and a size cap. With `network.https_proxy` set, requests
go through that proxy by host name instead (ADR-0018). Credentials are never logged or put
in errors.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.alerts.net import check_url, egress
from app.core.errors import ParamInvalidError

TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)
MAX_BODY = 32 * 1024 * 1024


class ConnectorError(Exception):
    """A failure to show on the Sources page; never carries credentials."""


class RetryLaterError(ConnectorError):
    def __init__(self, message: str, seconds: float) -> None:
        super().__init__(message)
        self.seconds = seconds


@dataclass(frozen=True, slots=True)
class Record:
    text: str  # one line for the parser; the provider's JSON for API connectors
    time: datetime | None = None  # used when the parser finds no time of its own


@dataclass(slots=True)
class Pull:
    records: list[Record]
    checkpoint: str
    behind_s: float | None = None
    warnings: list[str] = field(default_factory=list)  # partial failures (one feed of many)


class Connector(Protocol):
    poll_every: timedelta

    def pull(self, checkpoint: str | None, now: datetime) -> Pull: ...


@dataclass(frozen=True, slots=True)
class Reply:
    status: int
    headers: httpx.Headers
    body: bytes

    def json(self) -> Any:
        try:
            return json.loads(self.body)
        except ValueError:
            raise ConnectorError("The service did not answer with JSON") from None


class Https:
    """Requests to allowlisted hosts only, pinned to the checked address."""

    def __init__(self, hosts: frozenset[str], transport: httpx.BaseTransport | None = None) -> None:
        self._hosts = hosts
        self._transport = transport

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        form: dict[str, str] | None = None,
        max_body: int = MAX_BODY,
    ) -> Reply:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https" or host not in self._hosts:
            raise ConnectorError(f"Refused a request to {host or 'an unknown host'}")
        out = egress()
        proxy = out.proxy()
        if proxy is not None:
            # Through the proxy (ADR-0018): it resolves the allowlisted name; TLS still
            # checks the certificate against it. No local DNS, so no pin.
            target, ext = url, {}
            send = {**(headers or {}), "Accept": "application/json"}
        else:
            try:
                dest = check_url("webhook", url)  # resolves; refuses metadata and link-local
            except ParamInvalidError as exc:
                raise ConnectorError(str(exc)) from None
            if dest.private:
                raise ConnectorError(f"{host} resolved to a private address; refused")
            literal = f"[{dest.pin}]" if ":" in dest.pin else dest.pin
            target = urlunsplit(parts._replace(netloc=f"{literal}:{dest.port}"))
            ext = {"sni_hostname": host}
            send = {**(headers or {}), "Host": host, "Accept": "application/json"}
        try:
            with (
                httpx.Client(
                    timeout=TIMEOUT,
                    follow_redirects=False,
                    trust_env=False,
                    transport=self._transport,
                    proxy=proxy,
                    verify=out.verify(),
                ) as client,
                client.stream(method, target, headers=send, data=form, extensions=ext) as res,
            ):
                data = b""
                for chunk in res.iter_bytes():
                    data += chunk
                    if len(data) > max_body:
                        raise ConnectorError(f"{host} sent more than {max_body // 1048576} MB")
                reply = Reply(res.status_code, res.headers, data)
        except httpx.HTTPError as exc:
            raise ConnectorError(f"Cannot reach {host} ({type(exc).__name__})") from None
        if reply.status in (429, 503):
            wait = reply.headers.get("retry-after", "60")
            seconds = float(wait) if wait.replace(".", "", 1).isdigit() else 60.0
            message = f"{host} asked to slow down (HTTP {reply.status})"
            raise RetryLaterError(message, min(seconds, 3600))
        return reply


def backoff(failures: int, poll_every: timedelta, retry_after: float | None = None) -> timedelta:
    """Wait before the next try: the server's Retry-After, else doubling up to an hour."""
    if retry_after is not None:
        return timedelta(seconds=max(retry_after, poll_every.total_seconds()))
    grown: timedelta = poll_every * (2 ** min(failures, 10))
    return min(grown, timedelta(hours=1))
