"""Deliver one alert (ADR-0007 rows 4 to 7).

HTTP: the connection goes to the address `net.check_*` approved, with the original host in
the Host header and TLS name; no redirects, no proxies from the environment, 10 s timeout,
and at most 64 KB of the reply read (and never stored). Errors never contain the URL,
because webhook URLs carry their token.

SMTP: STARTTLS or implicit TLS with certificate checks against the server's name, except
to a relay on this host; connected to the approved address the same way.
"""

import re
import smtplib
import socket
import ssl
from collections.abc import Callable
from email.message import EmailMessage
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.alerts.net import Destination, egress

TIMEOUT = httpx.Timeout(10.0)
MAX_REPLY = 64 * 1024
_ADDRESS = re.compile(r"^[^@\s<>,;\"]{1,64}@[A-Za-z0-9.-]{1,253}$")


class SendError(Exception):
    """A delivery failed; the message is safe to store and show (no URL, no secret)."""


def post(
    dest: Destination,
    body: bytes,
    headers: dict[str, str],
    transport: httpx.BaseTransport | None = None,
) -> int:
    out = egress()
    proxy = out.proxy() if not dest.pin else None  # no pin: sent through the proxy
    if proxy is not None:
        # The proxy resolves the name (CONNECT host:443); TLS still checks the name.
        target, extensions = dest.url, {}
        send_headers = {**headers, "User-Agent": "alerts"}
    else:
        parts = urlsplit(dest.url)
        literal = f"[{dest.pin}]" if ":" in dest.pin else dest.pin
        target = urlunsplit(parts._replace(netloc=f"{literal}:{dest.port}"))
        name = f"[{dest.host}]" if ":" in dest.host else dest.host
        extensions = {"sni_hostname": dest.host} if dest.scheme == "https" else {}
        send_headers = {**headers, "Host": f"{name}:{dest.port}", "User-Agent": "alerts"}
    try:
        with (
            httpx.Client(
                timeout=TIMEOUT,
                follow_redirects=False,
                trust_env=False,
                transport=transport,
                proxy=proxy,
                verify=out.verify(),
            ) as client,
            client.stream(
                "POST", target, content=body, headers=send_headers, extensions=extensions
            ) as res,
        ):
            read = 0
            for chunk in res.iter_bytes():
                read += len(chunk)
                if read > MAX_REPLY:
                    break
            if not 200 <= res.status_code < 300:
                raise SendError(f"The destination answered HTTP {res.status_code}")
            return res.status_code
    except httpx.HTTPError as exc:
        raise SendError(f"Could not reach the destination ({type(exc).__name__})") from None


def check_address(value: str) -> str:
    value = value.strip()
    if not _ADDRESS.fullmatch(value):
        raise ValueError(f"Not an email address: {value[:80]!r}")
    return value


def message(
    from_addr: str, to_addrs: list[str], subject: str, text: str, html: str
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = check_address(from_addr)
    msg["To"] = ", ".join(check_address(a) for a in to_addrs)
    msg["Subject"] = subject  # one line already (render.email_parts)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


class _PinnedSMTP(smtplib.SMTP):
    """Talks to `pin` while TLS and EHLO use the server's name."""

    def __init__(self, host: str, pin: str, port: int, timeout: float) -> None:
        self._pin = pin
        super().__init__(timeout=timeout)
        self.connect(host, port)

    def _get_socket(self, host: str, port: int, timeout: float) -> socket.socket:
        return socket.create_connection((self._pin, port), timeout, self.source_address)


class _PinnedSMTPSSL(smtplib.SMTP_SSL):
    def __init__(self, host: str, pin: str, port: int, timeout: float) -> None:
        self._pin = pin
        super().__init__(timeout=timeout, context=ssl.create_default_context())
        self.connect(host, port)

    def _get_socket(self, host: str, port: int, timeout: float) -> socket.socket:
        raw = socket.create_connection((self._pin, port), timeout, self.source_address)
        # smtplib sets _host in connect(); TLS checks the certificate against that name.
        return self.context.wrap_socket(raw, server_hostname=getattr(self, "_host", None))


SmtpFactory = Callable[[Destination, Literal["starttls", "tls", "none"]], smtplib.SMTP]


def _connect(dest: Destination, security: Literal["starttls", "tls", "none"]) -> smtplib.SMTP:
    if security == "tls":
        return _PinnedSMTPSSL(dest.host, dest.pin, dest.port, 10.0)
    smtp = _PinnedSMTP(dest.host, dest.pin, dest.port, 10.0)
    if security == "starttls":
        smtp.starttls(context=ssl.create_default_context())
    return smtp


def send_mail(
    dest: Destination,
    security: Literal["starttls", "tls", "none"],
    username: str | None,
    password: str | None,
    msg: EmailMessage,
    connect: SmtpFactory = _connect,
) -> None:
    try:
        smtp = connect(dest, security)
        try:
            if username:
                smtp.login(username, password or "")
            smtp.send_message(msg)
        finally:
            try:
                smtp.quit()
            except smtplib.SMTPException:
                pass
    except smtplib.SMTPAuthenticationError:
        raise SendError("The mail server refused the user name or password") from None
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        raise SendError(f"Could not send the email ({type(exc).__name__})") from None
