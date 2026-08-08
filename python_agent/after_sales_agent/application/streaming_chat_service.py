from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Iterator
import uuid

from .chat import AgenticRagChatService
from ..infra.request_tracing import TraceRecorder


@dataclass(frozen=True)
class StreamingChatRequest:
    message: str
    recent_history: tuple[dict[str, str], ...] = ()
    request_id: str = ""
    session_id: str | None = None
    user_id: str | None = None
    payload: dict[str, Any] | None = None


class StreamingChatService:
    """Expose Agentic RAG chat results as semantic SSE events.

    The policy answer is generated and persisted before the first token event,
    so the streaming endpoint cannot bypass RAG trust checks or Java writes.
    """

    def __init__(
        self,
        chat_service: AgenticRagChatService | None = None,
    ) -> None:
        self.chat_service = chat_service or AgenticRagChatService()

    def stream(
        self,
        request: StreamingChatRequest,
        trace_recorder: TraceRecorder | None = None,
    ) -> Iterator[dict[str, Any]]:
        request_id = request.request_id or uuid.uuid4().hex
        started = perf_counter()
        payload = dict(request.payload or {})
        payload.setdefault("message", request.message)
        payload.setdefault("recent_history", list(request.recent_history))
        payload.setdefault("session_id", request.session_id)
        payload.setdefault("user_id", request.user_id)
        yield {
            "event": "start",
            "requestId": request_id,
            "runtime": "agentic_rag_chat",
        }
        result = self.chat_service.handle(payload, trace_recorder=trace_recorder)
        reply = str(result.get("assistant_reply") or "")
        first_token_ms = int((perf_counter() - started) * 1000)
        if reply:
            yield {
                "event": "token",
                "requestId": request_id,
                "text": reply,
            }
        yield {
            "event": "finish",
            "requestId": request_id,
            "reason": "stop",
        }
        yield {
            "event": "done",
            "requestId": request_id,
            "firstTokenMs": first_token_ms,
            "totalMs": int((perf_counter() - started) * 1000),
            "result": result,
        }
