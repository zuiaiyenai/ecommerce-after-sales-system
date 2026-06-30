from __future__ import annotations

from dataclasses import dataclass

from .conversation import ConversationContext
from .db import MySQLRepository
from .emotion_agent import EmotionAgent
from .models import AfterSalesRequest
from .qwen_service import LLMConversationResult


@dataclass(frozen=True)
class PersistenceResult:
    session_id: int
    session_no: str
    user_message_id: int
    assistant_message_id: int
    ticket_log_id: int | None = None
    notice_id: int | None = None


class ConversationPersistenceService:
    def __init__(self, repository: MySQLRepository) -> None:
        self.repository = repository
        self.emotion_agent = EmotionAgent()

    def persist_interaction(
        self,
        *,
        context: ConversationContext,
        result: LLMConversationResult,
        source_channel: str = "H5",
    ) -> PersistenceResult | None:
        if context.selected_order is None:
            return None

        order_db_id = self.repository.resolve_order_db_id(context.selected_order.order_id)
        user_id = None
        if order_db_id is not None:
            user_id = self.repository.resolve_order_owner_user_id(context.selected_order.order_id)
        if user_id is None:
            try:
                user_id = int(context.selected_order.user_id)
            except (TypeError, ValueError):
                return None
        ticket_id = self.repository.resolve_recent_ticket_id(order_db_id) if order_db_id else None
        session = self.repository.find_or_create_session(
            user_id=user_id,
            order_db_id=order_db_id,
            ticket_id=ticket_id,
            source_channel=source_channel,
        )
        user_emotion = self.emotion_agent.analyze(
            AfterSalesRequest(
                user_id=context.user_id,
                message=context.message,
                order_id=context.selected_order.order_id,
                description=context.description,
                item_opened=context.item_opened,
                human_request_count=context.human_request_count,
                attachments=context.attachments,
            ),
            context.selected_order,
            recent_user_messages=tuple(
                message.content for message in context.recent_history if message.role == "user"
            ),
        )

        user_message_id = self.repository.insert_chat_message(
            session_id=session["id"],
            sender_id=user_id,
            sender_role="USER",
            content=context.message,
            ai_intent=result.intent,
            emotion_label=self._map_emotion_label(user_emotion.label.value),
        )
        self.repository.update_session_snapshot(
            session_id=session["id"],
            last_message_content=context.message,
            ai_summary=f"用户意图={result.intent}; 建议动作={result.suggested_action}",
            increase_service_unread=True,
        )

        assistant_message_id = self.repository.insert_chat_message(
            session_id=session["id"],
            sender_id=0,
            sender_role="AI",
            content=result.assistant_reply,
            ai_intent=result.intent,
            emotion_label=self._map_emotion_label(result.fallback_result.emotion.label.value if result.fallback_result.emotion else "calm"),
        )
        self.repository.update_session_snapshot(
            session_id=session["id"],
            last_message_content=result.assistant_reply,
            ai_summary=self._build_ai_summary(context, result),
            increase_user_unread=True,
        )

        ticket_log_id = None
        notice_id = None
        if ticket_id:
            ticket_log_id = self.repository.insert_ticket_log(
                ticket_id=ticket_id,
                operator_id=0,
                operator_role="AI",
                old_status=None,
                new_status=result.fallback_result.current_status.value.upper(),
                action_type="AI_REPLY",
                action_desc=self._build_ticket_log_desc(context, result),
            )
            notice_id = self.repository.insert_message_notice(
                receiver_id=user_id,
                receiver_role="USER",
                title="售后咨询已更新",
                content=result.assistant_reply,
                notice_type="TICKET",
                business_type="TICKET",
                business_id=ticket_id,
            )

        return PersistenceResult(
            session_id=session["id"],
            session_no=session["session_no"],
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            ticket_log_id=ticket_log_id,
            notice_id=notice_id,
        )

    @staticmethod
    def _map_emotion_label(label: str) -> str:
        mapping = {
            "calm": "NEUTRAL",
            "anxious": "ANXIOUS",
            "dissatisfied": "DISSATISFIED",
            "angry": "ANGRY",
        }
        return mapping.get(label, "NEUTRAL")

    @staticmethod
    def _build_ai_summary(context: ConversationContext, result: LLMConversationResult) -> str:
        return (
            f"订单={context.selected_order.order_id}; "
            f"意图={result.intent}; "
            f"动作={result.suggested_action}; "
            f"回复={result.assistant_reply[:120]}"
        )

    @staticmethod
    def _build_ticket_log_desc(context: ConversationContext, result: LLMConversationResult) -> str:
        return (
            f"AI识别用户问题“{context.message}”，"
            f"判断意图为 {result.intent}，"
            f"给出回复：{result.assistant_reply}"
        )
