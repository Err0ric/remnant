"""Anthropic Messages adapter against a fake server: request shape, tool turns, parsing."""

import json

import httpx
import pytest

from app.core.errors import ProviderError
from app.llm.provider import ChatMessage, ToolCall
from app.llm.providers.anthropic import API_VERSION, AnthropicProvider

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "preview_query",
            "description": "Run SQL, 5 rows",
            "parameters": {"type": "object", "properties": {"sql": {"type": "string"}}},
        },
    }
]


def provider(handler, api_key: str | None = "sk-ant-test") -> AnthropicProvider:  # type: ignore[no-untyped-def]  # test helper
    return AnthropicProvider(
        "a1",
        "https://api.anthropic.com/v1",
        "claude-test",
        api_key,
        transport=httpx.MockTransport(handler),
    )


def reply(*blocks: dict[str, object], stop: str = "end_turn") -> dict[str, object]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-test",
        "content": list(blocks),
        "stop_reason": stop,
        "usage": {"input_tokens": 40, "output_tokens": 9},
    }


def test_request_shape_headers_and_text_reply() -> None:
    seen: dict[str, object] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["headers"] = dict(req.headers)
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json=reply({"type": "text", "text": '{"sql": "SELECT 1"}'}))

    p = provider(handler)
    assert p.locality == "cloud"
    res = p.chat([ChatMessage("system", "rules"), ChatMessage("user", "hi")], max_tokens=50)
    assert res.text == '{"sql": "SELECT 1"}'
    assert (res.prompt_tokens, res.completion_tokens, res.truncated) == (40, 9, False)
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    headers = seen["headers"]
    assert isinstance(headers, dict)
    assert headers["x-api-key"] == "sk-ant-test" and headers["anthropic-version"] == API_VERSION
    assert "authorization" not in headers
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["system"] == "rules" and body["max_tokens"] == 50
    assert body["messages"] == [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]


def test_tool_turns_are_translated_and_tool_results_grouped() -> None:
    seen: dict[str, object] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(req.content)
        return httpx.Response(
            200,
            json=reply(
                {"type": "text", "text": "checking"},
                {"type": "tool_use", "id": "tu_2", "name": "preview_query", "input": {"sql": "x"}},
                stop="tool_use",
            ),
        )

    history = [
        ChatMessage("user", "q"),
        ChatMessage(
            "assistant",
            "",
            tool_calls=(
                ToolCall("tu_1", "get_schema", "{}"),
                ToolCall("tu_0", "preview_query", '{"sql": "SELECT 1"}'),
            ),
        ),
        ChatMessage("tool", "schema", tool_call_id="tu_1", data_sources=()),
        ChatMessage("tool", "rows", tool_call_id="tu_0", data_sources=()),
    ]
    res = provider(handler).chat(history, tools=TOOLS)
    assert res.text == "checking"
    assert res.tool_calls == [ToolCall("tu_2", "preview_query", '{"sql": "x"}')]
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["tools"] == [
        {
            "name": "preview_query",
            "description": "Run SQL, 5 rows",
            "input_schema": {"type": "object", "properties": {"sql": {"type": "string"}}},
        }
    ]
    msgs = body["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[1]["content"] == [
        {"type": "tool_use", "id": "tu_1", "name": "get_schema", "input": {}},
        {"type": "tool_use", "id": "tu_0", "name": "preview_query", "input": {"sql": "SELECT 1"}},
    ]
    assert msgs[2]["content"] == [
        {"type": "tool_result", "tool_use_id": "tu_1", "content": "schema"},
        {"type": "tool_result", "tool_use_id": "tu_0", "content": "rows"},
    ]


def test_cut_off_replies_are_marked_truncated() -> None:
    res = provider(
        lambda req: httpx.Response(
            200, json=reply({"type": "text", "text": "{"}, stop="max_tokens")
        )
    ).chat([ChatMessage("user", "q")])
    assert res.truncated is True


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, json={"type": "error", "error": {"message": "bad key sk-ant-test"}}),
        httpx.Response(200, json={"content": "not a list"}),
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, content=b"x" * (65 * 1024)),
        httpx.Response(302, headers={"Location": "http://evil.example/"}),
    ],
)
def test_bad_responses_are_errors_without_secrets(response: httpx.Response) -> None:
    with pytest.raises(ProviderError) as exc:
        provider(lambda req: response).chat([ChatMessage("user", "q")])
    assert "sk-ant" not in str(exc.value)


def test_models_list() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "claude-b"}, {"id": "claude-a"}]})

    assert provider(handler).models() == ["claude-a", "claude-b"]


def test_anthropic_kind_is_cloud_even_at_a_private_address() -> None:
    from app.llm.locality import provider_endpoint

    assert provider_endpoint("openai_compat", "https://10.0.0.5/v1", []).locality == "local"
    endpoint = provider_endpoint("anthropic", "https://10.0.0.5/v1", [])
    assert endpoint.locality == "cloud"
