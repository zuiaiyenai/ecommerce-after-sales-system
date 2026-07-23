from __future__ import annotations

from copy import deepcopy
import json
import threading

import httpx
import pytest

from after_sales_agent.providers.resilient_llm_runtime import (
    FallbackLLMClient,
    LLMAuthenticationError,
    LLMConcurrencyLimitError,
    LLMInvalidRequestError,
    OllamaHTTPClient,
    OpenAICompatibleHTTPClient,
    ProviderConfig,
)


def config(**overrides):
    values = dict(provider="remote", base_url="https://llm.test", api_key="secret", model="test-model", connect_timeout=1, read_timeout=1, write_timeout=1, pool_timeout=1, total_timeout=2, max_concurrent=2, max_queue_wait=0.02, max_connections=4, max_keepalive_connections=2, keepalive_expiry=30, max_retries=1, retry_base_delay=0, retry_max_delay=0, circuit_failure_threshold=2, circuit_recovery_seconds=0.01)
    values.update(overrides)
    return ProviderConfig(**values)


def test_openai_protocol_and_client_reuse():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    transport = httpx.MockTransport(handler)
    pooled = httpx.Client(transport=transport, base_url="https://llm.test")
    client = OpenAICompatibleHTTPClient(config(), pooled)
    assert client.chat([{"role": "user", "content": "one"}])["choices"][0]["message"]["content"] == "ok"
    client.chat([{"role": "user", "content": "two"}])
    assert len(requests) == 2
    assert requests[0].url.path == "/v1/chat/completions"
    assert json.loads(requests[0].content)["model"] == "test-model"


def test_openai_request_preserves_caller_tools_and_required_tool_choice():
    captured = []
    tools = [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}]

    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = OpenAICompatibleHTTPClient(config(), httpx.Client(transport=httpx.MockTransport(handler), base_url="https://llm.test"))
    client.chat([{"role": "user", "content": "one"}], tools=tools, tool_choice="required")

    assert captured[0]["tools"] == tools
    assert captured[0]["tool_choice"] == "required"


def test_ollama_request_preserves_tools_and_option_mapping():
    captured = []
    tools = [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}]

    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "ok"}})

    client = OllamaHTTPClient(
        config(provider="ollama"),
        httpx.Client(transport=httpx.MockTransport(handler), base_url="https://llm.test"),
    )
    client.chat([{"role": "user", "content": "one"}], tools=tools, temperature=0.35, max_tokens=321)

    assert captured[0]["tools"] == tools
    assert captured[0]["options"] == {"temperature": 0.35, "num_predict": 321}


def canonical_tool_history():
    return [
        {"role": "system", "content": "system"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": "lookup",
                    "arguments": {"keyword": "A100"},
                },
            }],
        },
        {
            "role": "tool",
            "tool_call_id": "call-1",
            "name": "lookup",
            "content": '{"ok":true}',
        },
        {"role": "user", "content": "continue"},
    ]


def test_openai_history_is_rerendered_for_ollama_fallback_without_mutating_input():
    primary_requests = []
    fallback_requests = []

    def primary_handler(request):
        primary_requests.append(json.loads(request.content))
        return httpx.Response(503, json={"error": "unavailable"})

    def fallback_handler(request):
        fallback_requests.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "ok"}})

    primary = OpenAICompatibleHTTPClient(
        config(provider="openai", max_retries=0),
        httpx.Client(transport=httpx.MockTransport(primary_handler), base_url="https://llm.test"),
    )
    fallback = OllamaHTTPClient(
        config(provider="ollama", max_retries=0),
        httpx.Client(transport=httpx.MockTransport(fallback_handler), base_url="https://llm.test"),
    )
    client = FallbackLLMClient(primary, fallback)
    messages = canonical_tool_history()
    original = deepcopy(messages)

    response = client.chat(messages)

    assert response["message"]["content"] == "ok"
    assert messages == original
    openai_call = primary_requests[0]["messages"][1]["tool_calls"][0]
    assert openai_call["id"] == "call-1"
    assert openai_call["type"] == "function"
    assert json.loads(openai_call["function"]["arguments"]) == {"keyword": "A100"}
    assert primary_requests[0]["messages"][2] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "name": "lookup",
        "content": '{"ok":true}',
    }
    ollama_call = fallback_requests[0]["messages"][1]["tool_calls"][0]
    assert "id" not in ollama_call
    assert "type" not in ollama_call
    assert ollama_call["function"] == {
        "name": "lookup",
        "arguments": {"keyword": "A100"},
    }
    assert fallback_requests[0]["messages"][2] == {
        "role": "tool",
        "content": '{"ok":true}',
    }
    assert fallback_requests[0]["messages"][0] == original[0]
    assert fallback_requests[0]["messages"][3] == original[3]


