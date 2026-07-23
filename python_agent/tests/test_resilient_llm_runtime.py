from __future__ import annotations

import json
import threading

import httpx
import pytest

from after_sales_agent.providers.resilient_llm_runtime import (
    LLMAuthenticationError,
    LLMConcurrencyLimitError,
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
