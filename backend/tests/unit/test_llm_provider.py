"""OpenAI-compatible adapter against a fake server: parsing, limits, no redirects, auth header."""

import json

import httpx
import pytest

from app.core.errors import ProviderError
from app.llm.provider import ChatMessage, ToolCall
from app.llm.provider_http import MAX_RESPONSE_BYTES
from app.llm.providers.openai_compat import OpenAICompatibleProvider


def provider(handler, api_key: str | None = None) -> OpenAICompatibleProvider:  # type: ignore[no-untyped-def]  # test helper
    return OpenAICompatibleProvider(
        provider_id="p1",
        base_url="http://127.0.0.1:11434/v1",
        model="llama3.1:8b",
        api_key=api_key,
        locality="local",
        transport=httpx.MockTransport(handler),
    )


def completion(content: str, **extra: object) -> dict[str, object]:
    return {
        "model": "llama3.1:8b",
        "choices": [
            {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 7},
        **extra,
    }


def test_chat_round_trip_and_auth_header() -> None:
    seen: dict[str, object] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["auth"] = req.headers.get("authorization")
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json=completion('{"sql": "SELECT 1"}'))

    res = provider(handler, api_key="sk-test").chat(
        [ChatMessage("system", "be brief"), ChatMessage("user", "hi")],
        temperature=0.0,
        max_tokens=50,
    )
    assert res.text == '{"sql": "SELECT 1"}'
    assert (res.prompt_tokens, res.completion_tokens) == (12, 7)
    assert seen["url"] == "http://127.0.0.1:11434/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-test"
    body = seen["body"]
    assert isinstance(body, dict) and body["model"] == "llama3.1:8b" and body["temperature"] == 0.0


def test_no_auth_header_without_key() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert "authorization" not in req.headers
        return httpx.Response(200, json=completion("ok"))

    provider(handler).chat([ChatMessage("user", "hi")])


def test_oversized_response_rejected() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=completion("x" * (MAX_RESPONSE_BYTES + 10)))

    with pytest.raises(ProviderError, match="too large"):
        provider(handler).chat([ChatMessage("user", "hi")])


def test_redirects_are_not_followed() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302, headers={"Location": "https://cloud.example/v1/chat/completions"}
        )

    with pytest.raises(ProviderError, match="302"):
        provider(handler).chat([ChatMessage("user", "hi")])


@pytest.mark.parametrize(
    "payload",
    [b"not json", b'{"choices": []}', b'{"choices": [{"message": {"content": 5}}]}'],
)
def test_malformed_responses_rejected(payload: bytes) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    with pytest.raises(ProviderError):
        provider(handler).chat([ChatMessage("user", "hi")])


def test_http_errors_do_not_leak_keys() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key sk-test"})

    with pytest.raises(ProviderError) as info:
        provider(handler, api_key="sk-test").chat([ChatMessage("user", "hi")])
    assert "sk-test" not in str(info.value)


def test_models_listing() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/models"
        return httpx.Response(
            200, json={"data": [{"id": "llama3.1:8b"}, {"id": "qwen2.5-coder:7b"}]}
        )

    assert provider(handler).models() == ["llama3.1:8b", "qwen2.5-coder:7b"]


@pytest.mark.parametrize(
    ("base", "pin", "url", "host", "sni"),
    [
        (
            "http://models.lan:11434/v1",
            "10.0.0.5",
            "http://10.0.0.5:11434/v1/models",
            "models.lan:11434",
            None,
        ),
        ("https://gpu.corp/v1", "fd00::7", "https://[fd00::7]/v1/models", "gpu.corp", "gpu.corp"),
    ],
)
def test_pinned_address_is_used_with_original_host_and_tls_name(
    base: str, pin: str, url: str, host: str, sni: str | None
) -> None:
    seen: dict[str, object] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["host"] = req.headers.get("host")
        seen["sni"] = req.extensions.get("sni_hostname")
        return httpx.Response(200, json={"data": [{"id": "m"}]})

    p = OpenAICompatibleProvider(
        provider_id="p1",
        base_url=base,
        model="m",
        api_key=None,
        locality="local",
        transport=httpx.MockTransport(handler),
        pin=pin,
    )
    assert p.models() == ["m"]
    assert seen == {"url": url, "host": host, "sni": sni}


def test_local_calls_ignore_proxy_settings_cloud_calls_keep_them() -> None:
    def make(locality: str) -> OpenAICompatibleProvider:
        return OpenAICompatibleProvider("p", "http://10.0.0.5/v1", "m", None, locality)  # type: ignore[arg-type]  # literal

    assert make("local")._http._client().trust_env is False
    assert make("cloud")._http._client().trust_env is True


def test_pinned_host_header_never_carries_credentials() -> None:
    p = OpenAICompatibleProvider(
        "p", "http://u:pw@llm.lan:8080/v1", "m", None, "local", pin="10.0.0.5"
    )
    url, headers, _ = p._http._target("/models")
    assert url == "http://10.0.0.5:8080/v1/models"
    assert headers == {"Host": "llm.lan:8080"}


def test_tool_call_turns_round_trip_and_object_arguments_are_json() -> None:
    seen: dict[str, object] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(req.content)
        msg = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c2",
                    "function": {"name": "preview_query", "arguments": {"sql": "SELECT 1"}},
                }
            ],
        }
        return httpx.Response(200, json={"model": "m", "choices": [{"message": msg}]})

    asked = ChatMessage("assistant", "", tool_calls=(ToolCall("c1", "get_schema", "{}"),))
    res = provider(handler).chat(
        [ChatMessage("user", "q"), asked, ChatMessage("tool", "{}", tool_call_id="c1")]
    )
    assert res.tool_calls[0].arguments == '{"sql": "SELECT 1"}'  # Ollama sends an object
    body = seen["body"]
    assert isinstance(body, dict)
    sent = body["messages"][1]
    assert sent["content"] is None
    assert sent["tool_calls"] == [
        {"id": "c1", "type": "function", "function": {"name": "get_schema", "arguments": "{}"}}
    ]
    assert body["messages"][2]["tool_call_id"] == "c1"


def test_output_limit_is_reported_and_reasoning_text_is_not_the_answer() -> None:
    """Ollama returns thinking in `reasoning`; only `content` is the answer."""

    def handler(req: httpx.Request) -> httpx.Response:
        msg = {"role": "assistant", "content": "", "reasoning": '{"sql": "SELECT 9"}'}
        return httpx.Response(
            200, json={"model": "m", "choices": [{"message": msg, "finish_reason": "length"}]}
        )

    res = provider(handler).chat([ChatMessage("user", "hi")])
    assert res.text == "" and res.truncated is True


def test_a_finished_answer_is_not_marked_truncated() -> None:
    res = provider(lambda req: httpx.Response(200, json=completion("ok"))).chat(
        [ChatMessage("user", "hi")]
    )
    assert res.truncated is False


def test_reasoning_effort_is_sent_only_when_set() -> None:
    seen: list[dict[str, object]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return httpx.Response(200, json=completion("ok"))

    provider(handler).chat([ChatMessage("user", "hi")])
    assert "reasoning_effort" not in seen[-1]
    off = OpenAICompatibleProvider(
        "p1",
        "http://127.0.0.1:11434/v1",
        "qwen",
        None,
        "local",
        transport=httpx.MockTransport(handler),
        reasoning="none",
    )
    off.chat([ChatMessage("user", "hi")])
    assert seen[-1]["reasoning_effort"] == "none"
