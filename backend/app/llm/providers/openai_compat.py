"""OpenAI-compatible chat adapter: Ollama, LM Studio, llama.cpp, vLLM, OpenAI, and others.

Imported only by llm/gate.py (CLAUDE.md rule 2). Responses are untrusted: size-capped,
schema-checked, never executed. Redirects are refused so a local URL cannot bounce a
request to a cloud host. API keys never appear in errors or logs.
"""

import json
from typing import Any

import httpx

from app.core.errors import ProviderError
from app.llm.provider import ChatMessage, Locality, ProviderResponse, ToolCall
from app.llm.provider_http import PinnedJsonClient


class OpenAICompatibleProvider:
    def __init__(
        self,
        provider_id: str,
        base_url: str,
        model: str,
        api_key: str | None,
        locality: Locality,
        transport: httpx.BaseTransport | None = None,
        pin: str | None = None,
        reasoning: str | None = None,
    ) -> None:
        self.provider_id = provider_id
        # Sent as reasoning_effort only when set: servers and models without it may refuse
        # the field. "none" turns thinking off on Ollama's OpenAI endpoint.
        self._reasoning = reasoning
        self.locality: Locality = locality
        self.model = model
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = PinnedJsonClient(base_url, headers, locality, transport, pin)

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        return self._http.request(method, path, body)

    def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        json_mode: bool = False,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> ProviderResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [_message(m) for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if self._reasoning:
            body["reasoning_effort"] = self._reasoning
        if tools:
            body["tools"] = tools
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        data = self._request("POST", "/chat/completions", body)
        try:
            first = data["choices"][0]
            choice = first["message"]
            content = choice.get("content") or ""
            if not isinstance(content, str):
                raise TypeError("content")
            calls = [
                ToolCall(
                    call_id=str(c.get("id", "")),
                    name=str(c["function"]["name"]),
                    arguments=_arguments(c["function"].get("arguments")),
                )
                for c in choice.get("tool_calls") or []
            ]
            usage = data.get("usage") or {}
            return ProviderResponse(
                text=content,
                model=str(data.get("model", self.model)),
                tool_calls=calls,
                prompt_tokens=_int(usage.get("prompt_tokens")),
                completion_tokens=_int(usage.get("completion_tokens")),
                truncated=first.get("finish_reason") == "length",
            )
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise ProviderError("Provider response did not match the chat format") from exc

    def models(self) -> list[str]:
        data = self._request("GET", "/models")
        try:
            return sorted(str(m["id"]) for m in data["data"])
        except (KeyError, TypeError) as exc:
            raise ProviderError("Provider model list did not match the expected format") from exc


def _message(m: ChatMessage) -> dict[str, Any]:
    out: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_calls:
        out["content"] = m.content or None
        out["tool_calls"] = [
            {
                "id": c.call_id,
                "type": "function",
                "function": {"name": c.name, "arguments": c.arguments},
            }
            for c in m.tool_calls
        ]
    if m.name:
        out["name"] = m.name
    if m.tool_call_id:
        out["tool_call_id"] = m.tool_call_id
    return out


def _arguments(value: object) -> str:
    """JSON text of tool arguments. Ollama sends an object where OpenAI sends a string."""
    if value is None:
        return "{}"
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
