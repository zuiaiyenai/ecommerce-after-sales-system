from __future__ import annotations

import unittest
from typing import Any

from after_sales_agent.application.function_calling import (
    FunctionCallingAdapter,
    FunctionCallingProtocolError,
)


class RecordingClient:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.requests: list[dict[str, Any]] = []

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, **kwargs: Any) -> dict[str, Any]:
        self.requests.append({"messages": messages, "tools": tools, **kwargs})
        return self.response


class RecordingRegistry:
    def __init__(self) -> None:
        self.call_count = 0

    def tool_specs(self) -> list[dict[str, Any]]:
        return [{
            "name": "search_user_orders",
            "description": "Search orders.",
            "input_schema": {
                "type": "object",
                "properties": {"keyword": {"type": "string"}},
                "required": ["keyword"],
                "additionalProperties": False,
            },
        }, {
            "name": "handoff_to_human",
            "description": "Handoff.",
            "input_schema": {
                "type": "object",
                "properties": {"assistant_reply": {"type": "string"}},
                "required": [],
                "additionalProperties": False,
            },
        }]

    def registry(self) -> dict[str, object]:
        return {"search_user_orders": object(), "handoff_to_human": object()}

    def call(self, *_: Any, **__: Any) -> None:
        self.call_count += 1
        raise AssertionError("protocol parsing must not execute a registry tool")


def tool_response(
    *,
    name: str = "search_user_orders",
    arguments: str = '{"keyword":"A100"}',
    call_id: str = "call-1",
    call_type: str = "function",
) -> dict[str, Any]:
    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [{
        "id": call_id,
        "type": call_type,
        "function": {"name": name, "arguments": arguments},
    }]}}]}


class FunctionCallingAdapterTest(unittest.TestCase):
    def _adapter(self, response: dict[str, Any]) -> tuple[FunctionCallingAdapter, RecordingClient, RecordingRegistry]:
        client = RecordingClient(response)
        registry = RecordingRegistry()
        return FunctionCallingAdapter(client=client, registry=registry, temperature=0.35, max_tokens=321), client, registry

    def test_parses_single_tool_call_and_preserves_exact_assistant_message(self) -> None:
        response = tool_response()
        adapter, _, registry = self._adapter(response)

        decision = adapter.decide(system_prompt="system", payload={"user": {"message": "help"}}, prior_messages=[])

        self.assertEqual({
            "action": "tool_call",
            "tool_name": "search_user_orders",
            "tool_arguments": {"keyword": "A100"},
            "tool_call_id": "call-1",
        }, decision.action)
        self.assertIs(decision.assistant_message, response["choices"][0]["message"])
        self.assertEqual(0, registry.call_count)

    def test_normalizes_control_calls(self) -> None:
        final_adapter, _, _ = self._adapter(tool_response(
            name="final_reply",
            arguments='{"assistant_reply":"已记录","need_human":true,"evidence_needed":["图片"]}',
        ))
        handoff_adapter, _, _ = self._adapter(tool_response(
            name="handoff_to_human",
            arguments='{"assistant_reply":"转人工"}',
        ))

        self.assertEqual({
            "action": "final_reply", "assistant_reply": "已记录", "need_human": True,
            "evidence_needed": ["图片"], "tool_call_id": "call-1",
        }, final_adapter.decide(system_prompt="system", payload={}, prior_messages=[]).action)
        self.assertEqual("human_handoff", handoff_adapter.decide(
            system_prompt="system", payload={}, prior_messages=[]
        ).action["action"])

    def test_rejects_invalid_tool_calls(self) -> None:
        invalid_responses = [
            {"choices": [{"message": {"role": "assistant", "tool_calls": []}}]},
            {"choices": [{"message": {"role": "assistant", "tool_calls": [
                tool_response()["choices"][0]["message"]["tool_calls"][0],
                tool_response(call_id="call-2")["choices"][0]["message"]["tool_calls"][0],
            ]}}]},
            tool_response(name="not_registered"),
            tool_response(call_id=" "),
            tool_response(call_type="custom"),
            tool_response(arguments="not json"),
            tool_response(arguments="[]"),
            {"choices": [{"message": {"role": "assistant", "tool_calls": [{
                "id": "call-1", "type": "function", "function": {"arguments": "{}"},
            }]}}]},
        ]

        for response in invalid_responses:
            with self.subTest(response=response):
                adapter, _, registry = self._adapter(response)
                with self.assertRaises(FunctionCallingProtocolError):
                    adapter.decide(system_prompt="system", payload={}, prior_messages=[])
                self.assertEqual(0, registry.call_count)

    def test_forwards_provider_tools_options_and_prior_protocol_messages(self) -> None:
        adapter, client, _ = self._adapter(tool_response())
        prior = [
            {"role": "assistant", "content": None, "tool_calls": [{"id": "old", "type": "function"}]},
            {"role": "tool", "tool_call_id": "old", "content": '{"ok":true}'},
        ]

        adapter.decide(system_prompt="system", payload={"message": "hello"}, prior_messages=prior)

        request = client.requests[0]
        self.assertEqual("required", request["tool_choice"])
        self.assertEqual(0.35, request["temperature"])
        self.assertEqual(321, request["max_tokens"])
        self.assertEqual([{"role": "system", "content": "system"}, *prior, {"role": "user", "content": '{"message":"hello"}'}], request["messages"])
        names = [item["function"]["name"] for item in request["tools"]]
        self.assertEqual(["search_user_orders", "handoff_to_human", "final_reply"], names)
        self.assertEqual("object", request["tools"][0]["function"]["parameters"]["type"])


if __name__ == "__main__":
    unittest.main()
