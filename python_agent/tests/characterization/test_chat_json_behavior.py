"""Characterization tests for chat_json() behavior in LLM clients.

These tests capture the existing JSON parsing contract so that Phase 2
(migration to generate_structured()) can verify behavioral equivalence.

Note: We avoid importing the actual LLM client module because it has
relative imports that cannot be resolved via spec_from_file_location.
Instead, we replicate the chat_json logic directly from the source
to test the parsing contract in isolation.
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock


class LLMResponseParseError(Exception):
    """Replicated from after_sales_agent.providers.resilient_llm_runtime."""
    pass


class MinimalClient:
    """Minimal client that replicates chat_json() behavior from llm_client.py."""

    def chat(self, messages, temperature=0.2, **kwargs):
        raise NotImplementedError

    def chat_json(self, *, system_prompt, user_prompt, temperature=0.2, max_tokens=600):
        # Exact copy of chat_json logic from llm_client.py line 141
        response = self.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        try:
            choice = response["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError) as e:
            try:
                content = response["message"]["content"]
            except (KeyError, AttributeError) as e2:
                raise LLMResponseParseError(
                    f"Chat response missing 'choices' or 'message': {e2}"
                ) from e2
        if isinstance(content, dict):
            return content
        if not isinstance(content, str):
            raise LLMResponseParseError(
                f"Expected string content, got {type(content).__name__}"
            )
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as e:
            raise LLMResponseParseError(
                f"Failed to parse chat JSON response: {content!r}"
            ) from e
        if not isinstance(parsed, dict):
            raise LLMResponseParseError(
                f"Expected JSON object, got {type(parsed).__name__}"
            )
        return parsed


class TestChatJsonBehavior(unittest.TestCase):
    """Characterize the exact parsing path of chat_json()."""

    def _make_client(self, raw_response: dict) -> MinimalClient:
        client = MinimalClient()
        client.chat = MagicMock(return_value=raw_response)
        return client

    def test_chat_json_parses_string_json_content(self):
        raw = {
            "choices": [
                {"message": {"role": "assistant", "content": '{"action":"handoff","note":"ok"}'}}
            ]
        }
        client = self._make_client(raw)
        result = client.chat_json(
            system_prompt="You are helpful.",
            user_prompt="Help me.",
        )
        self.assertEqual(result["action"], "handoff")
        self.assertEqual(result["note"], "ok")

    def test_chat_json_returns_dict_content_directly(self):
        """When content is already a dict, return it without json.loads."""
        raw = {
            "choices": [
                {"message": {"role": "assistant", "content": {"action": "direct", "value": 42}}}
            ]
        }
        client = self._make_client(raw)
        result = client.chat_json(
            system_prompt="You are helpful.",
            user_prompt="Help me.",
        )
        self.assertEqual(result["action"], "direct")
        self.assertEqual(result["value"], 42)

    def test_chat_json_throws_on_missing_content_key(self):
        raw = {"choices": [{}]}
        client = self._make_client(raw)
        with self.assertRaises(LLMResponseParseError):
            client.chat_json(
                system_prompt="You are helpful.",
                user_prompt="Help me.",
            )

    def test_chat_json_throws_on_invalid_json_string(self):
        raw = {
            "choices": [
                {"message": {"role": "assistant", "content": "this is not json"}}
            ]
        }
        client = self._make_client(raw)
        with self.assertRaises(LLMResponseParseError):
            client.chat_json(
                system_prompt="You are helpful.",
                user_prompt="Help me.",
            )

    def test_chat_json_throws_on_index_error_in_choices(self):
        raw = {"choices": []}
        client = self._make_client(raw)
        with self.assertRaises(LLMResponseParseError):
            client.chat_json(
                system_prompt="You are helpful.",
                user_prompt="Help me.",
            )

    def test_chat_json_uses_message_content_fallback(self):
        """Non-standard format without 'choices' should use message.content."""
        raw = {
            "message": {"role": "assistant", "content": '{"status":"ok"}'}
        }
        client = self._make_client(raw)
        result = client.chat_json(
            system_prompt="You are helpful.",
            user_prompt="Help me.",
        )
        self.assertEqual(result["status"], "ok")

    def test_chat_json_with_chinese_content(self):
        raw = {
            "choices": [
                {"message": {"role": "assistant", "content": '{"action":"human_handoff","assistant_reply":"已为您转接人工客服"}'}}
            ]
        }
        client = self._make_client(raw)
        result = client.chat_json(
            system_prompt="You are helpful.",
            user_prompt="Help me.",
        )
        self.assertEqual(result["assistant_reply"], "已为您转接人工客服")

    def test_chat_json_default_temperature_is_02(self):
        """Verify the default temperature parameter."""
        received_kwargs: dict = {}

        class TracingClient(MinimalClient):
            def chat(self, messages, temperature=0.2, **kwargs):
                received_kwargs["temperature"] = temperature
                return {
                    "choices": [
                        {"message": {"role": "assistant", "content": '{"x":1}'}}
                    ]
                }

        client = TracingClient()
        client.chat_json(system_prompt="s", user_prompt="u")
        self.assertEqual(received_kwargs["temperature"], 0.2)

    def test_chat_json_custom_temperature_passed_through(self):
        received_kwargs: dict = {}

        class TracingClient(MinimalClient):
            def chat(self, messages, temperature=0.2, **kwargs):
                received_kwargs["temperature"] = temperature
                return {
                    "choices": [
                        {"message": {"role": "assistant", "content": '{"x":1}'}}
                    ]
                }

        client = TracingClient()
        client.chat_json(system_prompt="s", user_prompt="u", temperature=0.7)
        self.assertEqual(received_kwargs["temperature"], 0.7)

    def test_chat_json_passes_system_and_user_messages(self):
        received_messages: list = []

        class TracingClient(MinimalClient):
            def chat(self, messages, **kwargs):
                received_messages.extend(messages)
                return {
                    "choices": [
                        {"message": {"role": "assistant", "content": '{"ok":true}'}}
                    ]
                }

        client = TracingClient()
        client.chat_json(system_prompt="sys", user_prompt="usr")
        self.assertEqual(len(received_messages), 2)
        self.assertEqual(received_messages[0]["role"], "system")
        self.assertEqual(received_messages[0]["content"], "sys")
        self.assertEqual(received_messages[1]["role"], "user")
        self.assertEqual(received_messages[1]["content"], "usr")


if __name__ == "__main__":
    unittest.main()
