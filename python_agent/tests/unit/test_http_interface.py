from __future__ import annotations

from io import BytesIO
import unittest
from unittest.mock import patch

from after_sales_agent.interface import http_server
from after_sales_agent.interface.http_server import RequestBodyReadError, read_http_request_body
from after_sales_agent.application.streaming_chat_service import (
    StreamingChatRequest,
    StreamingChatService,
)


class HttpRequestBodyTest(unittest.TestCase):
    def test_reads_content_length_request_body(self) -> None:
        payload = b'{"chunks":["refund policy"]}'

        body = read_http_request_body(
            {"Content-Length": str(len(payload))},
            BytesIO(payload),
            max_bytes=1024,
        )

        self.assertEqual(payload, body)

    def test_reads_chunked_request_body_used_by_spring_rest_template(self) -> None:
        raw = b'7\r\n{"chunk\r\nA\r\ns":["text"\r\n2\r\n]}\r\n0\r\n\r\n'

        body = read_http_request_body(
            {"Transfer-Encoding": "chunked"},
            BytesIO(raw),
            max_bytes=1024,
        )

        self.assertEqual(b'{"chunks":["text"]}', body)

    def test_rejects_chunked_body_over_the_request_limit(self) -> None:
        raw = b'5\r\n12345\r\n0\r\n\r\n'

        with self.assertRaises(RequestBodyReadError) as context:
            read_http_request_body(
                {"Transfer-Encoding": "chunked"},
                BytesIO(raw),
                max_bytes=4,
            )

        self.assertEqual("request_too_large", context.exception.error)
        self.assertEqual(413, context.exception.status)

    def test_application_shutdown_explicitly_closes_shared_clients_once(self) -> None:
        with patch.object(http_server.LLM_CLIENTS, "close") as close_llm, patch.object(
            http_server.RERANKER_CLIENTS, "close"
        ) as close_reranker:
            http_server.close_application_resources()

        close_llm.assert_called_once_with()
        close_reranker.assert_called_once_with()


class FakeChatService:
    def __init__(self) -> None:
        self.payloads = []

    def handle(self, payload, trace_recorder=None):
        self.payloads.append(payload)
        return {
            "assistant_reply": "你好",
            "need_human": False,
            "session_mode": "AI",
            "raw": {"runtime": "agentic_rag_chat"},
        }


def test_streaming_endpoint_uses_agentic_rag_chat_service():
    chat = FakeChatService()
    events = list(
        StreamingChatService(chat).stream(
            StreamingChatRequest(
                message="hello",
                request_id="r1",
                payload={"user_id": "7", "message": "hello"},
            )
        )
    )

    assert chat.payloads[0]["user_id"] == "7"
    assert chat.payloads[0]["message"] == "hello"
    assert [item["event"] for item in events] == ["start", "token", "finish", "done"]
    assert "data:" not in str(events)
    assert "".join(item.get("text", "") for item in events) == "你好"
    assert events[-1]["result"]["raw"]["runtime"] == "agentic_rag_chat"


if __name__ == "__main__":
    unittest.main()
