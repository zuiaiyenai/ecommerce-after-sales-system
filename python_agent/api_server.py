from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
from time import perf_counter
from typing import Any

from after_sales_agent import (
    AfterSalesStatus,
    Attachment,
    ConversationContext,
    ConversationMessage,
    ConversationPersistenceService,
    DatabaseConfig,
    ImageReviewResult,
    MySQLRepository,
    Order,
    OrderItem,
    OrderStatus,
    QwenReturnService,
    ReturnConversationService,
)
from after_sales_agent.infra.trace import TraceRecorder
from after_sales_agent.utils.vision_utils import parse_image_review_payload, serialize_image_review


SERVICE = ReturnConversationService()
QWEN_SERVICE = QwenReturnService()
TRACE_HISTORY: deque[dict[str, object]] = deque(maxlen=120)


def init_repository() -> tuple[MySQLRepository | None, ConversationPersistenceService | None]:
    try:
        repo = MySQLRepository(DatabaseConfig.from_env_file())
        return repo, ConversationPersistenceService(repo)
    except Exception:
        return None, None


DB_REPOSITORY, PERSISTENCE = init_repository()


def sample_orders() -> list[Order]:
    now = datetime.now()
    return [
        Order(
            order_id="202405220123456789",
            user_id="u1001",
            status=OrderStatus.DELIVERED,
            amount=39.0,
            created_at=now - timedelta(days=5),
            shipped_at=now - timedelta(days=4),
            delivered_at=now - timedelta(days=2),
            items=(OrderItem("sku-100", "轻音降噪无线耳机 X3", "数码", 1, 39.0),),
            after_sales_status=AfterSalesStatus.NOT_APPLIED,
        ),
    ]


def load_order_cache() -> dict[str, Order]:
    if DB_REPOSITORY is not None:
        try:
            return {order.order_id: order for order in DB_REPOSITORY.list_orders(limit=20)}
        except Exception:
            pass
    return {order.order_id: order for order in sample_orders()}


ORDER_MAP = load_order_cache()


def build_order_from_payload(data: dict[str, Any]) -> Order | None:
    selected = data.get("selected_order")
    if not isinstance(selected, dict):
        return None

    status_map = {
        "paid": OrderStatus.PAID,
        "shipped": OrderStatus.SHIPPED,
        "delivered": OrderStatus.DELIVERED,
        "completed": OrderStatus.COMPLETED,
        "after_sales": OrderStatus.AFTER_SALES,
        "refunded": OrderStatus.REFUNDED,
    }
    after_sales_map = {
        "not_applied": AfterSalesStatus.NOT_APPLIED,
        "submitted": AfterSalesStatus.SUBMITTED,
        "waiting_evidence": AfterSalesStatus.WAITING_EVIDENCE,
        "merchant_review": AfterSalesStatus.MERCHANT_REVIEW,
        "platform_review": AfterSalesStatus.PLATFORM_REVIEW,
        "approved": AfterSalesStatus.APPROVED,
        "rejected": AfterSalesStatus.REJECTED,
        "waiting_return": AfterSalesStatus.WAITING_RETURN,
        "refund_processing": AfterSalesStatus.REFUND_PROCESSING,
        "exchange_processing": AfterSalesStatus.EXCHANGE_PROCESSING,
        "completed": AfterSalesStatus.COMPLETED,
        "human_processing": AfterSalesStatus.HUMAN_PROCESSING,
    }

    order_id = str(selected.get("order_id") or "").strip()
    if not order_id:
        return None
    status = status_map.get(str(selected.get("status") or "").strip().lower())
    if status is None:
        return None

    amount = float(selected.get("amount") or 0)
    return Order(
        order_id=order_id,
        user_id=str(selected.get("user_id") or data.get("user_id") or "").strip(),
        status=status,
        amount=amount,
        created_at=datetime.now() - timedelta(days=5),
        shipped_at=datetime.now() - timedelta(days=4),
        items=(
            OrderItem(
                "sku-dynamic",
                str(selected.get("product_name") or "未知商品").strip(),
                str(selected.get("category") or "未知分类").strip(),
                1,
                amount,
            ),
        ),
        has_open_after_sales=bool(selected.get("has_open_after_sales")),
        after_sales_status=after_sales_map.get(
            str(selected.get("after_sales_status") or "not_applied").strip().lower(),
            AfterSalesStatus.NOT_APPLIED,
        ),
        refund_status=str(selected.get("refund_status") or "未开始"),
        logistics_status=str(selected.get("logistics_status") or "待更新"),
        uploaded_evidence=tuple(selected.get("uploaded_evidence") or ()),
        merchant_rejected_before=bool(selected.get("merchant_rejected_before")),
    )


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


def build_recent_history(payload_history: list[Any] | tuple[Any, ...] | None) -> tuple[ConversationMessage, ...]:
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


def resolve_user_id(data: dict[str, Any], selected_order: Order | None) -> str:
    if selected_order is not None and selected_order.user_id:
        return selected_order.user_id
    selected = data.get("selected_order")
    if isinstance(selected, dict) and selected.get("user_id"):
        return str(selected["user_id"])
    return str(data.get("user_id") or "anonymous")


