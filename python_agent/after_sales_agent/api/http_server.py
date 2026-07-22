from __future__ import annotations

from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import logging
import os
import socket
import threading
from time import perf_counter
from typing import Any
from urllib.parse import parse_qs, urlparse

from after_sales_agent.config.environment import load_agent_env

# Load local secrets before importing modules that may construct global model
# clients. Local development defaults to .env overriding stale shell variables;
# set AGENT_ENV_OVERRIDE=false in deployment if injected env must win.
LOADED_ENV_PATH = load_agent_env()

from after_sales_agent.agents.emotion_service import EmotionAgent
from after_sales_agent.application.after_sales_workflow import LangGraphAfterSalesAgent
from after_sales_agent.application.knowledge_admin_service import KnowledgeAdminService
from after_sales_agent.application.knowledge_ingestion_service import KnowledgeParseError
from after_sales_agent.application.streaming_chat_service import StreamingChatRequest, StreamingChatService
from after_sales_agent.config.runtime_settings import resolve_agent_internal_token
from after_sales_agent.domain_models import AfterSalesRequest, Attachment, ConversationMessage, ImageReviewResult
from after_sales_agent.infra.agent_metrics import AGENT_RUNTIME_METRICS
from after_sales_agent.infra.request_tracing import TraceRecorder, install_trace_logging_filter, normalize_trace_id
from after_sales_agent.providers.llm_client import LLM_CLIENTS
from after_sales_agent.providers.model_prewarm_service import LocalModelPrewarmService
from after_sales_agent.providers.reranker_client import RERANKER_CLIENTS
from after_sales_agent.providers.vision_review_service import VisionReviewService
from after_sales_agent.utils.vision_serialization import serialize_image_review

# 配置日志 — 开发阶段输出所有 DEBUG 级别日志
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] trace=%(trace_id)s %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
install_trace_logging_filter()


LANGGRAPH_AGENT = LangGraphAfterSalesAgent()
VISION_SERVICE = VisionReviewService()
STREAMING_CHAT_SERVICE = StreamingChatService()
KNOWLEDGE_ADMIN_SERVICE = KnowledgeAdminService()
MODEL_PREWARM_SERVICE = LocalModelPrewarmService()
TRACE_HISTORY: deque[dict[str, object]] = deque(maxlen=120)
AGENT_INTERNAL_TOKEN = resolve_agent_internal_token()
AGENT_MAX_REQUEST_BYTES = max(1024, int(os.getenv("AGENT_MAX_REQUEST_BYTES", str(2 * 1024 * 1024))))
AGENT_CORS_ALLOW_ORIGIN = os.getenv("AGENT_CORS_ALLOW_ORIGIN", "").strip()


class RequestBodyReadError(ValueError):
    def __init__(self, error: str, *, status: int = 400, max_bytes: int | None = None) -> None:
        super().__init__(error)
        self.error = error
        self.status = status
        self.max_bytes = max_bytes


def read_http_request_body(headers: Any, stream: Any, *, max_bytes: int) -> bytes:
    transfer_encodings = {
        item.strip().lower()
        for item in str(headers.get("Transfer-Encoding") or "").split(",")
        if item.strip()
    }
    if "chunked" not in transfer_encodings:
        raw_length = headers.get("Content-Length", "0")
        try:
            content_length = int(raw_length or "0")
        except (TypeError, ValueError) as exc:
            raise RequestBodyReadError("invalid_content_length") from exc
        if content_length < 0:
            raise RequestBodyReadError("invalid_content_length")
        if content_length > max_bytes:
            raise RequestBodyReadError("request_too_large", status=413, max_bytes=max_bytes)
        body = stream.read(content_length)
        if len(body) != content_length:
            raise RequestBodyReadError("incomplete_request_body")
        return body

    body = bytearray()
    while True:
        size_line = stream.readline(128)
        if not size_line:
            raise RequestBodyReadError("incomplete_chunked_body")
        try:
            chunk_size = int(size_line.split(b";", 1)[0].strip(), 16)
        except ValueError as exc:
            raise RequestBodyReadError("invalid_chunk_size") from exc
        if chunk_size < 0:
            raise RequestBodyReadError("invalid_chunk_size")
        if chunk_size == 0:
            while True:
                trailer_line = stream.readline(8192)
                if trailer_line in {b"", b"\r\n", b"\n"}:
                    return bytes(body)
        if len(body) + chunk_size > max_bytes:
            raise RequestBodyReadError("request_too_large", status=413, max_bytes=max_bytes)
        chunk = stream.read(chunk_size)
        if len(chunk) != chunk_size:
            raise RequestBodyReadError("incomplete_chunked_body")
        body.extend(chunk)
        if stream.read(2) != b"\r\n":
            raise RequestBodyReadError("invalid_chunk_terminator")


