"""Opt-in redaction for cloud providers (ADR-0010 as reviewed, D36).

Off unless an admin turns it on for a provider. When on, for `ask`, `explain`, and `report`
calls to a cloud provider, every message the model would see (not the prompt) is rewritten:

- Values in identifying columns become tokens: IP columns as `IP_`, `actor_user_name` as
  `USER_`, host name columns as `HOST_`, wherever those columns appear in a data payload
  (event objects, sample values, preview rows with a `columns` header).
- In all text (raw lines, messages, questions, earlier SQL), IPv4 and IPv6 addresses and
  email addresses become tokens, and every user and host name taken from a column above is
  replaced too (whole word, ignoring case), so the raw line does not give back what the
  column hid.

A token is the kind plus 8 hex characters of HMAC-SHA256 over the kind and the normalized
value, keyed with a key derived from the install key: the same value always gets the same
token, so the model can still group and correlate. The reverse map lives in this object for
one call only and is applied to the reply (text and tool arguments) before anything else
reads it. It is never stored or logged. Stored logs are never changed.

Parser drafting is not redacted: a parser has to be written against the real line shape,
and its sample lines are chosen by an administrator.
"""

import hashlib
import hmac
import ipaddress
import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import replace
from typing import Any

from app.llm.provider import ChatMessage, ProviderResponse, ToolCall

PURPOSES = frozenset({"ask", "explain", "report"})
COLUMN_KINDS: dict[str, str] = {
    "src_endpoint_ip": "IP",
    "dst_endpoint_ip": "IP",
    "device_ip": "IP",
    "actor_user_name": "USER",
    "device_hostname": "HOST",
    "src_endpoint_hostname": "HOST",
    "dst_endpoint_hostname": "HOST",
}
MIN_NAME = 3  # shorter names are not hunted for in free text (they match too much)

_IPV4 = re.compile(
    r"(?<![\w.])(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?![\w.])"
)
_IPV6 = re.compile(r"(?<![\w:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:])")
_EMAIL = re.compile(
    r"(?<![\w.+-])[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,}(?![\w-])"
)
_TOKEN = re.compile(r"\b(IP|USER|HOST)_[0-9a-f]{8}\b")


def derive_key(install_key: bytes) -> bytes:
    """The redaction key: separate from the encryption key, stable for the install."""
    return hmac.new(install_key, b"redaction-v1", hashlib.sha256).digest()


