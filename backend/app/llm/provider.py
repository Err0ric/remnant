"""Model provider protocol (SPEC 6.1). Only llm/gate.py constructs or calls providers."""

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Locality = Literal["local", "cloud"]
Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    name: str
    arguments: str  # raw JSON text; validated by the caller, never executed as code


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: str
    name: str | None = None  # tool name for role="tool"
    tool_call_id: str | None = None
    # Sources whose event data this message carries; None means it carries none. The gate
    # adds them to the scope it checks, so data cannot reach a provider under a narrower
    # scope than it came from. Tool results must always declare (possibly empty).
    data_sources: tuple[str, ...] | None = None
    tool_calls: tuple[ToolCall, ...] = ()  # an assistant turn that asked for tools


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    text: str
    model: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    truncated: bool = False  # the provider stopped at the output limit


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    ok: bool
    detail: str
    models: list[str] = field(default_factory=list)
    busy: bool = False  # occupied with a request, not down (ADR-0028 row 7)


class Provider(Protocol):
    provider_id: str
    locality: Locality

    def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        json_mode: bool = False,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> ProviderResponse: ...

    def models(self) -> list[str]: ...
