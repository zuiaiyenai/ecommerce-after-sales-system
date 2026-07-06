from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Optional


class OrderStatus(str, Enum):
    PAID = "paid"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    COMPLETED = "completed"
    REFUNDED = "refunded"


class AfterSalesType(str, Enum):
    REFUND_ONLY = "refund_only"
    RETURN_REFUND = "return_refund"
    RETURN_AND_REFUND = "return_refund"
    REISSUE = "reissue"
    EXCHANGE = "reissue"
    PARTIAL_REFUND = "partial_refund"
    REPAIR = "return_refund"


class AfterSalesStatus(str, Enum):
    NOT_APPLIED = "not_applied"
    SUBMITTED = "submitted"
    WAITING_EVIDENCE = "waiting_evidence"
    MERCHANT_REVIEW = "merchant_review"
    PLATFORM_REVIEW = "platform_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    WAITING_RETURN = "waiting_return"
    REFUND_PROCESSING = "refund_processing"
    EXCHANGE_PROCESSING = "exchange_processing"
    COMPLETED = "completed"
    CLOSED = "closed"
    HUMAN_PROCESSING = "human_processing"


class AfterSalesScene(str, Enum):
    PRODUCT_DAMAGE = "product_damage"
    PACKAGE_DAMAGE = "package_damage"
    QUALITY_ISSUE = "quality_issue"
    WRONG_OR_MISSING_ITEMS = "wrong_or_missing_items"
    LOGISTICS_ISSUE = "logistics_issue"
    PROGRESS_QUERY = "progress_query"
    GENERAL = "general"


class Intent(str, Enum):
    APPLY_AFTER_SALES = "apply_after_sales"
    REFUND_PROGRESS = "refund_progress"
    RETURN_LOGISTICS = "return_logistics"
    SUPPLEMENT_EVIDENCE = "supplement_evidence"
    MERCHANT_REJECTED = "merchant_rejected"
    REFUND_ONLY = "refund_only"
    EXCHANGE_REPAIR = "exchange_repair"
    HUMAN_SERVICE = "human_service"
    COMPLAINT = "complaint"
    GENERAL = "general"


class Decision(str, Enum):
    RESPOND = "respond"
    ASK_FOR_INFO = "ask_for_info"
    CREATE_TICKET = "create_ticket"
    ESCALATE_HUMAN = "escalate_human"
    REJECT = "reject"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EmotionLabel(str, Enum):
    CALM = "calm"
    ANXIOUS = "anxious"
    DISSATISFIED = "dissatisfied"
    ANGRY = "angry"


class TicketStatus(str, Enum):
    WAITING_USER = "waiting_user"
    PENDING_REVIEW = "pending_review"
    AUTO_APPROVED = "auto_approved"
    HUMAN_HANDOFF = "human_handoff"
    CLOSED = "closed"


@dataclass(frozen=True)
class Attachment:
    kind: str
    name: str
    source: Optional[str] = None


@dataclass(frozen=True)
class ConversationMessage:
    role: str
    content: str
    create_time: Optional[datetime] = None


@dataclass(frozen=True)
class OrderItem:
    sku_id: str
    product_name: str
    category: str
    quantity: int
    unit_price: float


@dataclass(frozen=True)
class Order:
    order_id: str
    user_id: str
    status: OrderStatus
    amount: float
    created_at: datetime
    shipped_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    merchant_code: str = "MERCHANT_DEMO"
    items: tuple[OrderItem, ...] = ()
    has_open_after_sales: bool = False
    after_sales_status: AfterSalesStatus = AfterSalesStatus.NOT_APPLIED
    after_sales_type: Optional[AfterSalesType] = None
    refund_status: str = "未开始"
    logistics_status: str = "待更新"
    uploaded_evidence: tuple[str, ...] = ()
    user_after_sales_count: int = 0
    merchant_rejected_before: bool = False


