from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Iterator
import uuid

from ..providers.llm_client import LLMRequestContext, OpenAICompatibleClient, get_llm_client


@dataclass(frozen=True)
class StreamingChatRequest:
    message: str
    recent_history: tuple[dict[str, str], ...] = ()
    request_id: str = ""
    session_id: str | None = None
    user_id: str | None = None


class StreamingChatService:
    """Framework-neutral streaming application service.

    It emits semantic events. HTTP/SSE framing belongs to the route adapter.
    """

    def __init__(self, client: OpenAICompatibleClient | None = None) -> None:
        self.client = client or get_llm_client()

    def stream(self, request: StreamingChatRequest) -> Iterator[dict[str, Any]]:
        request_id = request.request_id or uuid.uuid4().hex
        context = LLMRequestContext(request_id=request_id, session_id=request.session_id, user_id=request.user_id)
        messages: list[dict[str, Any]] = [{"role": "system", "content": "你是电商售后客服。回答准确、简洁，不承诺未经审核的退款结果。"}]
        messages.extend(request.recent_history[-20:])
        messages.append({"role": "user", "content": request.message})
        started = perf_counter()
        first_token_ms: int | None = None
        yield {"event": "start", "requestId": request_id, "provider": self.client._client.primary.provider, "model": self.client.config.model}
        for chunk in self.client.stream_chat(messages, temperature=0.2, max_tokens=600, context=context):
            choices = chunk.get("choices") or []
            usage = chunk.get("usage")
            if usage:
                yield {"event": "usage", "requestId": request_id, "usage": usage}
            for choice in choices:
                delta = choice.get("delta") or {}
                text = delta.get("content")
                if text:
                    if first_token_ms is None:
                        first_token_ms = int((perf_counter() - started) * 1000)
                    yield {"event": "token", "requestId": request_id, "text": text}
                if delta.get("tool_calls"):
                    yield {"event": "tool_call", "requestId": request_id, "toolCalls": delta["tool_calls"]}
                if choice.get("finish_reason"):
                    yield {"event": "finish", "requestId": request_id, "reason": choice["finish_reason"]}
        yield {
            "event": "done",
            "requestId": request_id,
            "firstTokenMs": first_token_ms,
            "totalMs": int((perf_counter() - started) * 1000),
        }
