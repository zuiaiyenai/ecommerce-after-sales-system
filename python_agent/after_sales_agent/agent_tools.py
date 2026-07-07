from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Callable

from .models import Attachment
from .services.java_tool_client import JavaToolClient, JavaToolError
from .services.pgvector_retrieval import PgVectorKnowledgeRetriever
from .services.vision import VisionReviewService
from .utils.vision_utils import serialize_image_review


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    name: str
    data: Any = None
    error: str | None = None


@dataclass
class AfterSalesTools:
    java: JavaToolClient = field(default_factory=JavaToolClient)
    retriever: PgVectorKnowledgeRetriever = field(default_factory=PgVectorKnowledgeRetriever)
    vision: VisionReviewService = field(default_factory=VisionReviewService)

    def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        tool = self.registry().get(name)
        if tool is None:
            return ToolResult(ok=False, name=name, error=f"unknown tool: {name}")
        try:
            return ToolResult(ok=True, name=name, data=tool(arguments or {}))
        except (JavaToolError, ValueError) as exc:
            return ToolResult(ok=False, name=name, error=str(exc))
        except Exception as exc:
            return ToolResult(ok=False, name=name, error=f"{exc.__class__.__name__}: {exc}")

    def registry(self) -> dict[str, Callable[[dict[str, Any]], Any]]:
        return {
            "search_user_orders": self.search_user_orders,
            "get_order_detail": self.get_order_detail,
            "get_existing_after_sales": self.get_existing_after_sales,
            "get_merchant_policy": self.get_merchant_policy,
            "retrieve_knowledge": self.retrieve_knowledge,
            "review_images": self.review_images,
            "create_after_sales_ticket": self.create_after_sales_ticket,
            "handoff_to_human": self.handoff_to_human,
            "append_chat_message": self.append_chat_message,
            "request_missing_evidence": self.request_missing_evidence,
        }

    def tool_specs(self) -> list[dict[str, Any]]:
        return [
            {"name": "search_user_orders", "description": "Search the current user's orders by keyword/status."},
            {"name": "get_order_detail", "description": "Get one owned order by id or order number."},
            {"name": "get_existing_after_sales", "description": "Find an open after-sales ticket for an order."},
            {"name": "get_merchant_policy", "description": "Read merchant after-sales policy configuration."},
            {"name": "retrieve_knowledge", "description": "Retrieve RAG knowledge from pgvector with metadata filters."},
            {"name": "review_images", "description": "Analyze uploaded evidence images."},
            {"name": "create_after_sales_ticket", "description": "Create an after-sales ticket through Java business validation."},
            {"name": "handoff_to_human", "description": "Switch or create a session in human-service mode."},
            {"name": "append_chat_message", "description": "Append one chat message through Java business API."},
            {"name": "request_missing_evidence", "description": "Persist an assistant request for missing evidence."},
        ]

    def search_user_orders(self, args: dict[str, Any]) -> Any:
        return self.java.post(
            "/orders/search",
            {
                "userId": self._user_id(args),
                "keyword": args.get("keyword"),
                "statusFilter": args.get("status_filter") or args.get("statusFilter") or [],
            },
        )

    def get_order_detail(self, args: dict[str, Any]) -> Any:
        return self.java.get("/orders/detail", {"userId": self._user_id(args), "orderId": self._order_id(args)})

    def get_existing_after_sales(self, args: dict[str, Any]) -> Any:
        return self.java.get("/aftersales/existing", {"userId": self._user_id(args), "orderId": self._order_id(args)})

    def get_merchant_policy(self, args: dict[str, Any]) -> Any:
        merchant_code = str(args.get("merchant_code") or args.get("merchantCode") or "MERCHANT_DEMO")
        return self.java.get("/policies/merchant", {"merchantCode": merchant_code})

    def retrieve_knowledge(self, args: dict[str, Any]) -> Any:
        return self.retriever.retrieve(
            query=str(args.get("query") or ""),
            merchant_code=args.get("merchant_code") or args.get("merchantCode"),
            product_category=args.get("product_category") or args.get("productCategory"),
            scene=args.get("scene"),
            intent=args.get("intent"),
            source_type=args.get("source_type") or args.get("sourceType"),
            policy_version=args.get("policy_version") or args.get("policyVersion"),
            top_k=args.get("top_k") or args.get("topK"),
        )

    def review_images(self, args: dict[str, Any]) -> Any:
        attachments = tuple(
            Attachment(
                kind=str(item.get("kind") or "image"),
                name=str(item.get("name") or "image.jpg"),
                source=item.get("source"),
            )
            for item in args.get("attachments", [])
            if isinstance(item, dict)
        )
        result = self.vision.review_attachments(attachments, order_hint=args.get("order_hint"))
        return serialize_image_review(result)

    def create_after_sales_ticket(self, args: dict[str, Any]) -> Any:
        payload = dict(args)
        payload["userId"] = self._user_id(args)
        payload["orderId"] = self._order_id(args)
        return self.java.post("/aftersales/create", self._camelize(payload))

    def handoff_to_human(self, args: dict[str, Any]) -> Any:
        payload = dict(args)
        payload["userId"] = self._user_id(args)
        return self.java.post("/sessions/handoff", self._camelize(payload))

    def append_chat_message(self, args: dict[str, Any]) -> Any:
        payload = dict(args)
        payload["userId"] = self._user_id(args)
        return self.java.post("/sessions/message", self._camelize(payload))

    def request_missing_evidence(self, args: dict[str, Any]) -> Any:
        payload = dict(args)
        payload["userId"] = self._user_id(args)
        return self.java.post("/sessions/request-evidence", self._camelize(payload))

    @staticmethod
    def _user_id(args: dict[str, Any]) -> int:
        raw = args.get("user_id") or args.get("userId")
        if raw is None:
            raise ValueError("user_id is required")
        return int(raw)

    @staticmethod
    def _order_id(args: dict[str, Any]) -> str:
        raw = args.get("order_id") or args.get("orderId")
        if not raw:
            raise ValueError("order_id is required")
        return str(raw)

    @staticmethod
    def _camelize(payload: dict[str, Any]) -> dict[str, Any]:
        mapping = {
            "user_id": "userId",
            "order_id": "orderId",
            "after_sales_type": "afterSalesType",
            "reason_detail": "reasonDetail",
            "refund_amount": "refundAmount",
            "ai_confidence": "aiConfidence",
            "ai_recommend_type": "aiRecommendType",
            "policy_code": "policyCode",
            "policy_version": "policyVersion",
            "evidence_urls": "evidenceUrls",
            "ai_classify_result": "aiClassifyResult",
            "auto_approved": "autoApproved",
            "session_id": "sessionId",
            "ticket_id": "ticketId",
            "message_type": "messageType",
            "emotion_label": "emotionLabel",
            "emotion_score": "emotionScore",
            "emotion_confidence": "emotionConfidence",
            "knowledge_query": "knowledgeQuery",
            "knowledge_retrieval_mode": "knowledgeRetrievalMode",
            "knowledge_hit_count": "knowledgeHitCount",
            "knowledge_hits_json": "knowledgeHitsJson",
            "knowledge_trace_json": "knowledgeTraceJson",
            "evidence_needed": "evidenceNeeded",
            "assistant_reply": "assistantReply",
        }
        result: dict[str, Any] = {}
        for key, value in payload.items():
            if value is None:
                continue
            result[mapping.get(key, key)] = value
        return result

    @staticmethod
    def compact_json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