def test_ollama_canonical_history_is_rerendered_for_openai():
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = OpenAICompatibleHTTPClient(
        config(provider="openai"),
        httpx.Client(transport=httpx.MockTransport(handler), base_url="https://llm.test"),
    )
    messages = canonical_tool_history()
    original = deepcopy(messages)

    client.chat(messages)

    rendered = captured[0]["messages"]
    assert json.loads(rendered[1]["tool_calls"][0]["function"]["arguments"]) == {
        "keyword": "A100",
    }
    assert rendered[1]["tool_calls"][0]["id"] == "call-1"
    assert rendered[1]["tool_calls"][0]["type"] == "function"
    assert rendered[2]["tool_call_id"] == "call-1"
    assert rendered[2]["name"] == "lookup"
    assert messages == original


@pytest.mark.parametrize("client_type", [OpenAICompatibleHTTPClient, OllamaHTTPClient])
def test_plain_messages_remain_unchanged_when_tool_calls_are_null(client_type):
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        response = (
            {"message": {"content": "ok"}}
            if client_type is OllamaHTTPClient
            else {"choices": [{"message": {"content": "ok"}}]}
        )
        return httpx.Response(200, json=response)

    provider = "ollama" if client_type is OllamaHTTPClient else "openai"
    client = client_type(
        config(provider=provider),
        httpx.Client(transport=httpx.MockTransport(handler), base_url="https://llm.test"),
    )
    messages = [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "plain reply", "tool_calls": None},
        {"role": "user", "content": "continue", "metadata": {"turn": 2}},
    ]
    original = deepcopy(messages)

    client.chat(messages)

    assert captured[0]["messages"] == original
    assert messages == original


@pytest.mark.parametrize("client_type", [OpenAICompatibleHTTPClient, OllamaHTTPClient])
def test_raw_openai_history_is_normalized_and_rendered_without_mutating_input(client_type):
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        response = (
            {"message": {"content": "ok"}}
            if client_type is OllamaHTTPClient
            else {"choices": [{"message": {"content": "ok"}}]}
        )
        return httpx.Response(200, json=response)

    provider = "ollama" if client_type is OllamaHTTPClient else "openai"
    client = client_type(
        config(provider=provider),
        httpx.Client(transport=httpx.MockTransport(handler), base_url="https://llm.test"),
    )
    messages = canonical_tool_history()
    messages[1]["tool_calls"][0]["function"]["arguments"] = '{"keyword":"A100"}'
    messages[2].pop("name")
    original = deepcopy(messages)

    client.chat(messages)

    rendered = captured[0]["messages"]
    if client_type is OpenAICompatibleHTTPClient:
        assert json.loads(rendered[1]["tool_calls"][0]["function"]["arguments"]) == {
            "keyword": "A100",
        }
        assert rendered[2]["name"] == "lookup"
        assert rendered[2]["tool_call_id"] == "call-1"
    else:
        assert rendered[1]["tool_calls"][0]["function"]["arguments"] == {
            "keyword": "A100",
        }
        assert rendered[2] == {"role": "tool", "content": '{"ok":true}'}
    assert messages == original


