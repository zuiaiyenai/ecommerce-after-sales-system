"""Domain models — pure business types and enums.

This package must not import langgraph, psycopg, httpx, or any other
framework/infrastructure module. It is the dependency-free core of the
after-sales domain.
"""
from __future__ import annotations

from .models import (  # noqa: F401
    AfterSalesRequest,
    AfterSalesScene,
    AfterSalesStatus,
    AfterSalesType,
    AgentResult,
    Attachment,
    ConversationMessage,
    Decision,
    EmotionAnalysisResult,
    EmotionLabel,
    EvidenceCheckResult,
    HumanHandoffResult,
    ImageReviewItem,
    ImageReviewResult,
    Intent,
    IntentResult,
    Order,
    OrderItem,
    OrderStatus,
    RiskAssessmentResult,
    RiskLevel,
    StateTransitionResult,
    Ticket,
    TicketStatus,
    days_between,
    today,
)

__all__ = [
    "AfterSalesRequest",
    "AfterSalesScene",
    "AfterSalesStatus",
    "AfterSalesType",
    "AgentResult",
    "Attachment",
    "ConversationMessage",
    "Decision",
    "EmotionAnalysisResult",
    "EmotionLabel",
    "EvidenceCheckResult",
    "HumanHandoffResult",
    "ImageReviewItem",
    "ImageReviewResult",
    "Intent",
    "IntentResult",
    "Order",
    "OrderItem",
    "OrderStatus",
    "RiskAssessmentResult",
    "RiskLevel",
    "StateTransitionResult",
    "Ticket",
    "TicketStatus",
    "days_between",
    "today",
]
