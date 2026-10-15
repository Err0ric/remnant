"""Builds the pull connector for an API source (m365, anthropic) from its settings and
stored credential, and runs its connection test. Loki keeps its own path (ADR-0011)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

import httpx

from app.ingest.connectors import anthropic, m365
from app.ingest.connectors.base import Connector, ConnectorError

ApiKind = Literal["m365", "anthropic"]
API_KINDS: tuple[ApiKind, ...] = ("m365", "anthropic")


class SourceLike(Protocol):
    @property
    def kind(self) -> str: ...
    @property
    def m365(self) -> m365.M365Settings | None: ...
    @property
    def anthropic(self) -> anthropic.AnthropicSettings | None: ...


def secret_text(
    kind: ApiKind,
    *,
    api_key: str | None = None,
    client_secret: str | None = None,
    certificate_pem: str | None = None,
    private_key_pem: str | None = None,
    auth: Literal["certificate", "secret"] = "certificate",
) -> str:
    """The credential to store encrypted for a new API source. Checks it has the parts the
    settings need (and that a certificate matches its key) before anything is saved."""
    if kind == "anthropic":
        if not api_key or not api_key.startswith("sk-ant-"):
            raise ConnectorError("Paste an Anthropic Admin, Analytics, or Compliance API key")
        return api_key
    if auth == "secret":
        if not client_secret:
            raise ConnectorError("Paste the app registration's client secret")
        return m365.M365Secret(client_secret=client_secret).dump()
    if not certificate_pem or not private_key_pem:
        raise ConnectorError("Paste the certificate and its private key (PEM)")
    m365.check_certificate(certificate_pem, private_key_pem)
    return m365.M365Secret(certificate_pem=certificate_pem, private_key_pem=private_key_pem).dump()


def for_source(
    source: SourceLike, secret: str | None, transport: httpx.BaseTransport | None = None
) -> Connector:
    settings = source.m365 if source.kind == "m365" else source.anthropic
    if source.kind not in API_KINDS or settings is None:
        raise ConnectorError("This source has no API settings")
    return build(source.kind, settings, secret, transport)


def build(
    kind: ApiKind,
    settings: m365.M365Settings | anthropic.AnthropicSettings,
    secret: str | None,
    transport: httpx.BaseTransport | None = None,
) -> Connector:
    if kind == "m365" and isinstance(settings, m365.M365Settings):
        client = m365.M365Client(settings, m365.M365Secret.load(secret), transport)
        return m365.M365Connector(client)
    if kind == "anthropic" and isinstance(settings, anthropic.AnthropicSettings):
        return anthropic.AnthropicConnector(
            settings, anthropic.AnthropicClient(secret or "", transport)
        )
    raise ConnectorError("This source has no API settings")


def probe(
    kind: ApiKind,
    settings: m365.M365Settings | anthropic.AnthropicSettings,
    secret: str | None,
    now: datetime,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, str]:
    """One small read per enabled feed; maps each feed to "ok" or why it failed."""
    if kind == "m365" and isinstance(settings, m365.M365Settings):
        client = m365.M365Client(settings, m365.M365Secret.load(secret), transport)
        return m365.test_connection(client)
    if kind == "anthropic" and isinstance(settings, anthropic.AnthropicSettings):
        client_a = anthropic.AnthropicClient(secret or "", transport)
        return anthropic.test_connection(settings, client_a, now)
    raise ConnectorError("This source has no API settings")