def malformed_tool_histories():
    assistant = canonical_tool_history()[1]
    observation = canonical_tool_history()[2]
    second_call = deepcopy(assistant["tool_calls"][0])
    second_call["id"] = "call-2"
    cases = {
        "orphan_tool": [deepcopy(observation)],
        "wrong_id": [
            deepcopy(assistant),
            {**deepcopy(observation), "tool_call_id": "call-wrong"},
        ],
        "wrong_name": [
            deepcopy(assistant),
            {**deepcopy(observation), "name": "other_lookup"},
        ],
        "duplicate_tool": [
            deepcopy(assistant),
            deepcopy(observation),
            deepcopy(observation),
        ],
        "unclosed_assistant": [deepcopy(assistant)],
        "non_adjacent_tool": [
            deepcopy(assistant),
            {"role": "assistant", "content": "not an observation"},
            deepcopy(observation),
        ],
        "multiple_calls": [{
            **deepcopy(assistant),
            "tool_calls": [
                deepcopy(assistant["tool_calls"][0]),
                second_call,
            ],
        }],
        "duplicate_call_id": [
            deepcopy(assistant),
            deepcopy(observation),
            deepcopy(assistant),
            deepcopy(observation),
        ],
        "malformed_json_arguments": [{
            **deepcopy(assistant),
            "tool_calls": [{
                **deepcopy(assistant["tool_calls"][0]),
                "function": {
                    "name": "lookup",
                    "arguments": "{",
                },
            }],
        }],
        "non_object_json_arguments": [{
            **deepcopy(assistant),
            "tool_calls": [{
                **deepcopy(assistant["tool_calls"][0]),
                "function": {
                    "name": "lookup",
                    "arguments": "[]",
                },
            }],
        }],
        "non_finite_json_arguments": [{
            **deepcopy(assistant),
            "tool_calls": [{
                **deepcopy(assistant["tool_calls"][0]),
                "function": {
                    "name": "lookup",
                    "arguments": '{"score":NaN}',
                },
            }],
        }],
    }
    return list(cases.items())


@pytest.mark.parametrize("client_type", [OpenAICompatibleHTTPClient, OllamaHTTPClient])
@pytest.mark.parametrize(("reason", "malformed"), malformed_tool_histories())
def test_malformed_tool_history_fails_closed_without_http_request(client_type, reason, malformed):
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    provider = "ollama" if client_type is OllamaHTTPClient else "openai"
    client = client_type(
        config(provider=provider),
        httpx.Client(transport=httpx.MockTransport(handler), base_url="https://llm.test"),
    )

    with pytest.raises(LLMInvalidRequestError):
        client.chat(malformed)

    assert calls == 0


def test_stream_history_validation_fails_before_openai_http_request():
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, text="data: [DONE]\n\n")

    client = OpenAICompatibleHTTPClient(
        config(provider="openai"),
        httpx.Client(transport=httpx.MockTransport(handler), base_url="https://llm.test"),
    )
    malformed = malformed_tool_histories()[0][1]
    tools = [{
        "type": "function",
        "function": {"name": "lookup", "parameters": {"type": "object"}},
    }]

    with pytest.raises(LLMInvalidRequestError):
        list(client.stream_chat(malformed, tools=tools))

    assert calls == 0


def test_authentication_error_is_not_retried():
    calls = 0
    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"error": "bad key"})
    client = OpenAICompatibleHTTPClient(config(max_retries=3), httpx.Client(transport=httpx.MockTransport(handler), base_url="https://llm.test"))
    with pytest.raises(LLMAuthenticationError):
        client.chat([{"role": "user", "content": "hello"}])
    assert calls == 1


def test_queue_wait_is_bounded():
    entered = threading.Event()
    release = threading.Event()
    def handler(_request):
        entered.set()
        release.wait(1)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    client = OpenAICompatibleHTTPClient(config(max_concurrent=1), httpx.Client(transport=httpx.MockTransport(handler), base_url="https://llm.test"))
    worker = threading.Thread(target=lambda: client.chat([{"role": "user", "content": "first"}]))
    worker.start()
    assert entered.wait(1)
    with pytest.raises(LLMConcurrencyLimitError):
        client.chat([{"role": "user", "content": "second"}])
    release.set()
    worker.join(1)
    assert not worker.is_alive()
