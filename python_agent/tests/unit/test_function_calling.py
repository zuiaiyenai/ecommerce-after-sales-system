from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import Mock

from after_sales_agent.application.function_calling import (
    FunctionCallingAdapter,
    FunctionCallingProtocolError,
)
from after_sales_agent.tools import AgentToolRegistry


class RecordingClient:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.requests: list[dict[str, Any]] = []

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, **kwargs: Any) -> dict[str, Any]:
        self.requests.append({"messages": messages, "tools": tools, **kwargs})
        return self.response

    def chat_json(self, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int) -> dict[str, Any]:
        self.requests.append({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "temperature": temperature,
            "max_tokens": max_tokens,
        })
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


def ollama_tool_response(
    *,
    name: str = "search_user_orders",
    arguments: object | None = None,
    call_id: str | None = None,
    call_type: str | None = None,
) -> dict[str, Any]:
    tool_call: dict[str, Any] = {
        "function": {
            "name": name,
            "arguments": {"keyword": "A100"} if arguments is None else arguments,
        },
    }
    if call_id is not None:
        tool_call["id"] = call_id
    if call_type is not None:
        tool_call["type"] = call_type
    return {
        "model": "qwen3:8b",
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [tool_call],
        },
        "done": True,
    }


class FunctionCallingAdapterTest(unittest.TestCase):
    def _adapter(self, response: dict[str, Any]) -> tuple[FunctionCallingAdapter, RecordingClient, RecordingRegistry]:
        client = RecordingClient(response)
        registry = RecordingRegistry()
        return FunctionCallingAdapter(client=client, registry=registry, temperature=0.35, max_tokens=321), client, registry

    def test_parses_single_tool_call_into_canonical_assistant_message(self) -> None:
        response = tool_response()
        adapter, _, registry = self._adapter(response)

        decision = adapter.decide(system_prompt="system", payload={"user": {"message": "help"}}, prior_messages=[])

        self.assertEqual({
            "action": "tool_call",
            "tool_name": "search_user_orders",
            "tool_arguments": {"keyword": "A100"},
            "tool_call_id": "call-1",
        }, decision.action)
        self.assertEqual({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": "search_user_orders",
                    "arguments": {"keyword": "A100"},
                },
            }],
        }, decision.assistant_message)
        self.assertIsNot(decision.assistant_message, response["choices"][0]["message"])
        self.assertEqual(
            '{"keyword":"A100"}',
            response["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"],
        )
        self.assertEqual("openai", decision.provider_tool_call_shape)
        self.assertEqual(0, registry.call_count)

    def test_openai_and_ollama_calls_normalize_to_the_same_canonical_envelope(self) -> None:
        openai_response = tool_response()
        openai_adapter, _, _ = self._adapter(openai_response)
        ollama_response = ollama_tool_response(call_id="call-1", call_type="function")
        ollama_response["message"]["content"] = None
        ollama_adapter, _, _ = self._adapter(ollama_response)

        openai = openai_adapter.decide(system_prompt="system", payload={}, prior_messages=[])
        ollama = ollama_adapter.decide(system_prompt="system", payload={}, prior_messages=[])

        self.assertEqual(openai.assistant_message, ollama.assistant_message)
        canonical_call = openai.assistant_message["tool_calls"][0]
        self.assertEqual("call-1", canonical_call["id"])
        self.assertEqual("function", canonical_call["type"])
        self.assertEqual("search_user_orders", canonical_call["function"]["name"])
        self.assertEqual({"keyword": "A100"}, canonical_call["function"]["arguments"])
        self.assertEqual(
            '{"keyword":"A100"}',
            openai_response["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"],
        )
        self.assertEqual(
            {"keyword": "A100"},
            ollama_response["message"]["tool_calls"][0]["function"]["arguments"],
        )

    def test_parses_real_ollama_object_arguments_and_normalizes_missing_envelope_fields(self) -> None:
        response = ollama_tool_response()
        adapter, _, registry = self._adapter(response)

        first = adapter.decide(system_prompt="system", payload={}, prior_messages=[])
        second = adapter.decide(system_prompt="system", payload={}, prior_messages=[])

        self.assertEqual("ollama", first.provider_tool_call_shape)
        self.assertEqual("tool_call", first.action["action"])
        self.assertEqual({"keyword": "A100"}, first.action["tool_arguments"])
        self.assertRegex(first.action["tool_call_id"], r"^call_ollama_[0-9a-f]{32}$")
        self.assertNotEqual(first.action["tool_call_id"], second.action["tool_call_id"])
        normalized_call = first.assistant_message["tool_calls"][0]
        self.assertEqual(first.action["tool_call_id"], normalized_call["id"])
        self.assertEqual("function", normalized_call["type"])
        self.assertEqual({"keyword": "A100"}, normalized_call["function"]["arguments"])
        self.assertEqual("assistant", first.assistant_message["role"])
        self.assertEqual(0, registry.call_count)

    def test_rejects_malformed_or_ambiguous_ollama_shapes(self) -> None:
        two_calls = ollama_tool_response()
        two_calls["message"]["tool_calls"].append({
            "function": {"name": "search_user_orders", "arguments": {"keyword": "A200"}},
        })
        ambiguous = ollama_tool_response()
        ambiguous["choices"] = tool_response()["choices"]
        malformed = [
            {"message": {"role": "assistant", "tool_calls": []}},
            two_calls,
            ollama_tool_response(arguments=[]),
            ollama_tool_response(arguments='{"keyword":"A100"}'),
            ollama_tool_response(call_id=" "),
            ollama_tool_response(call_type="custom"),
            {"message": {"role": "assistant", "tool_calls": [{"function": {"arguments": {}}}]}},
            ambiguous,
        ]

        for response in malformed:
            with self.subTest(response=response):
                adapter, _, registry = self._adapter(response)
                with self.assertRaises(FunctionCallingProtocolError):
                    adapter.decide(system_prompt="system", payload={}, prior_messages=[])
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
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "old",
                    "type": "function",
                    "function": {
                        "name": "search_user_orders",
                        "arguments": {"keyword": "A099"},
                    },
                }],
            },
            {
                "role": "tool",
                "tool_call_id": "old",
                "name": "search_user_orders",
                "content": '{"ok":true}',
            },
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

    def test_real_registry_rejects_invalid_arguments_without_executing_tools(self) -> None:
        invalid_calls = [
            ("search_user_orders", {"keyword": 100}),
            ("search_user_orders", {"status_filter": "SHIPPED"}),
            ("retrieve_knowledge", {}),
            ("review_images", {}),
            ("review_images", {"attachments": {}}),
            ("review_images", {"attachments": ["not-an-object"]}),
            ("review_images", {"attachments": [{"kind": "image", "unexpected": True}]}),
            ("get_merchant_policy", {}),
            ("search_user_orders", {"unexpected": "field"}),
        ]

        for name, arguments in invalid_calls:
            with self.subTest(name=name, arguments=arguments):
                registry = AgentToolRegistry()
                registry.call = Mock()
                adapter = FunctionCallingAdapter(
                    client=RecordingClient(tool_response(name=name, arguments=json.dumps(arguments))),
                    registry=registry,
                )

                with self.assertRaises(FunctionCallingProtocolError):
                    adapter.decide(system_prompt="system", payload={}, prior_messages=[])

                registry.call.assert_not_called()

    def test_native_requires_runtime_defaulted_model_fields_without_execution(self) -> None:
        for name in ("review_images", "get_merchant_policy"):
            with self.subTest(name=name):
                registry = AgentToolRegistry()
                registry.call = Mock()
                adapter = FunctionCallingAdapter(
                    client=RecordingClient(tool_response(name=name, arguments="{}")),
                    registry=registry,
                )

                with self.assertRaises(FunctionCallingProtocolError):
                    adapter.decide(system_prompt="system", payload={}, prior_messages=[])

                registry.call.assert_not_called()

    def test_real_registry_rejects_forged_trusted_ids_without_executing_tools(self) -> None:
        for trusted_id in ("user_id", "session_id", "order_id", "ticket_id", "review_request_id"):
            with self.subTest(trusted_id=trusted_id):
                registry = AgentToolRegistry()
                registry.call = Mock()
                adapter = FunctionCallingAdapter(
                    client=RecordingClient(tool_response(arguments=json.dumps({
                        "keyword": "A100",
                        trusted_id: "forged",
                    }))),
                    registry=registry,
                )

                with self.assertRaises(FunctionCallingProtocolError):
                    adapter.decide(system_prompt="system", payload={}, prior_messages=[])

                registry.call.assert_not_called()

    def test_control_schema_rejects_missing_extra_and_wrong_typed_arguments(self) -> None:
        invalid_arguments = [
            {},
            {"assistant_reply": "已记录", "need_human": "true"},
            {"assistant_reply": "已记录", "evidence_needed": "图片"},
            {"assistant_reply": "已记录", "evidence_needed": [1]},
            {"assistant_reply": "已记录", "user_id": "forged"},
        ]

        for arguments in invalid_arguments:
            with self.subTest(arguments=arguments):
                adapter, _, registry = self._adapter(tool_response(
                    name="final_reply",
                    arguments=json.dumps(arguments, ensure_ascii=False),
                ))

                with self.assertRaises(FunctionCallingProtocolError):
                    adapter.decide(system_prompt="system", payload={}, prior_messages=[])

                self.assertEqual(0, registry.call_count)

    def test_real_registry_rejects_non_finite_and_boolean_numbers_without_execution(self) -> None:
        invalid_numbers = ("NaN", "Infinity", "-Infinity", "1e999", "true")

        for raw_number in invalid_numbers:
            with self.subTest(raw_number=raw_number):
                registry = AgentToolRegistry()
                registry.call = Mock()
                adapter = FunctionCallingAdapter(
                    client=RecordingClient(tool_response(
                        name="retrieve_knowledge",
                        arguments=f'{{"query":"refund policy","top_k":{raw_number}}}',
                    )),
                    registry=registry,
                )

                with self.assertRaises(FunctionCallingProtocolError):
                    adapter.decide(system_prompt="system", payload={}, prior_messages=[])

                registry.call.assert_not_called()

if __name__ == "__main__":
    unittest.main()