class BoundedAgentHttpServer(ThreadingHTTPServer):
    """Threaded server with an execution gate for slow LLM requests."""

    daemon_threads = True

    def __init__(self, server_address, request_handler_class, max_concurrent_requests: int) -> None:
        super().__init__(server_address, request_handler_class)
        self.max_concurrent_requests = max(1, max_concurrent_requests)
        self._request_gate = threading.BoundedSemaphore(self.max_concurrent_requests)
        self._inflight_lock = threading.Lock()
        self._inflight = 0

    @property
    def inflight_requests(self) -> int:
        with self._inflight_lock:
            return self._inflight

    def verify_request(self, request, client_address) -> bool:
        if self._request_gate.acquire(blocking=False):
            with self._inflight_lock:
                self._inflight += 1
            return True
        payload = b'{"error":"agent_overloaded","message":"Agent service is busy; retry shortly."}'
        try:
            request.sendall(
                b"HTTP/1.1 429 Too Many Requests\r\n"
                b"Content-Type: application/json; charset=utf-8\r\n"
                b"Retry-After: 1\r\n"
                + f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode("ascii")
                + payload
            )
        except OSError:
            pass
        return False

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self._inflight_lock:
                self._inflight -= 1
            self._request_gate.release()


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def is_valid_internal_token(provided: str | None, expected: str | None = None) -> bool:
    """Validate the Java-to-Agent shared secret without timing-sensitive comparison."""
    configured = (expected if expected is not None else AGENT_INTERNAL_TOKEN or "").strip()
    candidate = (provided or "").strip()
    return bool(configured and candidate and hmac.compare_digest(candidate, configured))


