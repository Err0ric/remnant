"""One alert, rendered for email, Slack, Teams, and webhooks (ADR-0007 rows 2, 5, 7).

Alerts are summaries: what fired, when, how many, why, and a link back. No event content.
Names come from saved searches and rule files, which other people wrote, so every format
escapes them: Slack cannot mention or link, Teams cannot link, email HTML cannot inject
markup, and the subject cannot carry extra headers.
"""

import hashlib
import hmac
import html
import json
import re
from dataclasses import dataclass
from typing import Any, Literal

AlertKind = Literal[
    "flag",
    "match",
    "pause",
    "test",
    "quiet",
    "resumed",
    "ai_new",
    "ai_sensitive",
    "ai_agent",
    "device_quiet",
    "device_resumed",
    "integrity_failed",
    "integrity_seal",
]
_LABEL = {
    "flag": "Flagged",
    "match": "Matches",
    "pause": "Paused",
    "test": "Test",
    "quiet": "Source quiet",
    "resumed": "Source resumed",
    "ai_new": "AI use not approved",
    "ai_sensitive": "Sensitive data to AI",
    "ai_agent": "AI agent changed",
    "device_quiet": "Device silent",
    "device_resumed": "Device seen again",
    "integrity_failed": "Log integrity check failed",
    "integrity_seal": "Daily integrity seal",
}


@dataclass(frozen=True, slots=True)
class Alert:
    kind: AlertKind
    title: str  # schedule name
    detail: str  # for example "Rule: <title> by <author>", or the pause reason
    count: int | None
    reason: str | None  # flag reason
    range_start: str | None
    range_end: str | None
    link: str | None
    product: str


def _one_line(text: str, limit: int = 200) -> str:
    return re.sub(r"[\x00-\x1f\x7f]+", " ", text).strip()[:limit]


def _summary(a: Alert) -> str:
    parts = [_LABEL[a.kind]]
    if a.count is not None:
        parts.append(
            f"{a.count} {'match' if a.count == 1 else 'matches'}"
            if a.kind == "match"
            else f"count {a.count}"
        )
    if a.reason:
        parts.append(_one_line(a.reason))
    return " · ".join(parts)


def _lines(a: Alert) -> list[str]:
    out = [_summary(a), _one_line(a.detail, 300)]
    if a.range_start and a.range_end:
        out.append(f"Range: {a.range_start} to {a.range_end}")
    return [line for line in out if line]


def _slack(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def slack_payload(a: Alert) -> dict[str, Any]:
    title = _slack(_one_line(a.title))
    body = "\n".join(_slack(line) for line in _lines(a))
    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {"type": "plain_text", "text": f"{a.product}: {_one_line(a.title)}"[:150]},
        },
        {"type": "section", "text": {"type": "plain_text", "text": "\n".join(_lines(a))[:2900]}},
    ]
    if a.link:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"<{_slack(a.link)}|Open in {_slack(a.product)}>",
                },
            }
        )
    return {"text": f"{_slack(a.product)}: {title}\n{body}"[:3000], "blocks": blocks}


_MD = re.compile(r"([\\`*_\[\]()#+!|<>~-])")


def _md(text: str) -> str:
    return _MD.sub(r"\\\1", text)


def teams_payload(a: Alert) -> dict[str, Any]:
    body: list[dict[str, Any]] = [
        {
            "type": "TextBlock",
            "text": _md(f"{a.product}: {_one_line(a.title)}"),
            "weight": "Bolder",
            "wrap": True,
        },
        *({"type": "TextBlock", "text": _md(line), "wrap": True} for line in _lines(a)),
    ]
    card: dict[str, Any] = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": body,
    }
    if a.link:
        card["actions"] = [
            {"type": "Action.OpenUrl", "title": f"Open in {a.product}", "url": a.link}
        ]
    return {
        "type": "message",
        "attachments": [
            {"contentType": "application/vnd.microsoft.card.adaptive", "content": card}
        ],
    }


def email_parts(a: Alert) -> tuple[str, str, str]:
    """(subject, text body, HTML body)."""
    subject = _one_line(
        f"[{a.product}] {_LABEL[a.kind]}: {a.title}"
        + (f": {a.count}" if a.count is not None else ""),
        200,
    )
    lines = [_one_line(a.title, 300), *_lines(a)]
    if a.link:
        lines.append(f"Open: {a.link}")
    text = "\n".join(lines) + "\n"
    items = "".join(f"<p>{html.escape(line)}</p>" for line in _lines(a))
    link = (
        f'<p><a href="{html.escape(a.link, quote=True)}">Open in {html.escape(a.product)}</a></p>'
        if a.link
        else ""
    )
    body = f"<h3>{html.escape(_one_line(a.title, 300))}</h3>{items}{link}"
    return subject, text, body


def webhook_body(a: Alert) -> bytes:
    doc = {
        "schema": "alert.v1",
        "product": a.product,
        "kind": a.kind,
        "title": a.title,
        "detail": a.detail,
        "count": a.count,
        "reason": a.reason,
        "range_start": a.range_start,
        "range_end": a.range_end,
        "link": a.link,
    }
    return json.dumps(doc, separators=(",", ":"), sort_keys=True).encode()


def signed_webhook(a: Alert, secret: str, now: int) -> tuple[bytes, dict[str, str]]:
    """Body and headers; the signature covers `<timestamp>.<body>` so it cannot be replayed
    with a different time."""
    body = webhook_body(a)
    mac = hmac.new(secret.encode(), str(now).encode() + b"." + body, hashlib.sha256).hexdigest()
    return body, {
        "Content-Type": "application/json",
        "X-Signature-256": f"sha256={mac}",
        "X-Signature-Timestamp": str(now),
    }
