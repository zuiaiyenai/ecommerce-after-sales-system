from __future__ import annotations

from after_sales_agent.application.streaming_chat_service import (
    StreamingChatRequest,
    StreamingChatService,
)


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