def resolve_internal_request_token(headers: Any) -> str | None:
    """Accept the project header and Prometheus-compatible Bearer authentication."""
    internal_token = str(headers.get("X-Agent-Internal-Token") or "").strip()
    if internal_token:
        return internal_token
    authorization = str(headers.get("Authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def build_attachments(payload_attachments: list[Any] | tuple[Any, ...] | None) -> tuple[Attachment, ...]:
    attachments: list[Attachment] = []
    for item in payload_attachments or []:
        if isinstance(item, str):
            kind = item.strip()
            if kind:
                attachments.append(Attachment(kind=kind, name=f"{kind}.jpg"))
            continue
        if isinstance(item, dict):
            kind = str(item.get("kind") or "商品照片").strip()
            name = str(item.get("name") or f"{kind}.jpg").strip()
            file_url = item.get("file_url") or item.get("fileUrl") or item.get("url")
            attachments.append(Attachment(kind=kind, name=name, source=item.get("source"), file_url=file_url))
    return tuple(attachments)


def build_langgraph_entry_payload(data: dict[str, Any], emotion_context: dict[str, Any] | None = None) -> dict[str, Any]:
    selected = data.get("selected_order") if isinstance(data.get("selected_order"), dict) else {}
    order_id = (
        data.get("order_id")
        or selected.get("order_id")
        or ""
    )
    user_id = (
        data.get("user_id")
        or selected.get("user_id")
        or "0"
    )
    raw_client_context = data.get("client_context") if isinstance(data.get("client_context"), dict) else {}
    # Trust markers are assigned by the adapter, never accepted from an HTTP request body.
    client_context = {
        key: value
        for key, value in raw_client_context.items()
        if key not in {"source", "event_id", "trusted_invocation"}
    }
    client_context["source"] = "java_gateway"
    if selected:
        client_context = {
            **client_context,
            "selected_order_hint": {
                "order_id": selected.get("order_id"),
                "product_name": selected.get("product_name"),
                "merchant_code": selected.get("merchant_code"),
                "category": selected.get("category") or selected.get("product_category"),
                "status": selected.get("status"),
                "after_sales_status": selected.get("after_sales_status"),
                "uploaded_evidence": selected.get("uploaded_evidence") or [],
            },
        }
    if emotion_context:
        client_context = {
            **client_context,
            "emotion": emotion_context,
        }
    review_request_id = data.get("review_request_id")
    ticket_id = data.get("ticket_id")
    return {
        "user_id": str(user_id),
        "session_id": data.get("session_id"),
        "ticket_id": ticket_id,
        "review_request_id": review_request_id,
        "order_id": str(order_id) if order_id else "",
        "message": str(data.get("message") or ""),
        "attachments": list(data.get("attachments") or []),
        "recent_history": build_recent_history_payload(data.get("recent_history")),
        "history_summary": data.get("history_summary") if isinstance(data.get("history_summary"), dict) else {},
        "client_context": client_context,
    }


def build_recent_history_payload(payload_history: list[Any] | tuple[Any, ...] | None) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    for item in payload_history or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        if role == "service":
            role = "assistant"
        if role not in {"user", "assistant"}:
            continue
        content = str(item.get("content") or "").strip()
        if content:
            history.append({"role": role, "content": content})
    limit = max(1, int(os.getenv("AGENT_RECENT_HISTORY_LIMIT", "20")))
    return history[-limit:]


def build_recent_history_messages(payload_history: list[Any] | tuple[Any, ...] | None) -> tuple[ConversationMessage, ...]:
    messages: list[ConversationMessage] = []
    for item in payload_history or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        if role == "service":
            role = "assistant"
        if role not in {"user", "assistant"}:
            continue
        content = str(item.get("content") or "").strip()
        if content:
            messages.append(ConversationMessage(role=role, content=content))
    return tuple(messages[-8:])


def analyze_chat_emotion(data: dict[str, Any]) -> dict[str, Any] | None:
    logger = logging.getLogger("api_server.emotion")
    try:
        message = str(data.get("message") or "").strip()
        attachments = build_attachments(data.get("attachments"))
        if attachments and message in {"", "[图片]", "[image]"}:
            return None
        if not message and not attachments:
            return None
        logger.info(
            "emotion request message=%s attachments=%d session_id=%s order_id=%s",
            message[:200],
            len(attachments),
            data.get("session_id"),
            data.get("order_id") or "",
        )

        selected = data.get("selected_order") if isinstance(data.get("selected_order"), dict) else {}
        user_id = (
            data.get("user_id")
            or selected.get("user_id")
            or "0"
        )
        request = AfterSalesRequest(
            user_id=str(user_id),
            message=message or ("用户发送了图片" if attachments else ""),
            order_id=str(data.get("order_id") or selected.get("order_id") or "") or None,
            description=str(data.get("description") or "").strip() or None,
            item_opened=data.get("item_opened"),
            human_request_count=int(data.get("human_request_count") or 0),
            attachments=attachments,
        )
        history = build_recent_history_messages(data.get("recent_history"))
        emotion = EmotionAgent().analyze(
            request,
            recent_history=history,
            recent_user_messages=tuple(message.content for message in history if message.role == "user"),
        )
        result = {
            "label": emotion.label.value,
            "score": emotion.score,
            "confidence": emotion.confidence,
            "triggers": list(emotion.triggers),
            "need_human_priority": emotion.need_human_priority,
            "reply_tone": emotion.reply_tone,
            "comfort_prefix": emotion.comfort_prefix,
            "comfort_examples": list(emotion.comfort_examples),
        }
        logger.info("emotion final context=%s", json.dumps(result, ensure_ascii=False, default=str))
        return result
    except Exception as exc:
        logger.exception("emotion analyze failed error=%s", exc)
        return None


def record_trace_event(
    trace: TraceRecorder,
    *,
    path: str,
    order_id: str | None = None,
    session_id: int | None = None,
    reply_preview: str | None = None,
) -> None:
    event = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "path": path,
        "order_id": order_id or "",
        "session_id": session_id,
        "reply_preview": (reply_preview or "")[:120],
        "trace": trace.to_dict(),
    }
    TRACE_HISTORY.appendleft(event)
    AGENT_RUNTIME_METRICS.record_trace(path, event["trace"])
    logging.getLogger("api_server.trace").info(
        "agent_trace=%s", json.dumps(event, ensure_ascii=False, separators=(",", ":"), default=str)
    )


def fallback_image_review(exc: Exception) -> ImageReviewResult:
    return ImageReviewResult(
        success=False,
        items=(),
        all_clear=False,
        has_damage_area=False,
        has_outer_package=False,
        has_logistics_label=False,
        logistics_matches_order=False,
        courier_company="",
        tracking_number="",
        sender_name="",
        receiver_name="",
        missing_visual_evidence=("图片分析结果待补充",),
        summary="图片分析暂时异常，我会先根据您的描述继续处理，稍后补充图片分析结果。",
        raw={
            "mode": "review_images_exception",
            "error": exc.__class__.__name__,
            "message": str(exc),
        },
    )


class AgentApiHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/api/health":
            self._send_json({"ok": True})
            return
        if not self._ensure_internal_authorized():
            return
        if self.path.startswith("/api/traces"):
            self._send_json({"items": list(TRACE_HISTORY)})
            return
        if self.path.startswith("/api/metrics/prometheus"):
            self._send_prometheus()
            return
        if self.path.startswith("/api/metrics"):
            self._send_json(AGENT_RUNTIME_METRICS.snapshot())
            return
        if self.path.startswith("/api/knowledge/documents"):
            self._handle_knowledge_documents()
            return
        self._send_json({"error": "not_found"}, status=404)

    def do_POST(self) -> None:
        if not self._ensure_internal_authorized():
            return
        try:
            self._raw_request_body = read_http_request_body(
                self.headers,
                self.rfile,
                max_bytes=AGENT_MAX_REQUEST_BYTES,
            )
        except RequestBodyReadError as exc:
            payload: dict[str, Any] = {"error": exc.error}
            if exc.max_bytes is not None:
                payload["max_bytes"] = exc.max_bytes
            self._send_json(payload, status=exc.status)
            return
        if self.path == "/api/chat":
            self._handle_chat()
            return
        if self.path == "/api/chat/stream":
            self._handle_chat_stream()
            return
        if self.path == "/api/analyze/emotion":
            self._handle_analyze_emotion()
            return
        if self.path == "/api/review-images":
            self._handle_review_images()
            return
        if self.path == "/api/knowledge/retrieve":
            self._handle_knowledge_retrieve()
            return
        if self.path == "/api/knowledge/parse":
            self._handle_knowledge_parse()
            return
        if self.path == "/api/knowledge/reindex":
            self._handle_knowledge_reindex()
            return
        if self.path == "/api/embeddings":
            self._handle_generate_embeddings()
            return
        self._send_json({"error": "not_found"}, status=404)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json_body(self) -> dict[str, Any]:
        raw_body = getattr(self, "_raw_request_body", None)
        if raw_body is None:
            raw_body = read_http_request_body(self.headers, self.rfile, max_bytes=AGENT_MAX_REQUEST_BYTES)
        body = raw_body.decode("utf-8")
        return json.loads(body or "{}")

    def _trace_id(self) -> str:
        trace_id = getattr(self, "_request_trace_id", None)
        if trace_id:
            return trace_id
        trace_id = normalize_trace_id(self.headers.get("X-Trace-Id"))
        self._request_trace_id = trace_id
        return trace_id

    def _ensure_internal_authorized(self) -> bool:
        if not AGENT_INTERNAL_TOKEN:
            self._send_json(
                {"error": "agent_auth_not_configured", "message": "Agent internal authentication is not configured."},
                status=503,
            )
            return False
        if not is_valid_internal_token(resolve_internal_request_token(self.headers)):
            self._send_json({"error": "unauthorized"}, status=401)
            return False
        return True

    def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("X-Trace-Id", self._trace_id())
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, socket.error):
            return

    def _send_prometheus(self) -> None:
        content, content_type = AGENT_RUNTIME_METRICS.prometheus_payload()
        self.send_response(200)
        self.send_header("X-Trace-Id", self._trace_id())
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, socket.error):
            return

    def _send_cors_headers(self) -> None:
        if not AGENT_CORS_ALLOW_ORIGIN:
            return
        self.send_header("Access-Control-Allow-Origin", AGENT_CORS_ALLOW_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Agent-Internal-Token, Authorization")

    def _write_sse(self, event: dict[str, Any]) -> None:
        event_name = str(event.get("event") or "message")
        data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        self.wfile.write(f"event: {event_name}\ndata: {data}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _handle_chat_stream(self) -> None:
        data = self._read_json_body()
        message = str(data.get("message") or "").strip()
        if not message:
            self._send_json({"error": "message_required"}, status=400)
            return
        history = tuple(build_recent_history_payload(data.get("recent_history")))
        request = StreamingChatRequest(
            message=message,
            recent_history=history,
            request_id=str(data.get("request_id") or ""),
            session_id=str(data.get("session_id") or "") or None,
            user_id=str(data.get("user_id") or "") or None,
        )
        self.send_response(200)
        self._send_cors_headers()
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("X-Trace-Id", self._trace_id())
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for event in STREAMING_CHAT_SERVICE.stream(request):
                self._write_sse(event)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, socket.error):
            logging.getLogger("api_server.stream").info("stream_client_disconnected request_id=%s", request.request_id)
        except Exception as exc:
            logging.getLogger("api_server.stream").exception("stream_failed request_id=%s", request.request_id)
            try:
                self._write_sse({"event": "error", "requestId": request.request_id, "error": exc.__class__.__name__, "message": "模型流式响应暂时不可用"})
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, socket.error):
                pass
        finally:
            self.close_connection = True

    def _handle_chat(self) -> None:
        trace = TraceRecorder(request_type="chat", trace_id=self._trace_id())
        with trace.step("read_request_body"):
            data = self._read_json_body()

        logger = logging.getLogger("api_server")
        msg_preview = str(data.get("message") or "")[:150]
        logger.info("📨 收到 chat 请求 message=%s attachments=%d order_id=%s",
                    msg_preview,
                    len(data.get("attachments") or []),
                    data.get("order_id") or "")

        with trace.step("emotion_analyze"):
            emotion_context = analyze_chat_emotion(data)
        if emotion_context is not None:
            trace.set_meta(
                emotion_label=emotion_context.get("label"),
                emotion_score=emotion_context.get("score"),
                emotion_need_human_priority=emotion_context.get("need_human_priority"),
            )
            logger.info("😊 情绪分析: label=%s score=%s",
                        emotion_context.get("label"), emotion_context.get("score"))

        try:
            with trace.step("langgraph_agent"):
                result = LANGGRAPH_AGENT.handle(
                    build_langgraph_entry_payload(data, emotion_context),
                    trace_recorder=trace,
                )
        except Exception as exc:
            logging.getLogger("api_server").exception("❌ langgraph agent 执行异常: %s", exc)
            trace.set_meta(
                error=exc.__class__.__name__,
                error_message=str(exc),
            )
            self._send_json(
                {
                    "error": "agent_runtime_error",
                    "message": str(exc),
                    "runtime": "langgraph_react",
                    "trace": trace.to_dict(),
                },
                status=503,
            )
            record_trace_event(
                trace,
                path="/api/chat",
                order_id=str(data.get("order_id") or ""),
                reply_preview=str(exc),
            )
            return

        payload = {
            "assistant_reply": result.get("assistant_reply") or "",
            "intent": "agent_managed",
            "suggested_action": "langgraph_agent",
            "evidence_needed": result.get("evidence_needed") or [],
            "need_human": bool(result.get("need_human")),
            "session_mode": result.get("session_mode") or "AI",
            "ticket": result.get("ticket"),
            "handoff_summary": None,
            "emotion": emotion_context,
            "image_review": None,
            "persistence": result.get("persistence"),
            "tool_trace": result.get("tool_trace") or [],
            "raw": {
                **(result.get("raw") or {}),
                "emotion_integrated": bool(emotion_context),
                "emotion_need_human_priority": (
                    emotion_context.get("need_human_priority") if emotion_context is not None else None
                ),
            },
            "trace": trace.to_dict(),
        }
        reply_logger = logging.getLogger("api_server")
        reply_logger.info("📤 响应: need_human=%s session_mode=%s reply=%s evidence_needed=%s",
                         payload["need_human"],
                         payload["session_mode"],
                         payload["assistant_reply"][:150],
                         payload["evidence_needed"])
        self._send_json(payload)
        record_trace_event(
            trace,
            path="/api/chat",
            order_id=str(data.get("order_id") or ""),
            session_id=_safe_int((result.get("persistence") or {}).get("session_id")),
            reply_preview=payload["assistant_reply"],
        )
        return

    def _handle_review_images(self) -> None:
        trace = TraceRecorder(request_type="review_images", trace_id=self._trace_id())
        with trace.step("read_request_body"):
            data = self._read_json_body()

        attachments = build_attachments(data.get("attachments"))
        order_hint = str(data.get("order_hint") or "").strip() or None
        trace.set_meta(
            attachment_count=len(attachments),
            attachment_kinds=[attachment.kind for attachment in attachments],
            vision_model=VISION_SERVICE.client.config.model,
        )
        try:
            VISION_SERVICE.bind_trace(trace)
            with trace.step("review_images", order_hint=bool(order_hint)):
                image_review = VISION_SERVICE.review_attachments(attachments, order_hint=order_hint)
        except Exception as exc:
            image_review = fallback_image_review(exc)
        finally:
            VISION_SERVICE.bind_trace(None)

        self._send_json(
            {
                "image_review": serialize_image_review(image_review),
                "trace": trace.to_dict(),
            }
        )
        record_trace_event(
            trace,
            path="/api/review-images",
            reply_preview=image_review.summary if image_review else "",
        )

    def _handle_analyze_emotion(self) -> None:
        trace = TraceRecorder(request_type="analyze_emotion", trace_id=self._trace_id())
        with trace.step("read_request_body"):
            data = self._read_json_body()

        emotion_context = analyze_chat_emotion(data)
        payload = {
            "emotion_label": emotion_context.get("label") if emotion_context else None,
            "emotion_score": emotion_context.get("score") if emotion_context else None,
            "emotion_confidence": emotion_context.get("confidence") if emotion_context else None,
            "need_human_priority": emotion_context.get("need_human_priority") if emotion_context else None,
            "triggers": emotion_context.get("triggers") if emotion_context else None,
            "reply_tone": emotion_context.get("reply_tone") if emotion_context else None,
            "trace": trace.to_dict(),
        }
        self._send_json(payload)
        record_trace_event(
            trace,
            path="/api/analyze/emotion",
            order_id=str(data.get("order_id") or ""),
            session_id=_safe_int(data.get("session_id")),
            reply_preview=str(payload["emotion_label"] or ""),
        )

    def _handle_knowledge_retrieve(self) -> None:
        data = self._read_json_body()
        self._send_json(KNOWLEDGE_ADMIN_SERVICE.retrieve(data))

    def _handle_knowledge_parse(self) -> None:
        try:
            self._send_json(KNOWLEDGE_ADMIN_SERVICE.parse_document(self._read_json_body()))
        except KnowledgeParseError as exc:
            error = str(exc)
            statuses = {
                "UNSUPPORTED_FILE_TYPE": 415,
                "PDF_ENCRYPTED": 422,
                "PDF_TEXT_LAYER_MISSING": 422,
                "FILE_DECODE_FAILED": 422,
                "DOCUMENT_CONTENT_EMPTY": 422,
                "DOCUMENT_CHUNKING_FAILED": 422,
            }
            self._send_json({"error": error if error in statuses else "FILE_DECODE_FAILED"}, status=statuses.get(error, 422))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json({"error": "FILE_DECODE_FAILED"}, status=422)
        except Exception:
            logging.getLogger("api_server.knowledge_parse").exception("knowledge parse failed")
            self._send_json({"error": "knowledge_parse_failed"}, status=500)

    def _handle_knowledge_reindex(self) -> None:
        try:
            self._send_json(KNOWLEDGE_ADMIN_SERVICE.reindex())
        except Exception as exc:
            self._send_json(
                {"ok": False, "error": exc.__class__.__name__, "message": str(exc)},
                status=503,
            )

    def _handle_generate_embeddings(self) -> None:
        """生成文本embeddings"""
        try:
            data = self._read_json_body()
            chunks = data.get("chunks", [])
            self._send_json(KNOWLEDGE_ADMIN_SERVICE.generate_embeddings(chunks))
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
        except Exception as exc:
            self._send_json(
                {"ok": False, "error": exc.__class__.__name__, "message": str(exc)},
                status=500,
            )

    def _handle_knowledge_documents(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        limit = max(1, min(int((params.get("limit") or ["50"])[0]), 200))
        try:
            self._send_json(KNOWLEDGE_ADMIN_SERVICE.list_documents(limit=limit))
        except RuntimeError as exc:
            message = str(exc)
            error = "pgvector_error"
            if message.startswith("pg_dependency_missing:"):
                error = "pg_dependency_missing"
                message = message.removeprefix("pg_dependency_missing:").strip()
            elif message.startswith("pgvector_error:"):
                message = message.removeprefix("pgvector_error:").strip()
            self._send_json({"error": error, "message": message}, status=503)
            return

def close_application_resources() -> None:
    LLM_CLIENTS.close()
    RERANKER_CLIENTS.close()


def main() -> None:
    started_at = perf_counter()
    host = os.getenv("AGENT_HOST", "127.0.0.1")
    port = int(os.getenv("AGENT_PORT", "8000"))
    max_concurrent_requests = int(os.getenv("AGENT_MAX_CONCURRENT_REQUESTS", "2"))
    server = BoundedAgentHttpServer((host, port), AgentApiHandler, max_concurrent_requests)
    threading.Thread(target=MODEL_PREWARM_SERVICE.prewarm, name="agent-model-prewarm", daemon=True).start()
    print(f"Agent API running at http://{host}:{port}/api ({int((perf_counter() - started_at) * 1000)}ms)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        close_application_resources()


if __name__ == "__main__":
    main()
