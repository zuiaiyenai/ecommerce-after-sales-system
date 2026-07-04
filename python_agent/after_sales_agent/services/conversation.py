from __future__ import annotations

from dataclasses import dataclass, replace

from ..agents.return_agent import ReturnAgent
from ..models import (
    AfterSalesRequest,
    AgentResult,
    Attachment,
    ConversationMessage,
    ImageReviewResult,
    Order,
)
from .vision import VisionReviewService
from ..utils.vision_utils import image_review_to_visual_evidence, is_visual_review_failed


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


def build_after_sales_request(
    context: ConversationContext,
    *,
    image_review: ImageReviewResult | None = None,
) -> AfterSalesRequest:
    """Single conversion point so rule, LLM, and persistence paths see the same request shape."""
    resolved_image_review = context.image_review if image_review is None else image_review
    return AfterSalesRequest(
        user_id=context.user_id,
        message=context.message,
        order_id=context.selected_order.order_id if context.selected_order else None,
        description=_description_with_recent_user_context(context),
        item_opened=context.item_opened,
        refund_amount=context.refund_amount,
        human_request_count=context.human_request_count,
        attachments=context.attachments,
        visual_evidence=image_review_to_visual_evidence(resolved_image_review),
        visual_review_failed=is_visual_review_failed(context.attachments, resolved_image_review),
    )


def _description_with_recent_user_context(context: ConversationContext) -> str | None:
    parts = [context.description.strip()] if context.description else []
    current_message = context.message.strip()
    recent_user_messages = []
    for message in context.recent_history:
        if message.role != "user":
            continue
        content = message.content.strip()
        if content and content != current_message:
            recent_user_messages.append(content)
    if recent_user_messages:
        parts.append("历史用户补充：" + " / ".join(recent_user_messages[-3:]))
    return " ".join(parts) if parts else None


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
        request = build_after_sales_request(context, image_review=image_review)
        result = self.agent.handle(request, context.selected_order)
        if image_review and image_review.success:
            return replace(
                result,
                progress_hint=self._merge_progress(result.progress_hint, image_review.summary),
                audit_note=self._merge_progress(result.audit_note, f"vision={image_review.summary}"),
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
    def _merge_progress(base: str | None, extra: str) -> str:
        if not base:
            return extra
        return f"{base} {extra}"
