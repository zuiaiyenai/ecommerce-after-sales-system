from __future__ import annotations

from dataclasses import dataclass

from .agent import ReturnAgent
from .models import (
    AfterSalesRequest,
    AgentResult,
    Attachment,
    ConversationMessage,
    ImageReviewResult,
    Order,
)
from .vision import VisionReviewService


@dataclass(frozen=True)
class ConversationContext:
    user_id: str
    selected_order: Order | None
    message: str
    session_id: int | None = None
    description: str | None = None
    item_opened: bool | None = None
    refund_amount: float | None = None
    human_request_count: int = 0
    attachments: tuple[Attachment, ...] = ()
    image_review: ImageReviewResult | None = None
    recent_history: tuple[ConversationMessage, ...] = ()
    history_summary: dict[str, object] | None = None


class ReturnConversationService:
    def __init__(
        self,
        agent: ReturnAgent | None = None,
        vision_service: VisionReviewService | None = None,
    ) -> None:
        self.agent = agent or ReturnAgent()
        self.vision_service = vision_service or VisionReviewService()

    def handle(self, context: ConversationContext) -> AgentResult:
        order_hint = None
        if context.selected_order is not None:
            order_hint = f"订单号：{context.selected_order.order_id}；商品：{context.selected_order.items[0].product_name}"
        image_review = context.image_review or self.review_images(
            context.attachments,
            order_hint=order_hint,
        )
        request = AfterSalesRequest(
            user_id=context.user_id,
            message=context.message,
            order_id=context.selected_order.order_id if context.selected_order else None,
            description=context.description,
            item_opened=context.item_opened,
            refund_amount=context.refund_amount,
            human_request_count=context.human_request_count,
            attachments=context.attachments,
            visual_evidence=self._extract_visual_evidence(image_review),
            visual_review_failed=self._visual_review_failed(context.attachments, image_review),
        )
        result = self.agent.handle(request, context.selected_order)
        if image_review and image_review.success:
            return AgentResult(
                decision=result.decision,
                user_reply=result.user_reply,
                extracted_order_id=result.extracted_order_id,
                intent=result.intent,
                next_agent=result.next_agent,
                need_human=result.need_human,
                current_status=result.current_status,
                allowed_actions=result.allowed_actions,
                missing_fields=result.missing_fields,
                risk_level=result.risk_level,
                ticket=result.ticket,
                progress_hint=self._merge_progress(result.progress_hint, image_review.summary),
                audit_note=self._merge_progress(result.audit_note, f"vision={image_review.summary}"),
                handoff_summary=result.handoff_summary,
            )
        return result

    def review_images(
        self,
        attachments: tuple[Attachment, ...],
        *,
        order_hint: str | None = None,
    ) -> ImageReviewResult | None:
        if not attachments:
            return None
        return self.vision_service.review_attachments(attachments, order_hint=order_hint)

    @staticmethod
    def _extract_visual_evidence(image_review: ImageReviewResult | None) -> tuple[str, ...]:
        if image_review is None or not image_review.success:
            return ()
        evidence: list[str] = []
        if image_review.has_damage_area:
            evidence.append("破损照片")
        if image_review.has_outer_package:
            evidence.append("外包装照片")
        if image_review.has_logistics_label:
            evidence.append("物流面单照片")
        return tuple(evidence)

    @staticmethod
    def _visual_review_failed(
        attachments: tuple[Attachment, ...],
        image_review: ImageReviewResult | None,
    ) -> bool:
        if not attachments:
            return False
        if image_review is None:
            return True
        if not image_review.success:
            return True
        failure_markers = {"视觉模型不可用", "图片分析结果待补充"}
        return any(item in failure_markers for item in image_review.missing_visual_evidence)

    @staticmethod
    def _merge_progress(base: str | None, extra: str) -> str:
        if not base:
            return extra
        return f"{base} {extra}"