@dataclass(frozen=True)
class AfterSalesRequest:
    user_id: str
    message: str
    requested_type: Optional[AfterSalesType] = None
    order_id: Optional[str] = None
    reason: Optional[str] = None
    description: Optional[str] = None
    refund_amount: Optional[float] = None
    item_opened: Optional[bool] = None
    human_request_count: int = 0
    attachments: tuple[Attachment, ...] = ()
    visual_evidence: tuple[str, ...] = ()
    visual_review_failed: bool = False
    llm_intent: Optional[Intent] = None
    llm_scene: Optional[AfterSalesScene] = None
    llm_confidence: float = 0.0
    normalized_issue: Optional[str] = None
    quality_description_detailed: Optional[bool] = None
    evidence_consistent: Optional[bool] = None
    requested_at: datetime = field(default_factory=datetime.now)


@dataclass(frozen=True)
class IntentResult:
    intent: Intent
    next_agent: str
    need_human: bool
    keywords: tuple[str, ...] = ()
    score: int = 0
    needs_clarification: bool = False
    clarification_options: tuple[str, ...] = ()
    fallback: bool = False


@dataclass(frozen=True)
class StateTransitionResult:
    current_status: AfterSalesStatus
    allowed_actions: tuple[str, ...]
    allowed: bool
    reason: str
    suggested_status: AfterSalesStatus


@dataclass(frozen=True)
class EvidenceCheckResult:
    evidence_complete: bool
    missing_items: tuple[str, ...]
    suggestion: str
    required_items: tuple[str, ...]


@dataclass(frozen=True)
class RiskAssessmentResult:
    risk_level: RiskLevel
    allow_auto_refund: bool
    need_human_review: bool
    reason: str
    score: int


@dataclass(frozen=True)
class HumanHandoffResult:
    triggered: bool
    reason: Optional[str]
    summary: dict[str, str]


@dataclass(frozen=True)
class EmotionAnalysisResult:
    label: EmotionLabel
    score: int
    confidence: float
    triggers: tuple[str, ...]
    need_human_priority: bool
    reply_tone: str
    comfort_prefix: str
    comfort_examples: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImageReviewItem:
    name: str
    image_type: str
    is_clear: bool
    contains_damage_area: bool
    contains_outer_package: bool
    contains_logistics_label: bool
    logistics_matches_order: bool = False
    courier_company: str = ""
    tracking_number: str = ""
    sender_name: str = ""
    receiver_name: str = ""
    confidence: float = 0.0
    notes: str = ""


@dataclass(frozen=True)
class ImageReviewResult:
    success: bool
    items: tuple[ImageReviewItem, ...]
    all_clear: bool
    has_damage_area: bool
    has_outer_package: bool
    has_logistics_label: bool
    logistics_matches_order: bool = False
    courier_company: str = ""
    tracking_number: str = ""
    sender_name: str = ""
    receiver_name: str = ""
    missing_visual_evidence: tuple[str, ...] = ()
    summary: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Ticket:
    ticket_id: str
    order_id: str
    user_id: str
    after_sales_type: AfterSalesType
    intent: Intent
    status: TicketStatus
    risk_level: RiskLevel
    summary: str
    expected_hours: int
    next_action: str
    created_at: datetime


@dataclass(frozen=True)
class AgentResult:
    decision: Decision
    user_reply: str
    extracted_order_id: Optional[str]
    intent: Intent
    next_agent: str
    need_human: bool
    current_status: AfterSalesStatus
    scene: AfterSalesScene = AfterSalesScene.GENERAL
    allowed_actions: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    risk_level: RiskLevel = RiskLevel.LOW
    ticket: Optional[Ticket] = None
    suggested_action: Optional[str] = None
    progress_hint: Optional[str] = None
    audit_note: Optional[str] = None
    handoff_summary: Optional[dict[str, str]] = None
    emotion: EmotionAnalysisResult | None = None


def days_between(start: Optional[datetime], end: datetime) -> Optional[int]:
    if start is None:
        return None
    return (end.date() - start.date()).days


def today() -> date:
    return datetime.now().date()
