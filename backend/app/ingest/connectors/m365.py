"""Microsoft 365 connector (ADR-0002): Management Activity API and Microsoft Graph.

One Entra app registration per tenant, read-only application permissions, client
credentials with a certificate (preferred) or a client secret. Each record is stored as
Microsoft's JSON, unmodified, as `raw`; templates map it.

Feeds and the application permission each needs:

- Audit.AzureActiveDirectory, Audit.Exchange, Audit.SharePoint, Audit.General (includes
  Copilot interactions), DLP.All: Management Activity API, ActivityFeed.Read (DLP.All also
  ActivityFeed.ReadDlp).
- signins: Graph auditLogs/signIns, AuditLog.Read.All (needs Entra ID P1 or P2).
- directory_audits: Graph auditLogs/directoryAudits, AuditLog.Read.All.
- alerts: Graph security/alerts_v2, SecurityAlert.Read.All.

The checkpoint keeps, per feed, the end of the last window read. Activity content is
listed by `contentCreated` in windows of at most 24 hours, starting no more than 7 days
back (the API's limits); Graph feeds are read in time windows that end a little before
now, since Microsoft delivers some records minutes late. A failing feed (a missing
license, a permission not granted) is reported and skipped; the others continue.
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import quote, urlencode, urlsplit

import httpx
import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ingest.connectors.base import ConnectorError, Https, Pull, Record, RetryLaterError

ContentType = Literal[
    "Audit.AzureActiveDirectory", "Audit.Exchange", "Audit.SharePoint", "Audit.General", "DLP.All"
]
GraphFeed = Literal["signins", "directory_audits", "alerts"]
CONTENT_TYPES: tuple[ContentType, ...] = (
    "Audit.AzureActiveDirectory",
    "Audit.Exchange",
    "Audit.SharePoint",
    "Audit.General",
    "DLP.All",
)

DEFAULT_CONTENT: tuple[ContentType, ...] = CONTENT_TYPES[:4]  # DLP.All needs another permission
DEFAULT_GRAPH: tuple[GraphFeed, ...] = ("signins", "directory_audits")

CLOUDS = {
    "commercial": ("login.microsoftonline.com", "manage.office.com", "graph.microsoft.com"),
    "gcc": ("login.microsoftonline.com", "manage-gcc.office.com", "graph.microsoft.com"),
    "gcc_high": ("login.microsoftonline.us", "manage.office365.us", "graph.microsoft.us"),
}
GRAPH = {
    "signins": ("auditLogs/signIns", "createdDateTime"),
    "directory_audits": ("auditLogs/directoryAudits", "activityDateTime"),
    "alerts": ("security/alerts_v2", "createdDateTime"),
}
POLL_EVERY = timedelta(minutes=5)
GRAPH_LAG = timedelta(minutes=20)  # sign-ins and audits can arrive minutes late
MAX_BLOBS = 100  # content blobs per poll, all types
MAX_RECORDS = 50_000
MAX_PAGES = 20
GUID = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


class M365Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(pattern=GUID)
    client_id: str = Field(pattern=GUID)
    cloud: Literal["commercial", "gcc", "gcc_high"] = "commercial"
    auth: Literal["certificate", "secret"] = "certificate"
    content_types: list[ContentType] = Field(
        default_factory=lambda: list(DEFAULT_CONTENT), max_length=5
    )
    graph: list[GraphFeed] = Field(default_factory=lambda: list(DEFAULT_GRAPH), max_length=3)
    backfill_hours: int = Field(default=24, ge=0, le=168)

    @field_validator("content_types", "graph")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))

    def hosts(self) -> tuple[str, str, str]:
        return CLOUDS[self.cloud]


@dataclass(frozen=True, slots=True)
class M365Secret:
    """Either a client secret, or a certificate and its private key (PEM)."""

    client_secret: str | None = None
    certificate_pem: str | None = None
    private_key_pem: str | None = None

    @classmethod
    def load(cls, text: str | None) -> M365Secret:
        if not text:
            return cls()
        try:
            data = json.loads(text)
        except ValueError:
            return cls(client_secret=text)
        return cls(
            client_secret=data.get("client_secret"),
            certificate_pem=data.get("certificate_pem"),
            private_key_pem=data.get("private_key_pem"),
        )

    def dump(self) -> str:
        return json.dumps(
            {
                k: v
                for k, v in (
                    ("client_secret", self.client_secret),
                    ("certificate_pem", self.certificate_pem),
                    ("private_key_pem", self.private_key_pem),
                )
                if v
            }
        )


def check_certificate(certificate_pem: str, private_key_pem: str) -> str:
    """Validates the pair and returns the SHA-1 thumbprint Entra shows (hex)."""
    try:
        cert = x509.load_pem_x509_certificate(certificate_pem.encode())
        key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    except (ValueError, TypeError) as exc:
        raise ConnectorError("The certificate or private key is not valid PEM") from exc
    if cert.public_key().public_numbers() != key.public_key().public_numbers():  # type: ignore[union-attr]  # RSA keys, checked by the comparison
        raise ConnectorError("The private key does not belong to the certificate")
    return cert.fingerprint(hashes.SHA1()).hex().upper()  # noqa: S303  # Entra's thumbprint format


class M365Client:
    def __init__(
        self,
        settings: M365Settings,
        secret: M365Secret,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self._secret = secret
        self._login, self._manage, self._graph = settings.hosts()
        self._http = Https(frozenset(settings.hosts()), transport)
        self._tokens: dict[str, tuple[str, float]] = {}

    # --- tokens ----------------------------------------------------------------------

    def _assertion(self, audience: str) -> str:
        if not (self._secret.certificate_pem and self._secret.private_key_pem):
            raise ConnectorError("No certificate is stored for this source")
        cert = x509.load_pem_x509_certificate(self._secret.certificate_pem.encode())
        thumb = base64.urlsafe_b64encode(cert.fingerprint(hashes.SHA256())).decode().rstrip("=")
        now = int(time.time())
        claims = {
            "aud": audience,
            "iss": self.settings.client_id,
            "sub": self.settings.client_id,
            "jti": str(uuid.uuid4()),
            "nbf": now,
            "iat": now,
            "exp": now + 600,
        }
        return jwt.encode(
            claims, self._secret.private_key_pem, algorithm="PS256", headers={"x5t#S256": thumb}
        )

    def token(self, resource_host: str) -> str:
        cached = self._tokens.get(resource_host)
        if cached and cached[1] > time.time() + 120:
            return cached[0]
        url = f"https://{self._login}/{self.settings.tenant_id}/oauth2/v2.0/token"
        form = {
            "client_id": self.settings.client_id,
            "scope": f"https://{resource_host}/.default",
            "grant_type": "client_credentials",
        }
        if self.settings.auth == "certificate":
            form["client_assertion_type"] = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
            form["client_assertion"] = self._assertion(url)
        else:
            if not self._secret.client_secret:
                raise ConnectorError("No client secret is stored for this source")
            form["client_secret"] = self._secret.client_secret
        reply = self._http.request("POST", url, form=form, max_body=256 * 1024)
        if reply.status != 200:
            raise ConnectorError(_entra_error(reply))
        data = reply.json()
        token = str(data.get("access_token") or "")
        if not token:
            raise ConnectorError("Entra returned no access token")
        self._tokens[resource_host] = (token, time.time() + float(data.get("expires_in", 3599)))
        return token

    def _get(self, host: str, url: str) -> tuple[Any, httpx.Headers]:
        if urlsplit(url).hostname != host:
            raise ConnectorError(f"Refused a link to another host from {host}")
        reply = self._http.request(
            "GET", url, headers={"Authorization": f"Bearer {self.token(host)}"}
        )
        if reply.status != 200:
            raise ConnectorError(_api_error(host, reply))
        return reply.json(), reply.headers

    # --- Management Activity API -----------------------------------------------------

    def _feed_root(self) -> str:
        return f"https://{self._manage}/api/v1.0/{self.settings.tenant_id}/activity/feed"

    def start_subscription(self, content_type: str) -> None:
        url = (
            f"{self._feed_root()}/subscriptions/start?contentType={quote(content_type)}"
            f"&PublisherIdentifier={self.settings.tenant_id}"
        )
        reply = self._http.request(
            "POST", url, headers={"Authorization": f"Bearer {self.token(self._manage)}"}
        )
        body = reply.body.decode("utf-8", "replace")
        if reply.status == 200 or "AF20024" in body:  # AF20024: already enabled
            return
        raise ConnectorError(_api_error(self._manage, reply))

    def list_content(
        self, content_type: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        q = urlencode(
            {
                "contentType": content_type,
                "startTime": _iso(start),
                "endTime": _iso(end),
                "PublisherIdentifier": self.settings.tenant_id,
            }
        )
        url: str | None = f"{self._feed_root()}/subscriptions/content?{q}"
        out: list[dict[str, Any]] = []
        for _ in range(MAX_PAGES):
            if url is None:
                break
            data, headers = self._get(self._manage, url)
            if isinstance(data, list):
                out.extend(x for x in data if isinstance(x, dict))
            url = headers.get("NextPageUri")
        return out

    def content(self, uri: str) -> list[dict[str, Any]]:
        data, _ = self._get(self._manage, uri)
        return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []

    # --- Graph -----------------------------------------------------------------------

    def graph(self, feed: GraphFeed, start: datetime, end: datetime) -> list[dict[str, Any]]:
        path, field = GRAPH[feed]
        flt = f"{field} ge {_iso(start)} and {field} lt {_iso(end)}"
        url: str | None = f"https://{self._graph}/v1.0/{path}?" + urlencode(
            {"$filter": flt, "$top": "1000" if feed != "alerts" else "500"}
        )
        out: list[dict[str, Any]] = []
        for _ in range(MAX_PAGES):
            if url is None:
                break
            data, _ = self._get(self._graph, url)
            out.extend(x for x in (data.get("value") or []) if isinstance(x, dict))
            url = data.get("@odata.nextLink")
        return out


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _entra_error(reply: Any) -> str:
    try:
        data = reply.json()
        code = str(data.get("error") or "")
        codes = data.get("error_codes") or []
    except ConnectorError:
        code, codes = "", []
    hint = {
        7000215: "the client secret is wrong or expired",
        700027: "the certificate is not uploaded to the app registration, or does not match",
        700016: "no app with this client id in the tenant",
        90002: "no such tenant",
        7000222: "the client secret has expired",
    }
    for c in codes:
        if c in hint:
            return f"Entra refused the sign-in: {hint[c]} (AADSTS{c})"
    return f"Entra refused the sign-in ({code or f'HTTP {reply.status}'})"


def _api_error(host: str, reply: Any) -> str:
    body = reply.body.decode("utf-8", "replace")
    if "AF20022" in body:  # listing content before the subscription has started
        return "ok (no subscription yet; it starts on the first pull)"
    if reply.status == 403 and "premium license" in body.lower():
        return "Sign-in logs need Entra ID P1 or P2 in this tenant"
    if reply.status in (401, 403):
        return (
            f"{host} refused access (HTTP {reply.status});"
            " check the app's API permissions and admin consent"
        )
    return f"{host} answered HTTP {reply.status}"


def _record_time(item: dict[str, Any]) -> datetime | None:
    for key in ("CreationTime", "createdDateTime", "activityDateTime"):
        t = _parse(item.get(key))
        if t:
            return t
    return None


def _line(item: dict[str, Any]) -> str:
    return json.dumps(item, separators=(",", ":"), ensure_ascii=False)


class M365Connector:
    poll_every = POLL_EVERY

    def __init__(self, client: M365Client) -> None:
        self._c = client

    def pull(self, checkpoint: str | None, now: datetime) -> Pull:
        s = self._c.settings
        cp: dict[str, Any] = json.loads(checkpoint) if checkpoint else {}
        feeds: dict[str, Any] = cp.setdefault("feeds", {})
        started: list[str] = cp.setdefault("started", [])
        records: list[Record] = []
        warnings: list[str] = []
        floor = now - timedelta(days=7) + timedelta(minutes=5)
        default_start = now - timedelta(hours=s.backfill_hours)
        blobs = 0
        oldest_end: datetime | None = None

        for ct in s.content_types:
            try:
                if ct not in started:
                    self._c.start_subscription(ct)
                    started.append(ct)
                state = feeds.setdefault(ct, {})
                start = max(_parse(state.get("end")) or default_start, floor)
                seen = set(state.get("seen", []))
                while start < now and blobs < MAX_BLOBS and len(records) < MAX_RECORDS:
                    end = min(start + timedelta(hours=24), now)
                    items = sorted(
                        self._c.list_content(ct, start, end),
                        key=lambda x: (str(x.get("contentCreated")), str(x.get("contentId"))),
                    )
                    stop_at: datetime | None = None
                    for item in items:
                        if item.get("contentId") in seen:
                            continue
                        if blobs >= MAX_BLOBS or len(records) >= MAX_RECORDS:
                            stop_at = _parse(item.get("contentCreated")) or start
                            break
                        for rec in self._c.content(str(item.get("contentUri", ""))):
                            records.append(Record(_line(rec), _record_time(rec)))
                        blobs += 1
                        seen.add(str(item.get("contentId")))
                    if stop_at is not None:
                        # Resume at the first blob not read; keep ids at that instant.
                        at = [
                            str(i.get("contentId"))
                            for i in items
                            if _parse(i.get("contentCreated")) == stop_at
                            and i.get("contentId") in seen
                        ]
                        state.update(end=stop_at.isoformat(), seen=at)
                        break
                    state.update(end=end.isoformat(), seen=[])
                    seen = set()
                    start = end
                end_t = _parse(state.get("end"))
                if end_t and (oldest_end is None or end_t < oldest_end):
                    oldest_end = end_t
            except RetryLaterError:
                raise  # the whole organization is rate limited: wait as asked
            except ConnectorError as exc:
                warnings.append(f"{ct}: {exc}")

        graph_end = now - GRAPH_LAG
        for feed in s.graph:
            try:
                state = feeds.setdefault(feed, {})
                start = _parse(state.get("end")) or (default_start - GRAPH_LAG)
                if start >= graph_end:
                    continue
                end = min(start + timedelta(hours=24), graph_end)
                items = self._c.graph(feed, start, end)
                items.sort(key=lambda x: str(x.get(GRAPH[feed][1])))
                for item in items:
                    records.append(Record(_line(item), _record_time(item)))
                state["end"] = end.isoformat()
                if oldest_end is None or end < oldest_end:
                    oldest_end = end
            except RetryLaterError:
                raise  # the whole organization is rate limited: wait as asked
            except ConnectorError as exc:
                warnings.append(f"{feed}: {exc}")

        if warnings and not records and len(warnings) == len(s.content_types) + len(s.graph):
            raise ConnectorError("; ".join(warnings)[:500])
        behind = (now - oldest_end).total_seconds() if oldest_end else None
        return Pull(records, json.dumps(cp), behind, warnings)


def test_connection(client: M365Client) -> dict[str, str]:
    """Get the tokens and read one small page from each enabled API; says which work."""
    now = datetime.now(UTC)
    hour = now - timedelta(hours=1)
    checks: list[tuple[str, Any]] = []
    first = client.settings.content_types[0] if client.settings.content_types else None
    if first:
        checks.append(("Management Activity API", lambda: client.list_content(first, hour, now)))
    for feed in client.settings.graph:
        checks.append((f"Graph {feed}", lambda f=feed: client.graph(f, hour, now)))
    results: dict[str, str] = {}
    for name, fn in checks:
        try:
            fn()
            results[name] = "ok"
        except ConnectorError as exc:
            results[name] = str(exc)
    return results
