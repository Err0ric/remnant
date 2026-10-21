"""Anthropic Messages API adapter (SPEC 6.1). Always a cloud provider.

Imported only by llm/gate.py (CLAUDE.md rule 2). The internal chat format (OpenAI style:
system, user, assistant with tool calls, tool results) is translated to Messages API
blocks here: system turns go to the top-level `system` field, an assistant tool request
becomes `tool_use` blocks, and tool results become `tool_result` blocks in a user turn.
Responses are untrusted: size-capped by the shared HTTP client and checked for shape.
"""

import json
from typing import Any

import httpx

from app.core.errors import ProviderError
from app.llm.provider import ChatMessage, Locality, ProviderResponse, ToolCall
from app.llm.provider_http import PinnedJsonClient

API_VERSION = "2023-06-01"
DEFAULT_BASE_URL = "https://api.anthropic.com/v1"


class AnthropicProvider:
    locality: Locality = "cloud"

    def __init__(
        self,
        provider_id: str,
        base_url: str,
        model: str,
        api_key: str | None,
        transport: httpx.BaseTransport | None = None,
        pin: str | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.locality = "cloud"  # whatever the URL resolves to (SPEC 6.1)
        self.model = model
        headers = {"anthropic-version": API_VERSION}
        if api_key:
            headers["x-api-key"] = api_key
        self._http = PinnedJsonClient(base_url, headers, "cloud", transport, pin)

    def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        json_mode: bool = False,  # no JSON mode; the gate extracts and validates JSON
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> ProviderResponse:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": _messages([m for m in messages if m.role != "system"]),
        }
        if system:
            body["system"] = system
        if tools:
            body["tools"] = [_tool(t) for t in tools]
        data = self._http.request("POST", "/messages", body)
        try:
            blocks = data["content"]
            if not isinstance(blocks, list):
                raise TypeError("content")
            text = "".join(str(b["text"]) for b in blocks if b.get("type") == "text")
            calls = [
                ToolCall(
                    call_id=str(b["id"]),
                    name=str(b["name"]),
                    arguments=json.dumps(b.get("input") or {}),
                )
                for b in blocks
                if b.get("type") == "tool_use"
            ]
            usage = data.get("usage") or {}
            return ProviderResponse(
                text=text,
                model=str(data.get("model", self.model)),
                tool_calls=calls,
                prompt_tokens=_int(usage.get("input_tokens")),
                completion_tokens=_int(usage.get("output_tokens")),
                truncated=data.get("stop_reason") == "max_tokens",
            )
        except (KeyError, TypeError, AttributeError) as exc:
            raise ProviderError("Provider response did not match the Messages format") from exc

    def models(self) -> list[str]:
        data = self._http.request("GET", "/models?limit=100")
        try:
            return sorted(str(m["id"]) for m in data["data"])
        except (KeyError, TypeError) as exc:
            raise ProviderError("Provider model list did not match the expected format") from exc


def _tool(spec: dict[str, Any]) -> dict[str, Any]:
    """OpenAI-style function tool to a Messages API tool."""
    fn = spec.get("function", spec)
    return {
        "name": fn["name"],
        "description": fn.get("description", ""),
        "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
    }


def _messages(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    """Messages API turns. Consecutive turns of the same role are merged into one, so tool
    results that answer several tool requests arrive together, as the API expects."""
    out: list[dict[str, Any]] = []
    for m in messages:
        role = "assistant" if m.role == "assistant" else "user"
        blocks: list[dict[str, Any]] = []
        if m.role == "tool":
            blocks.append(
                {"type": "tool_result", "tool_use_id": m.tool_call_id or "", "content": m.content}
            )
        else:
            if m.content:
                blocks.append({"type": "text", "text": m.content})
            for c in m.tool_calls:
                try:
                    args = json.loads(c.arguments or "{}")
                except ValueError:
                    args = {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": c.call_id,
                        "name": c.name,
                        "input": args if isinstance(args, dict) else {},
                    }
                )
        if not blocks:
            continue
        if out and out[-1]["role"] == role:
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": blocks})
    return out


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