def build_trace_meta(*, attachments: tuple[Attachment, ...], skip_image_review: bool) -> dict[str, object]:
    return {
        "attachment_count": len(attachments),
        "attachment_kinds": [attachment.kind for attachment in attachments],
        "skip_image_review": skip_image_review,
        "vision_model": SERVICE.vision_service.client.config.model,
        "text_model": QWEN_SERVICE.client.config.model,
    }


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
        self._send_json({"error": "not_found"}, status=404)

    def do_POST(self) -> None:
        if self.path == "/api/chat":
            self._handle_chat()
            return
        if self.path == "/api/review-images":
            self._handle_review_images()
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

        order_id = data.get("order_id")
        session_id = data.get("session_id")
        attachments = build_attachments(data.get("attachments"))
        skip_image_review = bool(data.get("skip_image_review"))
        image_review = parse_image_review_payload(data.get("image_review"))
        trace.set_meta(**build_trace_meta(attachments=attachments, skip_image_review=skip_image_review))

        selected_order = build_order_from_payload(data)
        if selected_order is None and order_id:
            selected_order = ORDER_MAP.get(str(order_id))

        order_hint = None
        if selected_order is not None:
            product_name = selected_order.items[0].product_name if selected_order.items else ""
            order_hint = f"订单号：{selected_order.order_id}；商品：{product_name}"

        if image_review is None and not skip_image_review:
            SERVICE.vision_service.bind_trace(trace)
            with trace.step("review_images", order_hint=bool(order_hint)):
                image_review = SERVICE.review_images(attachments, order_hint=order_hint)
            SERVICE.vision_service.bind_trace(None)
        elif image_review is not None:
            trace.set_meta(image_review_source="frontend_cached")
        else:
            trace.set_meta(image_review_source="skipped")

        recent_history = build_recent_history(data.get("recent_history"))
        if DB_REPOSITORY is not None and session_id is not None:
            try:
                with trace.step("load_recent_history", session_id=int(session_id), limit=6):
                    db_history = DB_REPOSITORY.get_recent_messages(int(session_id), limit=6)
                    if not recent_history:
                        recent_history = db_history
            except Exception:
                pass

        context = ConversationContext(
            user_id=resolve_user_id(data, selected_order),
            selected_order=selected_order,
            message=str(data.get("message") or ""),
            session_id=int(session_id) if session_id is not None else None,
            description=data.get("description"),
            item_opened=data.get("item_opened"),
            human_request_count=int(data.get("human_request_count") or 0),
            attachments=attachments,
            image_review=image_review,
            recent_history=recent_history,
        )

        QWEN_SERVICE.bind_trace(trace)
        with trace.step("generate_assistant_reply"):
            result = QWEN_SERVICE.handle(context)
        QWEN_SERVICE.bind_trace(None)

        persistence_result = None
        if PERSISTENCE is not None:
            try:
                with trace.step("persist_interaction"):
                    persistence_result = PERSISTENCE.persist_interaction(
                        context=context,
                        result=result,
                        source_channel="H5",
                    )
            except Exception:
                persistence_result = None

        ticket = result.fallback_result.ticket
        payload = {
            "assistant_reply": result.assistant_reply,
            "intent": result.intent,
            "suggested_action": result.suggested_action,
            "evidence_needed": list(result.evidence_needed),
            "fallback_decision": result.fallback_result.decision.value,
            "fallback_progress_hint": result.fallback_result.progress_hint,
            "fallback_need_human": result.fallback_result.need_human,
            "ticket": {
                "ticket_id": ticket.ticket_id,
                "status": ticket.status.value,
                "expected_hours": ticket.expected_hours,
            }
            if ticket
            else None,
            "handoff_summary": result.fallback_result.handoff_summary,
            "emotion": self._serialize_emotion(result),
            "image_review": serialize_image_review(image_review),
            "persistence": {
                "session_id": persistence_result.session_id,
                "session_no": persistence_result.session_no,
                "user_message_id": persistence_result.user_message_id,
                "assistant_message_id": persistence_result.assistant_message_id,
                "ticket_log_id": persistence_result.ticket_log_id,
                "notice_id": persistence_result.notice_id,
            }
            if persistence_result
            else None,
            "raw": result.raw,
            "trace": trace.to_dict(),
        }
        self._send_json(payload)
        record_trace_event(
            trace,
            path="/api/chat",
            order_id=str(order_id or ""),
            session_id=persistence_result.session_id
            if persistence_result
            else (int(session_id) if session_id is not None else None),
            reply_preview=result.assistant_reply,
        )

    def _handle_review_images(self) -> None:
        trace = TraceRecorder(request_type="review_images")
        with trace.step("read_request_body"):
            data = self._read_json_body()

        attachments = build_attachments(data.get("attachments"))
        order_hint = str(data.get("order_hint") or "").strip() or None
        trace.set_meta(
            attachment_count=len(attachments),
            attachment_kinds=[attachment.kind for attachment in attachments],
            vision_model=SERVICE.vision_service.client.config.model,
        )
        try:
            SERVICE.vision_service.bind_trace(trace)
            with trace.step("review_images", order_hint=bool(order_hint)):
                image_review = SERVICE.review_images(attachments, order_hint=order_hint)
        except Exception as exc:
            image_review = fallback_image_review(exc)
        finally:
            SERVICE.vision_service.bind_trace(None)

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

    @staticmethod
    def _serialize_emotion(result: Any) -> dict[str, Any] | None:
        emotion = result.fallback_result.emotion
        if emotion is None:
            return None
        return {
            "label": emotion.label.value,
            "score": emotion.score,
            "triggers": list(emotion.triggers),
            "need_human_priority": emotion.need_human_priority,
            "reply_tone": emotion.reply_tone,
            "comfort_prefix": emotion.comfort_prefix,
        }


if __name__ == "__main__":
    started_at = perf_counter()
    server = ThreadingHTTPServer(("127.0.0.1", 8000), AgentApiHandler)
    print(f"Agent API running at http://127.0.0.1:8000/api ({int((perf_counter() - started_at) * 1000)}ms)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
