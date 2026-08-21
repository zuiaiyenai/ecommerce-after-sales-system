from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import math
from typing import Any
import uuid


@dataclass(frozen=True)
class NativeDecision:
    action: dict[str, Any]
    assistant_message: dict[str, Any]
    provider_tool_call_shape: str


class FunctionCallingProtocolError(ValueError):
    pass


class FunctionCallingAdapter:
    """Translate one provider-native tool call into the existing workflow action."""

    def __init__(
        self,
        *,
        client: Any,
        registry: Any,
        temperature: float = 0.2,
        max_tokens: int = 600,
    ) -> None:
        self._client = client
        self._registry = registry
        self._temperature = temperature
        self._max_tokens = max_tokens

    def decide(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        prior_messages: list[dict[str, Any]],
    ) -> NativeDecision:
        provider_tools = self._provider_tools()
        response = self._client.chat(
            [
                {"role": "system", "content": system_prompt},
                *prior_messages,
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
            ],
            tools=provider_tools,
            tool_choice="required",
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        assistant_message, provider_shape = self._assistant_message(response)
        tool_call = self._single_tool_call(assistant_message)
        call_id = self._call_id(tool_call, provider_shape)
        self._validate_call_type(tool_call, provider_shape)

        function = tool_call.get("function")
        if not isinstance(function, dict):
            raise FunctionCallingProtocolError("tool call function is required")
        name = function.get("name")
        if not isinstance(name, str) or not name.strip():
            raise FunctionCallingProtocolError("tool call name is required")
        name = name.strip()
        if name not in self._known_names():
            raise FunctionCallingProtocolError(f"unknown tool call: {name}")
        arguments = self._arguments(function.get("arguments"), provider_shape)
        self._validate_schema_value(
            arguments,
            self._schema_for_name(name, provider_tools),
            path=f"{name}.arguments",
        )
        assistant_message = self._canonical_assistant_message(
            assistant_message,
            call_id=call_id,
            name=name,
            arguments=arguments,
        )
        return NativeDecision(
            action=self._normalize_action(name, arguments, call_id),
            assistant_message=assistant_message,
            provider_tool_call_shape=provider_shape,
        )

    def _provider_tools(self) -> list[dict[str, Any]]:
        tools = []
        for spec in self._registry.tool_specs():
            tools.append({
                "type": "function",
                "function": {
                    "name": spec["name"],
                    "description": spec["description"],
                    "parameters": spec["input_schema"],
                },
            })
        tools.append({
            "type": "function",
            "function": {
                "name": "final_reply",
                "description": "Return the final user-facing reply without executing a tool.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "assistant_reply": {"type": "string"},
                        "need_human": {"type": "boolean"},
                        "evidence_needed": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["assistant_reply"],
                    "additionalProperties": False,
                },
            },
        })
        return tools

    def _known_names(self) -> set[str]:
        return set(self._registry.registry()) | {"final_reply"}

    @staticmethod
    def _schema_for_name(name: str, provider_tools: list[dict[str, Any]]) -> dict[str, Any]:
        for tool in provider_tools:
            function = tool.get("function")
            if isinstance(function, dict) and function.get("name") == name:
                schema = function.get("parameters")
                if isinstance(schema, dict):
                    return schema
                break
        raise FunctionCallingProtocolError(f"tool call schema is unavailable: {name}")

    @classmethod
    def _validate_schema_value(cls, value: Any, schema: dict[str, Any], *, path: str) -> None:
        expected = schema.get("type")
        if expected == "object":
            if not isinstance(value, dict):
                raise FunctionCallingProtocolError(f"{path} must be an object")
            properties = schema.get("properties")
            required = schema.get("required", [])
            if not isinstance(properties, dict) or not isinstance(required, list):
                raise FunctionCallingProtocolError(f"{path} has an invalid object schema")
            missing = [name for name in required if name not in value]
            if missing:
                raise FunctionCallingProtocolError(f"{path} is missing required fields: {', '.join(missing)}")
            unknown = set(value) - set(properties)
            if schema.get("additionalProperties") is not False:
                raise FunctionCallingProtocolError(f"{path} schema must reject additional properties")
            if unknown:
                raise FunctionCallingProtocolError(
                    f"{path} contains unknown fields: {', '.join(sorted(unknown))}"
                )
            for name, child in value.items():
                child_schema = properties.get(name)
                if not isinstance(child_schema, dict):
                    raise FunctionCallingProtocolError(f"{path}.{name} has no valid schema")
                cls._validate_schema_value(child, child_schema, path=f"{path}.{name}")
            return
        if expected == "array":
            if not isinstance(value, list):
                raise FunctionCallingProtocolError(f"{path} must be an array")
            items = schema.get("items")
            if not isinstance(items, dict):
                raise FunctionCallingProtocolError(f"{path} has an invalid array schema")
            for index, item in enumerate(value):
                cls._validate_schema_value(item, items, path=f"{path}[{index}]")
            return
        if expected == "string":
            valid = isinstance(value, str)
        elif expected == "boolean":
            valid = isinstance(value, bool)
        elif expected == "number":
            valid = (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and cls._is_finite_number(value)
            )
        elif expected == "integer":
            valid = (
                isinstance(value, int)
                and not isinstance(value, bool)
                and cls._is_finite_number(value)
            )
        elif expected == "null":
            valid = value is None
        else:
            raise FunctionCallingProtocolError(f"{path} has unsupported schema type: {expected}")
        if not valid:
            raise FunctionCallingProtocolError(f"{path} must be {expected}")

    @staticmethod
    def _is_finite_number(value: int | float) -> bool:
        try:
            return math.isfinite(value)
        except (OverflowError, TypeError):
            return False

    @staticmethod
    def _assistant_message(response: Any) -> tuple[dict[str, Any], str]:
        if not isinstance(response, dict):
            raise FunctionCallingProtocolError("model response must be an object")
        has_openai_shape = "choices" in response
        has_ollama_shape = "message" in response
        if has_openai_shape == has_ollama_shape:
            raise FunctionCallingProtocolError("model response has an ambiguous assistant message shape")
        if has_openai_shape:
            try:
                message = response["choices"][0]["message"]
            except (KeyError, IndexError, TypeError) as exc:
                raise FunctionCallingProtocolError("model response has no assistant message") from exc
            provider_shape = "openai"
        else:
            message = response["message"]
            provider_shape = "ollama"
        if not isinstance(message, dict):
            raise FunctionCallingProtocolError("model assistant message must be an object")
        if provider_shape == "ollama" and message.get("role") != "assistant":
            raise FunctionCallingProtocolError("Ollama tool response must use the assistant role")
        return message, provider_shape

    @staticmethod
    def _single_tool_call(assistant_message: dict[str, Any]) -> dict[str, Any]:
        calls = assistant_message.get("tool_calls")
        if not isinstance(calls, list) or len(calls) != 1 or not isinstance(calls[0], dict):
            raise FunctionCallingProtocolError("model response must contain exactly one tool call")
        return calls[0]

    @staticmethod
    def _arguments(raw: Any, provider_shape: str) -> dict[str, Any]:
        if provider_shape == "ollama":
            if not isinstance(raw, dict):
                raise FunctionCallingProtocolError("Ollama tool call arguments must be an object")
            return dict(raw)
        if not isinstance(raw, str):
            raise FunctionCallingProtocolError("tool call arguments must be a JSON string")
        try:
            arguments = json.loads(
                raw,
                parse_constant=FunctionCallingAdapter._reject_json_constant,
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise FunctionCallingProtocolError("tool call arguments must contain valid JSON") from exc
        if not isinstance(arguments, dict):
            raise FunctionCallingProtocolError("tool call arguments must decode to an object")
        return arguments

    @staticmethod
    def _call_id(tool_call: dict[str, Any], provider_shape: str) -> str:
        call_id = tool_call.get("id")
        if provider_shape == "ollama" and call_id is None:
            return f"call_ollama_{uuid.uuid4().hex}"
        if not isinstance(call_id, str) or not call_id.strip():
            raise FunctionCallingProtocolError("tool call id is required")
        return call_id

    @staticmethod
    def _validate_call_type(tool_call: dict[str, Any], provider_shape: str) -> None:
        call_type = tool_call.get("type")
        if provider_shape == "ollama" and call_type is None:
            return
        if call_type != "function":
            raise FunctionCallingProtocolError("tool call type must be function")

    @staticmethod
    def _canonical_assistant_message(
        source: dict[str, Any],
        *,
        call_id: str,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        content = source.get("content")
        if content is not None and not isinstance(content, str):
            raise FunctionCallingProtocolError("Ollama assistant content must be text or null")
        return {
            "role": "assistant",
            "content": content,
            "tool_calls": [{
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": deepcopy(arguments),
                },
            }],
        }

    @staticmethod
    def _reject_json_constant(value: str) -> None:
        raise ValueError(f"non-standard JSON constant is not allowed: {value}")

    @staticmethod
    def _normalize_action(name: str, arguments: dict[str, Any], call_id: str) -> dict[str, Any]:
        if name == "final_reply":
            if not isinstance(arguments.get("assistant_reply"), str):
                raise FunctionCallingProtocolError("final_reply requires assistant_reply")
            action: dict[str, Any] = {
                "action": "final_reply",
                "assistant_reply": arguments["assistant_reply"],
                "tool_call_id": call_id,
            }
            if "need_human" in arguments:
                action["need_human"] = arguments["need_human"]
            if "evidence_needed" in arguments:
                action["evidence_needed"] = arguments["evidence_needed"]
            return action
        if name == "handoff_to_human":
            action = {"action": "human_handoff", "tool_call_id": call_id, "need_human": True}
            for key in ("assistant_reply", "evidence_needed"):
                if key in arguments:
                    action[key] = arguments[key]
            return action
        return {
            "action": "tool_call",
            "tool_name": name,
            "tool_arguments": arguments,
            "tool_call_id": call_id,
        }
