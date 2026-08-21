from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from typing import Any


def _clean_string(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_evidence_source(value: Any) -> str:
    source = str(value or "").strip()
    if not source.startswith("/"):
        return source
    tool_base_url = os.getenv(
        "AFTERSALES_JAVA_TOOL_BASE_URL",
        "http://java:8080/api/internal/agent-tools",
    ).rstrip("/")
    api_base_url = tool_base_url.split("/internal/agent-tools", 1)[0].rstrip("/")
    return f"{api_base_url}{source}"


@dataclass(frozen=True)
class TrustedCaseContext:
    user_id: str
    session_id: str | None
    ticket_id: str
    order_id: str
    ticket_status: str
    merchant_code: str | None
    policy_version: str | None
    product_name: str | None
    product_category: str | None
    after_sales_type: str | None
    issue_description: str
    business_time: str | None
    context_version: str
    evidence_revision: int
    request_source: str
    attachments: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_ticket(
        cls,
        payload: dict[str, Any],
        ticket: dict[str, Any],
    ) -> "TrustedCaseContext":
        raw_attachments = [
            dict(item)
            for item in payload.get("attachments") or []
            if isinstance(item, dict)
        ]
        if not raw_attachments:
            raw_attachments = [
                {
                    "kind": "image",
                    "name": f"ticket_evidence_{index}.jpg",
                    "source": _normalize_evidence_source(url),
                }
                for index, url in enumerate(ticket.get("evidence_urls") or [], start=1)
                if str(url or "").strip()
            ]
        context_version = _clean_string(ticket.get("context_version"))
        if context_version is None:
            version_payload = {
                "ticket_id": ticket.get("ticket_id"),
                "status": ticket.get("status"),
                "policy_version": ticket.get("policy_version"),
                "evidence_urls": ticket.get("evidence_urls") or [],
            }
            context_version = hashlib.sha256(
                json.dumps(
                    version_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                ).encode("utf-8")
            ).hexdigest()[:24]
        client_context = (
            payload.get("client_context")
            if isinstance(payload.get("client_context"), dict)
            else {}
        )
        return cls(
            user_id=str(payload.get("user_id") or ticket.get("user_id") or ""),
            session_id=_clean_string(payload.get("session_id")),
            ticket_id=str(ticket.get("ticket_id") or payload.get("ticket_id") or ""),
            order_id=str(ticket.get("order_id") or payload.get("order_id") or ""),
            ticket_status=str(ticket.get("status") or "").upper(),
            merchant_code=_clean_string(ticket.get("merchant_code")),
            policy_version=_clean_string(ticket.get("policy_version")),
            product_name=_clean_string(ticket.get("product_name")),
            product_category=_clean_string(
                ticket.get("category") or ticket.get("product_category")
            ),
            after_sales_type=_clean_string(ticket.get("after_sales_type")),
            issue_description="；".join(
                dict.fromkeys(
                    text
                    for text in (
                        _clean_string(ticket.get("reason")),
                        _clean_string(ticket.get("reason_detail")),
                        _clean_string(ticket.get("description")),
                    )
                    if text
                )
            ),
            business_time=_clean_string(
                ticket.get("after_sales_applied_at") or ticket.get("create_time")
            ),
            context_version=context_version,
            evidence_revision=max(
                0,
                int(ticket.get("evidence_revision") or 0),
            ),
            request_source=str(client_context.get("source") or "unknown").lower(),
            attachments=tuple(raw_attachments),
        )

    def policy_view(self, issue: str) -> dict[str, Any]:
        return {
            "issue": issue,
            "merchant_code": self.merchant_code,
            "policy_version": self.policy_version,
            "product_name": self.product_name,
            "product_category": self.product_category,
            "after_sales_type": self.after_sales_type,
            "business_time": self.business_time,
            "context_version": self.context_version,
        }

    def evidence_view(self, issue: str) -> dict[str, Any]:
        return {
            "issue": issue,
            "product_name": self.product_name,
            "product_category": self.product_category,
            "after_sales_type": self.after_sales_type,
            "ticket_id": self.ticket_id,
            "order_id": self.order_id,
            "context_version": self.context_version,
        }


@dataclass(frozen=True)
class PolicyTask:
    task_id: str
    trace_id: str | None
    review_request_id: str
    ticket_id: str
    context_version: str
    user_id: str
    issue: str
    query: str
    merchant_code: str | None
    product_name: str | None
    product_category: str | None
    after_sales_type: str | None
    policy_version: str | None
    business_time: str | None
    skill_name: str = ""
    skill_version: str = ""
    skill_instructions: str = ""


@dataclass(frozen=True)
class EvidenceTask:
    task_id: str
    trace_id: str | None
    review_request_id: str
    ticket_id: str
    context_version: str
    user_id: str
    order_id: str
    issue: str
    product_name: str | None
    product_category: str | None
    after_sales_type: str | None
    attachments: tuple[dict[str, Any], ...] = ()
    skill_name: str = ""
    skill_version: str = ""
    skill_instructions: str = ""


@dataclass(frozen=True)
class ReviewWorkflowPlan:
    action: str
    specialists: tuple[str, ...]
    policy_query: str
    reason_codes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PolicyAssessment:
    context_version: str
    success: bool
    trusted_policy_eligible: bool
    policy_version_matched: bool
    filter_level: str | None
    reranker_succeeded: bool
    retrieval_mode: str | None
    policy_match_score: float
    policy_threshold: float = 0.55
    required_evidence: tuple[str, ...] = ()
    citations: tuple[dict[str, Any], ...] = ()
    uncertainty_reasons: tuple[str, ...] = ()
    raw_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceAssessment:
    context_version: str
    success: bool
    visual_verifiable: bool
    evidence_consistent: bool | None
    visual_confidence: float
    satisfied_evidence: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    risk_signals: tuple[str, ...] = ()
    uncertainty_reasons: tuple[str, ...] = ()
    image_review: dict[str, Any] | None = None
    evidence_categories: tuple[str, ...] = ()
    observed_issue_types: tuple[str, ...] = ()
    verification_limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReviewProposal:
    proposed_verdict: str
    reason: str
    confidence: float
    risk_reasons: tuple[str, ...]
    assistant_reply: str
    model_confidence: float = 0.0
    confidence_model_version: str | None = None
    confidence_breakdown: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