class Redactor:
    def __init__(self, key: bytes) -> None:
        self._key = key
        self._reverse: dict[str, str] = {}
        self._names: dict[str, str] = {}  # lower-cased user or host name -> token
        self.counts: Counter[str] = Counter()

    # --- tokens -------------------------------------------------------------------------

    def token(self, kind: str, value: str) -> str:
        norm = _normalize(kind, value)
        digest = hmac.new(self._key, f"{kind}\0{norm}".encode(), hashlib.sha256).hexdigest()
        token = f"{kind}_{digest[:8]}"
        if token not in self._reverse:
            self._reverse[token] = value
            self.counts[kind] += 1
        return token

    # --- messages -----------------------------------------------------------------------

    def messages(self, messages: Iterable[ChatMessage]) -> list[ChatMessage]:
        """Every message the model would see, rewritten; system messages are left alone."""
        msgs = list(messages)
        for m in msgs:  # first learn the names in columns, so text anywhere can hide them
            data = _data(m)
            if data is not None:
                self._learn(data)
        out = []
        for m in msgs:
            if m.role == "system":
                out.append(m)
                continue
            data = _data(m)
            content = (
                json.dumps({"data": self._value(data)}, default=str)
                if data is not None
                else self.text(m.content)
            )
            calls = tuple(replace(c, arguments=self.text(c.arguments)) for c in m.tool_calls)
            out.append(replace(m, content=content, tool_calls=calls))
        return out

    def restore(self, response: ProviderResponse) -> ProviderResponse:
        """The reply with tokens put back, before anything validates or runs it."""
        return replace(
            response,
            text=self.unmask(response.text),
            tool_calls=[
                ToolCall(c.call_id, c.name, self.unmask(c.arguments)) for c in response.tool_calls
            ],
        )

    def unmask(self, text: str) -> str:
        return _TOKEN.sub(lambda m: self._reverse.get(m.group(0), m.group(0)), text)

    # --- walking data ---------------------------------------------------------------------

    def _learn(self, value: Any, key: str | None = None) -> None:
        kind = COLUMN_KINDS.get(key or "")
        if kind in ("USER", "HOST"):
            for v in value if isinstance(value, list) else [value]:
                if isinstance(v, str) and len(v.strip()) >= MIN_NAME:
                    self._names[v.strip().lower()] = self.token(kind, v.strip())
            return
        if isinstance(value, dict):
            for row_kinds, rows in _table(value):
                for row in rows:
                    for kind_i, cell in zip(row_kinds, row, strict=False):
                        if kind_i in ("USER", "HOST") and isinstance(cell, str):
                            if len(cell.strip()) >= MIN_NAME:
                                self._names[cell.strip().lower()] = self.token(kind_i, cell.strip())
            for k, v in value.items():
                self._learn(v, str(k))
        elif isinstance(value, list):
            for v in value:
                self._learn(v)

    def _value(self, value: Any, key: str | None = None) -> Any:
        kind = COLUMN_KINDS.get(key or "")
        if kind is not None:
            if isinstance(value, str) and value:
                return self.token(kind, value)
            if isinstance(value, list):
                return [self.token(kind, v) if isinstance(v, str) and v else v for v in value]
        if isinstance(value, dict):
            tables = _table(value)
            out = {str(k): self._value(v, str(k)) for k, v in value.items()}
            for row_kinds, _rows in tables:
                out["rows"] = [
                    [
                        self.token(k, c) if k and isinstance(c, str) and c else self._value(c)
                        for k, c in zip(row_kinds, row, strict=False)
                    ]
                    for row in value["rows"]
                ]
            return out
        if isinstance(value, list):
            return [self._value(v) for v in value]
        if isinstance(value, str):
            return self.text(value)
        return value

    # --- free text ------------------------------------------------------------------------

    def text(self, text: str) -> str:
        if not text:
            return text
        text = _EMAIL.sub(lambda m: self.token("USER", m.group(0)), text)
        text = _IPV4.sub(lambda m: self.token("IP", m.group(0)), text)
        text = _IPV6.sub(self._ipv6, text)
        if self._names:
            names = sorted(self._names, key=len, reverse=True)
            pattern = re.compile(
                r"(?<![\w.-])(?:" + "|".join(re.escape(n) for n in names) + r")(?![\w-])",
                re.IGNORECASE,
            )
            text = pattern.sub(lambda m: self._names[m.group(0).lower()], text)
        return text

    def _ipv6(self, m: re.Match[str]) -> str:
        try:
            ipaddress.IPv6Address(m.group(0))
        except ValueError:
            return m.group(0)  # a time like 12:30:01 or other colon text
        return self.token("IP", m.group(0))


def _data(m: ChatMessage) -> Any:
    """The payload under "data" for a data message, else None."""
    if m.data_sources is None:
        return None
    try:
        parsed = json.loads(m.content)
    except ValueError:
        return None
    return parsed.get("data") if isinstance(parsed, dict) else None


def _table(value: dict[str, Any]) -> list[tuple[list[str | None], list[list[Any]]]]:
    """A {"columns": [...], "rows": [[...]]} shape: each row cell's kind by column."""
    cols, rows = value.get("columns"), value.get("rows")
    if not (isinstance(cols, list) and isinstance(rows, list)):
        return []
    if not all(isinstance(r, list) for r in rows):
        return []
    return [([COLUMN_KINDS.get(str(c)) for c in cols], rows)]


def _normalize(kind: str, value: str) -> str:
    v = value.strip()
    if kind == "IP":
        try:
            return str(ipaddress.ip_address(v))
        except ValueError:
            return v.lower()
    return v.lower()
