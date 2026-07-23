from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


@dataclass(frozen=True)
class NativeDecision:
    action: dict[str, Any]
    assistant_message: dict[str, Any]


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
        response = self._client.chat(
            [
                {"role": "system", "content": system_prompt},
                *prior_messages,
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
            ],
            tools=self._provider_tools(),
            tool_choice="required",
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        assistant_message = self._assistant_message(response)
        tool_call = self._single_tool_call(assistant_message)
        call_id = tool_call.get("id")
        if not isinstance(call_id, str) or not call_id.strip():
            raise FunctionCallingProtocolError("tool call id is required")
        if tool_call.get("type") != "function":
            raise FunctionCallingProtocolError("tool call type must be function")

        function = tool_call.get("function")
        if not isinstance(function, dict):
            raise FunctionCallingProtocolError("tool call function is required")
        name = function.get("name")
        if not isinstance(name, str) or not name.strip():
            raise FunctionCallingProtocolError("tool call name is required")
        name = name.strip()
        if name not in self._known_names():
            raise FunctionCallingProtocolError(f"unknown tool call: {name}")
        arguments = self._arguments(function.get("arguments"))
        return NativeDecision(
            action=self._normalize_action(name, arguments, call_id),
            assistant_message=assistant_message,
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
    def _assistant_message(response: Any) -> dict[str, Any]:
        try:
            message = response["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise FunctionCallingProtocolError("model response has no assistant message") from exc
        if not isinstance(message, dict):
            raise FunctionCallingProtocolError("model assistant message must be an object")
        return message

    @staticmethod
    def _single_tool_call(assistant_message: dict[str, Any]) -> dict[str, Any]:
        calls = assistant_message.get("tool_calls")
        if not isinstance(calls, list) or len(calls) != 1 or not isinstance(calls[0], dict):
            raise FunctionCallingProtocolError("model response must contain exactly one tool call")
        return calls[0]

    @staticmethod
    def _arguments(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, str):
            raise FunctionCallingProtocolError("tool call arguments must be a JSON string")
        try:
            arguments = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise FunctionCallingProtocolError("tool call arguments must contain valid JSON") from exc
        if not isinstance(arguments, dict):
            raise FunctionCallingProtocolError("tool call arguments must decode to an object")
        return arguments

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
