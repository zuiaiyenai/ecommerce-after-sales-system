from __future__ import annotations

import os
import json
from copy import deepcopy
from time import perf_counter

import pytest

from after_sales_agent.providers.llm_client import OpenAICompatibleClient, OpenAICompatibleConfig


@pytest.mark.real_llm
@pytest.mark.skipif(not os.getenv("LLM_API_KEY"), reason="LLM_API_KEY is not configured")
def test_real_llm_chat_smoke():
    client = OpenAICompatibleClient(OpenAICompatibleConfig.from_env())
    try:
        response = client.chat(
            [{"role": "system", "content": "Reply briefly."}, {"role": "user", "content": "Reply with OK."}],
            temperature=0,
            max_tokens=8,
        )
        assert response.get("choices")
    finally:
        client.close()


@pytest.mark.real_llm
@pytest.mark.skipif(not os.getenv("LLM_API_KEY"), reason="LLM_API_KEY is not configured")
def test_real_llm_chat_json():
    client = OpenAICompatibleClient(OpenAICompatibleConfig.from_env())
    try:
        result = client.chat_json(
            system_prompt='Return JSON only: {"emotion":"angry","score":0.8}',
            user_prompt="用户说：等了十天还没退款，我非常生气！",
            temperature=0,
            max_tokens=80,
        )
        assert result["emotion"] == "angry"
        assert 0 <= float(result["score"]) <= 1
    finally:
        client.close()


@pytest.mark.real_llm
@pytest.mark.skipif(not os.getenv("LLM_API_KEY"), reason="LLM_API_KEY is not configured")
def test_real_llm_function_call_protocol_accepts_raw_openai_history_without_mutation():
    client = OpenAICompatibleClient(OpenAICompatibleConfig.from_env())
    tools = [{"type": "function", "function": {"name": "query_order_info", "description": "Query an order", "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]}}}]
    try:
        first = client.chat([{"role": "user", "content": "查询订单 202607040001"}], tools=tools, tool_choice="required", max_tokens=120)
        assistant = first["choices"][0]["message"]
        call = assistant["tool_calls"][0]
        assert call["id"]
        assert call["function"]["name"] == "query_order_info"
        assert json.loads(call["function"]["arguments"])["order_id"] == "202607040001"
        messages = [
            {"role": "user", "content": "查询订单 202607040001"},
            assistant,
            {"role": "tool", "tool_call_id": call["id"], "content": '{"status":"delivered"}'},
        ]
        original = deepcopy(messages)
        final = client.chat(messages, tools=tools, tool_choice="none", max_tokens=80)
        assert final["choices"][0]["message"].get("content")
        assert messages == original
    finally:
        client.close()


@pytest.mark.real_llm
@pytest.mark.skipif(not os.getenv("LLM_API_KEY"), reason="LLM_API_KEY is not configured")
def test_real_llm_stream_chat(capsys):
    client = OpenAICompatibleClient(OpenAICompatibleConfig.from_env())
    started = perf_counter()
    first_token = None
    text = []
    finish = None
    usage = None
    try:
        for event in client.stream_chat([{"role": "user", "content": "用一句话说明七天无理由退货。"}], temperature=0, max_tokens=80, stream_options={"include_usage": True}):
            if event.get("usage"):
                usage = event["usage"]
            for choice in event.get("choices") or []:
                content = (choice.get("delta") or {}).get("content")
                if content:
                    first_token = first_token or perf_counter()
                    text.append(content)
                finish = choice.get("finish_reason") or finish
        assert text
        assert finish
        assert usage is not None
        print(f"first_token_ms={int((first_token-started)*1000)} total_ms={int((perf_counter()-started)*1000)}")
    finally:
        client.close()
