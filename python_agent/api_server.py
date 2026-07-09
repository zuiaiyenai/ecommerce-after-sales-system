from __future__ import annotations

from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import socket
from time import perf_counter
from typing import Any
from urllib.parse import parse_qs, urlparse

# 配置日志 — 开发阶段输出所有 DEBUG 级别日志
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# 第三方库日志保持 WARNING，避免噪音
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

from after_sales_agent import AfterSalesRequest, Attachment, ConversationMessage, EmotionAgent, ImageReviewResult
from after_sales_agent.infra.trace import TraceRecorder
from after_sales_agent.langgraph_runtime import LangGraphAfterSalesAgent
from after_sales_agent.services.pgvector_retrieval import PgVectorConfig, PgVectorKnowledgeRetriever
from after_sales_agent.services.vision import VisionReviewService
from after_sales_agent.utils.vision_utils import serialize_image_review


LANGGRAPH_AGENT = LangGraphAfterSalesAgent()
VISION_SERVICE = VisionReviewService()
TRACE_HISTORY: deque[dict[str, object]] = deque(maxlen=120)


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
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
            attachments.append(Attachment(kind=kind, name=name, source=item.get("source")))
    return tuple(attachments)


def build_langgraph_entry_payload(data: dict[str, Any], emotion_context: dict[str, Any] | None = None) -> dict[str, Any]:
    selected = data.get("selected_order") if isinstance(data.get("selected_order"), dict) else {}
    order_id = (
        data.get("order_id")
        or data.get("orderId")
        or selected.get("order_id")
        or selected.get("orderId")
        or ""
    )
    user_id = (
        data.get("user_id")
        or data.get("userId")
        or selected.get("user_id")
        or selected.get("userId")
        or "0"
    )
    client_context = data.get("client_context") if isinstance(data.get("client_context"), dict) else {}
    if selected:
        client_context = {
            **client_context,
            "selected_order_hint": {
                "order_id": selected.get("order_id") or selected.get("orderId"),
                "product_name": selected.get("product_name") or selected.get("productName"),
                "merchant_code": selected.get("merchant_code") or selected.get("merchantCode"),
                "category": selected.get("category") or selected.get("product_category") or selected.get("productCategory"),
                "status": selected.get("status"),
                "after_sales_status": selected.get("after_sales_status") or selected.get("afterSalesStatus"),
                "uploaded_evidence": selected.get("uploaded_evidence") or selected.get("uploadedEvidence") or [],
            },
        }
    if emotion_context:
        client_context = {
            **client_context,
            "emotion": emotion_context,
        }
    return {
        "user_id": str(user_id),
        "session_id": data.get("session_id") or data.get("sessionId"),
        "order_id": str(order_id) if order_id else "",
        "message": str(data.get("message") or ""),
        "attachments": list(data.get("attachments") or []),
        "recent_history": build_recent_history_payload(data.get("recent_history") or data.get("recentHistory")),
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
    return history[-8:]


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
        if not message and not attachments:
            return None
        logger.info(
            "emotion request message=%s attachments=%d session_id=%s order_id=%s",
            message[:200],
            len(attachments),
            data.get("session_id") or data.get("sessionId"),
            data.get("order_id") or data.get("orderId") or "",
        )

        selected = data.get("selected_order") if isinstance(data.get("selected_order"), dict) else {}
        user_id = (
            data.get("user_id")
            or data.get("userId")
            or selected.get("user_id")
            or selected.get("userId")
            or "0"
        )
        request = AfterSalesRequest(
            user_id=str(user_id),
            message=message or ("用户发送了图片" if attachments else ""),
            order_id=str(data.get("order_id") or data.get("orderId") or selected.get("order_id") or selected.get("orderId") or "") or None,
            description=str(data.get("description") or "").strip() or None,
            item_opened=data.get("item_opened"),
            human_request_count=int(data.get("human_request_count") or 0),
            attachments=attachments,
        )
        history = build_recent_history_messages(data.get("recent_history") or data.get("recentHistory"))
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
    TRACE_HISTORY.appendleft(
        {
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "path": path,
            "order_id": order_id or "",
            "session_id": session_id,
            "reply_preview": (reply_preview or "")[:120],
            "trace": trace.to_dict(),
        }
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
        if self.path.startswith("/api/traces"):
            self._send_json({"items": list(TRACE_HISTORY)})
            return
        if self.path.startswith("/api/knowledge/documents"):
            self._handle_knowledge_documents()
            return
        self._send_json({"error": "not_found"}, status=404)

    def do_POST(self) -> None:
        if self.path == "/api/chat":
            self._handle_chat()
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
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length).decode("utf-8")
        return json.loads(body or "{}")

    def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, socket.error):
            return

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _handle_chat(self) -> None:
        trace = TraceRecorder(request_type="chat")
        with trace.step("read_request_body"):
            data = self._read_json_body()

        logger = logging.getLogger("api_server")
        msg_preview = str(data.get("message") or "")[:150]
        logger.info("📨 收到 chat 请求 message=%s attachments=%d order_id=%s",
                    msg_preview,
                    len(data.get("attachments") or []),
                    data.get("order_id") or data.get("orderId") or "")

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
                result = LANGGRAPH_AGENT.handle(build_langgraph_entry_payload(data, emotion_context))
        except Exception as exc:
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
                order_id=str(data.get("order_id") or data.get("orderId") or ""),
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
            order_id=str(data.get("order_id") or data.get("orderId") or ""),
            session_id=_safe_int((result.get("persistence") or {}).get("session_id")),
            reply_preview=payload["assistant_reply"],
        )
        return

    def _handle_review_images(self) -> None:
        trace = TraceRecorder(request_type="review_images")
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
        trace = TraceRecorder(request_type="analyze_emotion")
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
            order_id=str(data.get("order_id") or data.get("orderId") or ""),
            session_id=_safe_int(data.get("session_id") or data.get("sessionId")),
            reply_preview=str(payload["emotion_label"] or ""),
        )

    def _handle_knowledge_retrieve(self) -> None:
        data = self._read_json_body()
        sources = data.get("sources") if isinstance(data.get("sources"), list) else []
        source_type = sources[0] if len(sources) == 1 else data.get("source_type") or data.get("sourceType")
        top_k = data.get("topK") or data.get("top_k")
        result = PgVectorKnowledgeRetriever().retrieve(
            query=str(data.get("query") or ""),
            merchant_code=data.get("merchantCode") or data.get("merchant_code"),
            product_category=data.get("productCategory") or data.get("product_category"),
            scene=data.get("scene"),
            intent=data.get("intent"),
            source_type=source_type,
            top_k=top_k,
        )
        hits = [
            {
                "source_type": hit.get("metadata", {}).get("source_type") or hit.get("source_type"),
                "source_code": hit.get("source_code"),
                "title": hit.get("title"),
                "summary": hit.get("snippet"),
                "snippet": hit.get("snippet"),
                "score": hit.get("score"),
                "tags": hit.get("metadata", {}).get("tags") or [],
                "metadata": hit.get("metadata") or {},
            }
            for hit in result.get("hits", [])
        ]
        self._send_json(
            {
                "query": result.get("query") or data.get("query") or "",
                "retrieval_mode": result.get("mode") or "pgvector",
                "total_hits": len(hits),
                "hits": hits,
                "trace": result.get("trace") or {},
            }
        )

    def _handle_knowledge_reindex(self) -> None:
        try:
            from ingest_pgvector_knowledge import reindex

            result = reindex()
            self._send_json({"ok": True, **result})
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

            if not isinstance(chunks, list) or not chunks:
                self._send_json({"error": "chunks must be a non-empty list"}, status=400)
                return

            # 使用PgVectorKnowledgeRetriever的embedding能力
            from after_sales_agent.services.pgvector_retrieval import PgVectorKnowledgeRetriever, PgVectorConfig

            retriever = PgVectorKnowledgeRetriever(PgVectorConfig.from_env())

            # 批量生成embeddings
            embeddings = retriever.embed_many([str(chunk) for chunk in chunks])

            self._send_json({
                "ok": True,
                "embeddings": embeddings,
                "count": len(embeddings),
                "dimensions": len(embeddings[0]) if embeddings and embeddings[0] else 0
            })
        except Exception as exc:
            self._send_json(
                {"ok": False, "error": exc.__class__.__name__, "message": str(exc)},
                status=500,
            )

    def _handle_knowledge_documents(self) -> None:
        try:
            import psycopg
        except Exception as exc:
            self._send_json({"error": "pg_dependency_missing", "message": str(exc)}, status=503)
            return

        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        limit = max(1, min(int((params.get("limit") or ["50"])[0]), 200))
        config = PgVectorConfig.from_env()
        try:
            with psycopg.connect(config.dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, source_type, source_code, merchant_code, title, product_category,
                               scene, intent, policy_version, tags, metadata, status, updated_at
                        FROM knowledge_document
                        ORDER BY id
                        LIMIT %s
                        """,
                        (limit,),
                    )
                    rows = cur.fetchall()
        except Exception as exc:
            self._send_json({"error": "pgvector_error", "message": str(exc)}, status=503)
            return
        self._send_json(
            {
                "items": [
                    {
                        "id": row[0],
                        "source_type": row[1],
                        "source_code": row[2],
                        "merchant_code": row[3],
                        "title": row[4],
                        "product_category": row[5],
                        "scene": row[6],
                        "intent": row[7],
                        "policy_version": row[8],
                        "tags": row[9] or [],
                        "metadata": row[10] or {},
                        "status": row[11],
                        "updated_at": row[12].isoformat() if row[12] else None,
                    }
                    for row in rows
                ]
            }
        )

if __name__ == "__main__":
    started_at = perf_counter()
    server = ThreadingHTTPServer(("127.0.0.1", 8000), AgentApiHandler)
    print(f"Agent API running at http://127.0.0.1:8000/api ({int((perf_counter() - started_at) * 1000)}ms)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
