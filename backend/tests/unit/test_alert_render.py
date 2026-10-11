"""Alert messages: summary only, names escaped for each format (ADR-0007 rows 2, 5, 7)."""

import hashlib
import hmac
import json
from dataclasses import replace

from app.alerts.render import Alert, email_parts, signed_webhook, slack_payload, teams_payload

HOSTILE = "<!channel> [click](https://evil.example) *bold* <script>x</script> & co"
ALERT = Alert(
    kind="match",
    title=HOSTILE,
    detail="Rule by Jane Doe",
    count=6,
    reason="6 is above 5",
    range_start="2026-10-10T12:00:00+00:00",
    range_end="2026-10-10T13:00:00+00:00",
    link="https://siem.example.internal/schedules",
    product="Codename",
)


def test_slack_text_cannot_mention_or_link() -> None:
    """mrkdwn (the top-level text and the link block) is escaped; names only ever sit in
    plain_text blocks, which Slack shows literally."""
    doc = slack_payload(ALERT)
    assert "<!channel>" not in doc["text"] and "&lt;!channel&gt;" in doc["text"]
    for block in doc["blocks"]:
        if block["text"]["type"] == "mrkdwn":
            assert (
                "<!channel>" not in block["text"]["text"] and HOSTILE not in block["text"]["text"]
            )
        else:
            assert block["text"]["type"] == "plain_text"


def test_teams_card_escapes_markdown_links() -> None:
    body = json.dumps(teams_payload(ALERT))
    assert "[click](https://evil.example)" not in body
    assert body.count("application/vnd.microsoft.card.adaptive") == 1


def test_email_html_is_escaped_and_text_has_the_link() -> None:
    subject, text, html = email_parts(ALERT)
    assert subject.startswith("[Codename] ") and "\n" not in subject
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "https://siem.example.internal/schedules" in text


def test_webhook_is_signed_over_timestamp_and_body() -> None:
    body, headers = signed_webhook(ALERT, secret="s3cret", now=1_760_000_000)
    expected = hmac.new(b"s3cret", b"1760000000." + body, hashlib.sha256).hexdigest()
    assert headers["X-Signature-256"] == f"sha256={expected}"
    assert headers["X-Signature-Timestamp"] == "1760000000"
    doc = json.loads(body)
    assert doc["schema"] == "alert.v1" and doc["count"] == 6 and "events" not in doc


def test_newlines_cannot_add_email_headers() -> None:
    a = replace(ALERT, title="x\r\nBcc: someone@example.net")
    subject, _, _ = email_parts(a)
    assert "\r" not in subject and "\n" not in subject
