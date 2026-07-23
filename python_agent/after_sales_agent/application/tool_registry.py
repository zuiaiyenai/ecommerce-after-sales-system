from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from typing import Any, Callable

from ..domain_models import Attachment
from ..integrations.java_tool_client import JavaToolClient, JavaToolError
from ..retrieval.pgvector_retriever import PgVectorKnowledgeRetriever
from ..providers.vision_review_service import VisionReviewService
from ..utils.vision_serialization import serialize_image_review


def _is_traceable_citation(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    source_code = str(value.get("source_code") or "").strip()
    trace_id = str(value.get("chunk_id") or value.get("document_id") or "").strip()
    return bool(source_code and trace_id)


def normalize_knowledge_result(value: Any) -> Any:
    """Expose one citation-list contract at the Agent tool boundary."""
    if not isinstance(value, dict):
        return value
    normalized = dict(value)
    hits = value.get("hits")
    if not isinstance(hits, list):
        return normalized
    normalized_hits: list[Any] = []
    for raw_hit in hits:
        if not isinstance(raw_hit, dict):
            normalized_hits.append(raw_hit)
            continue
        hit = dict(raw_hit)
        citations = hit.get("citations")
        if not isinstance(citations, list):
            citation = hit.get("citation")
            citations = [dict(citation)] if isinstance(citation, dict) else []
        hit["citations"] = [dict(item) for item in citations if _is_traceable_citation(item)]
        hit.pop("citation", None)
        normalized_hits.append(hit)
    normalized["hits"] = normalized_hits
    return normalized


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    name: str
    data: Any = None
    error: str | None = None
    error_code: str | None = None
    error_category: str | None = None
    retryable: bool = False


@dataclass
class AgentToolRegistry:
    java: JavaToolClient = field(default_factory=JavaToolClient)
    retriever: PgVectorKnowledgeRetriever = field(default_factory=PgVectorKnowledgeRetriever)
    vision: VisionReviewService = field(default_factory=VisionReviewService)

    def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        tool = self.registry().get(name)
        if tool is None:
            return ToolResult(
                ok=False,
                name=name,
                error=f"unknown tool: {name}",
                error_code="UNKNOWN_TOOL",
                error_category="validation",
            )
        try:
            return ToolResult(ok=True, name=name, data=tool(arguments or {}))
        except JavaToolError as exc:
            return ToolResult(
                ok=False,
                name=name,
                error=str(exc),
                error_code=exc.code,
                error_category=exc.category,
                retryable=exc.retryable,
            )
        except ValueError as exc:
            return ToolResult(
                ok=False,
                name=name,
                error=str(exc),
                error_code="INVALID_TOOL_ARGUMENTS",
                error_category="validation",
            )
        except Exception as exc:
            return ToolResult(
                ok=False,
                name=name,
                error=f"{exc.__class__.__name__}: {exc}",
                error_code="TOOL_EXECUTION_ERROR",
                error_category="tool_error",
            )

    def registry(self) -> dict[str, Callable[[dict[str, Any]], Any]]:
        return {
            "search_user_orders": self.search_user_orders,
            "get_order_detail": self.get_order_detail,
            "get_existing_after_sales": self.get_existing_after_sales,
            "get_after_sales_ticket": self.get_after_sales_ticket,
            "get_merchant_policy": self.get_merchant_policy,
            "retrieve_knowledge": self.retrieve_knowledge,
            "review_images": self.review_images,
            "submit_ai_review": self.submit_ai_review,
            "handoff_to_human": self.handoff_to_human,
            "append_chat_message": self.append_chat_message,
            "request_missing_evidence": self.request_missing_evidence,
        }

    def tool_specs(self) -> list[dict[str, Any]]:
        return [
            self._tool_spec("search_user_orders", "Search only the current user's orders.", [], True, "low", True, {
                "keyword": {"type": "string"},
                "status_filter": {"type": "array", "items": {"type": "string"}},
            }),
            self._tool_spec("get_order_detail", "Get one order after Java ownership validation.", [], True, "low", True, {}),
            self._tool_spec("get_existing_after_sales", "Find an open after-sales ticket for an owned order.", [], True, "low", True, {}),
            self._tool_spec("get_after_sales_ticket", "Get an existing ticket after Java ownership validation.", [], True, "low", True, {}),
            self._tool_spec("get_merchant_policy", "Read merchant policy configuration; never mutates business state.", [], True, "low", True, {
                "merchant_code": {"type": "string"},
            }),
            self._tool_spec(
                "retrieve_knowledge",
                "Retrieve RAG evidence with explicit metadata filters.",
                ["query"],
                True,
                "low",
                True,
                properties={
                    "query": {"type": "string"},
                    "merchant_code": {"type": "string"},
                    "product_category": {"type": "string"},
                    "scene": {"type": "string"},
                    "intent": {"type": "string"},
                    "source_type": {"type": "string"},
                    "policy_version": {
                        "type": "string",
                        "description": "Java-owned policy version snapshot for historical policy lookup.",
                    },
                    "as_of_time": {
                        "type": "string",
                        "format": "date-time",
                        "description": "Timezone-aware ISO 8601 business effective time.",
                    },
                    "top_k": {"type": "number"},
                },
            ),
            self._tool_spec("review_images", "Analyze evidence images without changing ticket state.", [], True, "medium", True, {
                "attachments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string"}, "name": {"type": "string"},
                            "source": {"type": "string"}, "file_url": {"type": "string"},
                        },
                        "additionalProperties": False,
                    },
                },
                "order_hint": {"type": "string"},
            }),
            self._tool_spec("submit_ai_review", "Submit a guarded review result for an existing ticket.", ["verdict"], False, "high", True, {
                "verdict": {"type": "string"}, "after_sales_type": {"type": "string"},
                "reason": {"type": "string"}, "reason_detail": {"type": "string"},
                "refund_amount": {"type": "number"}, "ai_review_confidence": {"type": "number"},
                "ai_suggested_after_sale_type": {"type": "string"}, "policy_code": {"type": "string"},
                "policy_version": {"type": "string"}, "evidence_urls": {"type": "array", "items": {"type": "string"}},
                "auto_approved": {"type": "boolean"},
                "evidence_needed": {"type": "array", "items": {"type": "string"}},
                "assistant_reply": {"type": "string"}, "visual_uncertain": {"type": "boolean"},
                "policy_uncertain": {"type": "boolean"}, "evidence_consistent": {"type": "boolean"},
                "visual_confidence": {"type": "number"}, "risk_review_reasons": {"type": "array", "items": {"type": "string"}},
                "policy_match_score": {"type": "number"}, "filter_level": {"type": "string"},
                "reranker_succeeded": {"type": "boolean"}, "trusted_policy_eligible": {"type": "boolean"},
                "knowledge_query": {"type": "string"}, "knowledge_retrieval_mode": {"type": "string"},
                "knowledge_hit_count": {"type": "number"}, "knowledge_hits_json": {"type": "string"},
                "knowledge_trace_json": {"type": "string"},
            }),
            self._tool_spec("handoff_to_human", "Move a session into human-service mode.", [], False, "medium", True, {
                "assistant_reply": {"type": "string"}, "evidence_needed": {"type": "array", "items": {"type": "string"}},
            }),
            self._tool_spec("append_chat_message", "Persist one chat message through Java.", ["content"], False, "medium", True, {
                "content": {"type": "string"}, "message_type": {"type": "string"},
                "file_url": {"type": "string"}, "emotion_label": {"type": "string"},
                "emotion_score": {"type": "number"}, "emotion_confidence": {"type": "number"},
                "need_human_priority": {"type": "boolean"},
            }),
            self._tool_spec("request_missing_evidence", "Persist a generic missing-evidence request.", [], False, "medium", True, {
                "assistant_reply": {"type": "string"}, "evidence_needed": {"type": "array", "items": {"type": "string"}},
            }),
        ]

    @staticmethod
    def _tool_spec(
        name: str,
        description: str,
        required: list[str],
        read_only: bool,
        risk_level: str,
        idempotent: bool,
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "name": name,
            "description": description,
            "input_schema": {
                "type": "object",
                "required": required,
                "properties": properties or {},
                "additionalProperties": False,
            },
            "read_only": read_only,
            "risk_level": risk_level,
            "idempotent": idempotent,
        }

    def search_user_orders(self, args: dict[str, Any]) -> Any:
        return self._normalize_java_response(
            self.java.post(
                "/orders/search",
                {
                "userId": self._user_id(args),
                "keyword": args.get("keyword"),
                "statusFilter": args.get("status_filter") or [],
                },
            )
        )

    def get_order_detail(self, args: dict[str, Any]) -> Any:
        return self._normalize_java_response(
            self.java.get("/orders/detail", {"userId": self._user_id(args), "orderId": self._order_id(args)})
        )

    def get_existing_after_sales(self, args: dict[str, Any]) -> Any:
        return self._normalize_java_response(
            self.java.get("/aftersales/existing", {"userId": self._user_id(args), "orderId": self._order_id(args)})
        )

    def get_after_sales_ticket(self, args: dict[str, Any]) -> Any:
        return self._normalize_java_response(
            self.java.get(
                "/aftersales/ticket",
                {
                "userId": self._user_id(args),
                "ticketId": self._ticket_id(args),
                "orderId": args.get("order_id"),
                },
            )
        )

    def get_merchant_policy(self, args: dict[str, Any]) -> Any:
        merchant_code = str(args.get("merchant_code") or "MERCHANT_DEMO")
        return self._normalize_java_response(
            self.java.get("/policies/merchant", {"merchantCode": merchant_code})
        )

    def retrieve_knowledge(self, args: dict[str, Any]) -> Any:
        return normalize_knowledge_result(self.retriever.retrieve(
            query=str(args.get("query") or ""),
            merchant_code=args.get("merchant_code"),
            product_category=args.get("product_category"),
            scene=args.get("scene"),
            intent=args.get("intent"),
            source_type=args.get("source_type"),
            policy_version=args.get("policy_version"),
            as_of_time=self._parse_as_of_time(args.get("as_of_time")),
            top_k=args.get("top_k"),
        ))

    @staticmethod
    def _parse_as_of_time(raw: Any) -> datetime | None:
        if raw is None or raw == "":
            return None
        if not isinstance(raw, str):
            raise ValueError("as_of_time must be a timezone-aware ISO 8601 string")
        value = raw.strip()
        if not value:
            return None
        normalized = f"{value[:-1]}+00:00" if value.endswith(("Z", "z")) else value
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError("as_of_time must be a valid timezone-aware ISO 8601 string") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("as_of_time must include a timezone offset")
        return parsed

    def review_images(self, args: dict[str, Any]) -> Any:
        attachments = tuple(
            Attachment(
                kind=str(item.get("kind") or "image"),
                name=str(item.get("name") or "image.jpg"),
                source=item.get("source"),
                file_url=item.get("file_url") or item.get("fileUrl") or item.get("url"),
            )
            for item in args.get("attachments", [])
            if isinstance(item, dict)
        )
        result = self.vision.review_attachments(attachments, order_hint=args.get("order_hint"))
        return serialize_image_review(result)

    def submit_ai_review(self, args: dict[str, Any]) -> Any:
        payload = dict(args)
        payload["userId"] = self._user_id(args)
        payload["ticketId"] = self._ticket_id(args)
        return self._normalize_java_response(
            self.java.post("/aftersales/review", self._camelize(payload))
        )

    def handoff_to_human(self, args: dict[str, Any]) -> Any:
        payload = dict(args)
        payload["userId"] = self._user_id(args)
        return self._normalize_java_response(
            self.java.post("/sessions/handoff", self._camelize(payload))
        )

    def append_chat_message(self, args: dict[str, Any]) -> Any:
        payload = dict(args)
        payload["userId"] = self._user_id(args)
        return self._normalize_java_response(
            self.java.post("/sessions/message", self._camelize(payload))
        )

    def request_missing_evidence(self, args: dict[str, Any]) -> Any:
        payload = dict(args)
        payload["userId"] = self._user_id(args)
        return self._normalize_java_response(
            self.java.post("/sessions/request-evidence", self._camelize(payload))
        )

    @staticmethod
    def _user_id(args: dict[str, Any]) -> int:
        raw = args.get("user_id")
        if raw is None:
            raise ValueError("user_id is required")
        return int(raw)

    @staticmethod
    def _order_id(args: dict[str, Any]) -> str:
        raw = args.get("order_id")
        if not raw:
            raise ValueError("order_id is required")
        return str(raw)

    @staticmethod
    def _ticket_id(args: dict[str, Any]) -> str:
        raw = args.get("ticket_id")
        if not raw:
            raise ValueError("ticket_id is required")
        return str(raw)

    @staticmethod
    def _camelize(payload: dict[str, Any]) -> dict[str, Any]:
        mapping = {
            "user_id": "userId",
            "order_id": "orderId",
            "after_sales_type": "afterSalesType",
            "reason_detail": "reasonDetail",
            "refund_amount": "refundAmount",
            "ai_review_confidence": "aiReviewConfidence",
            "ai_suggested_after_sale_type": "aiSuggestedAfterSaleType",
            "policy_code": "policyCode",
            "policy_version": "policyVersion",
            "evidence_urls": "evidenceUrls",
            "ai_review_audit_json": "aiReviewAuditJson",
            "auto_approved": "autoApproved",
            "session_id": "sessionId",
            "ticket_id": "ticketId",
            "review_request_id": "reviewRequestId",
            "message_type": "messageType",
            "file_url": "fileUrl",
            "emotion_label": "emotionLabel",
            "emotion_score": "emotionScore",
            "emotion_confidence": "emotionConfidence",
            "need_human_priority": "needHumanPriority",
            "knowledge_query": "knowledgeQuery",
            "knowledge_retrieval_mode": "knowledgeRetrievalMode",
            "knowledge_hit_count": "knowledgeHitCount",
            "knowledge_hits_json": "knowledgeHitsJson",
            "knowledge_trace_json": "knowledgeTraceJson",
            "evidence_needed": "evidenceNeeded",
            "assistant_reply": "assistantReply",
            "visual_uncertain": "visualUncertain",
            "policy_uncertain": "policyUncertain",
            "evidence_consistent": "evidenceConsistent",
            "filter_level": "filterLevel",
            "reranker_succeeded": "rerankerSucceeded",
            "trusted_policy_eligible": "trustedPolicyEligible",
            "visual_confidence": "visualConfidence",
            "risk_review_reasons": "riskReviewReasons",
            "policy_citations": "policyCitations",
            "policy_match_score": "policyMatchScore",
            "skill_versions": "skillVersions",
            "image_review": "imageReview",
        }
        result: dict[str, Any] = {}
        for key, value in payload.items():
            if value is None:
                continue
            result[mapping.get(key, key)] = value
        return result

    @classmethod
    def _normalize_java_response(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                cls._camel_to_snake(str(key)): cls._normalize_java_response(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [cls._normalize_java_response(item) for item in value]
        return value

    @staticmethod
    def _camel_to_snake(key: str) -> str:
        chars: list[str] = []
        for char in key:
            if char.isupper() and chars and chars[-1] != "_":
                chars.append("_")
            chars.append(char.lower())
        return "".join(chars)

    @staticmethod
    def compact_json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
