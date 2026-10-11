"""Alert delivery: pinned address, no redirects, no URL in errors (ADR-0007)."""

import smtplib
from email.message import EmailMessage
from typing import Any

import httpx
import pytest

from app.alerts.net import Destination
from app.alerts.send import SendError, message, post, send_mail

DEST = Destination(
    url="https://hooks.slack.com/services/T0/B0/SECRETTOKEN",
    scheme="https",
    host="hooks.slack.com",
    port=443,
    pin="198.51.100.10",
    private=False,
)


def test_posts_to_the_pinned_address_with_the_real_host() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"], seen["host"] = str(req.url), req.headers["host"]
        seen["sni"] = req.extensions.get("sni_hostname")
        return httpx.Response(200, text="ok")

    assert (
        post(DEST, b"{}", {"Content-Type": "application/json"}, httpx.MockTransport(handler)) == 200
    )
    assert seen["url"] == "https://198.51.100.10/services/T0/B0/SECRETTOKEN"
    assert seen["host"] == "hooks.slack.com:443" and seen["sni"] == "hooks.slack.com"


@pytest.mark.parametrize("status", [301, 302, 404, 500])
def test_redirects_and_errors_fail_without_leaking_the_url(status: int) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers={"Location": "http://169.254.169.254/"})

    with pytest.raises(SendError) as err:
        post(DEST, b"{}", {}, httpx.MockTransport(handler))
    assert "SECRETTOKEN" not in str(err.value) and str(status) in str(err.value)


def test_connection_errors_do_not_leak_the_url() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom https://hooks.slack.com/services/T0/B0/SECRETTOKEN")

    with pytest.raises(SendError) as err:
        post(DEST, b"{}", {}, httpx.MockTransport(handler))
    assert "SECRETTOKEN" not in str(err.value)


def test_email_message_and_login() -> None:
    msg = message("siem@example.net", ["soc@example.net"], "[X] Test", "text", "<p>html</p>")
    assert msg["To"] == "soc@example.net" and msg.is_multipart()
    with pytest.raises(ValueError):
        message("siem@example.net", ["a@b.c\r\nBcc: x@y.z"], "s", "t", "h")

    sent: list[EmailMessage] = []

    class Fake:
        def login(self, u: str, p: str) -> None:
            if p != "right":
                raise smtplib.SMTPAuthenticationError(535, b"no")

        def send_message(self, m: EmailMessage) -> None:
            sent.append(m)

        def quit(self) -> None:
            pass

    smtp_dest = Destination(
        "smtp://mail.example.net:587", "smtp", "mail.example.net", 587, "203.0.113.40", False
    )
    send_mail(smtp_dest, "starttls", "u", "right", msg, lambda d, s: Fake())  # type: ignore[arg-type,return-value]  # test double
    assert sent == [msg]
    with pytest.raises(SendError, match="refused"):
        send_mail(smtp_dest, "starttls", "u", "wrong", msg, lambda d, s: Fake())  # type: ignore[arg-type,return-value]  # test double


def test_a_real_smtp_conversation_reaches_the_pinned_address() -> None:
    """A minimal SMTP server on loopback: the pinned client connects to the approved address
    while speaking to the server by name."""
    import socket
    import threading

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    got: list[bytes] = []

    def serve() -> None:
        conn, _ = srv.accept()
        f = conn.makefile("rwb")
        f.write(b"220 relay ready\r\n")
        f.flush()
        data = False
        for line in f:
            got.append(line)
            if data:
                if line == b".\r\n":
                    data = False
                    f.write(b"250 queued\r\n")
                    f.flush()
                continue
            cmd = line[:4].upper()
            if cmd == b"EHLO":
                f.write(b"250 relay\r\n")
            elif cmd == b"DATA":
                data = True
                f.write(b"354 go\r\n")
            elif cmd == b"QUIT":
                f.write(b"221 bye\r\n")
                f.flush()
                break
            else:
                f.write(b"250 ok\r\n")
            f.flush()
        conn.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    dest = Destination(f"smtp://relay.local:{port}", "smtp", "relay.local", port, "127.0.0.1", True)
    msg = message("siem@example.net", ["soc@example.net"], "[X] Test", "hello", "<p>hello</p>")
    send_mail(dest, "none", None, None, msg)
    t.join(5)
    srv.close()
    text = b"".join(got)
    assert b"rcpt to:<soc@example.net>" in text.lower()
    assert b"Subject: [X] Test" in text
