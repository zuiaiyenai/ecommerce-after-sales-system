from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..agents.emotion_agent import EmotionAgent
from ..infra.db import MySQLRepository
from ..merchant_policy import MerchantPolicyRegistry
from .conversation import ConversationContext, build_after_sales_request
from .qwen_service import LLMConversationResult


@dataclass(frozen=True)
class PersistenceResult:
    session_id: int
    session_no: str
    user_message_id: int
    assistant_message_id: int
    ticket_no: str | None = None
    ticket_log_id: int | None = None
    notice_id: int | None = None


class ConversationPersistenceService:
    def __init__(self, repository: MySQLRepository) -> None:
        self.repository = repository
        self.emotion_agent = EmotionAgent()
        self.policy_registry = MerchantPolicyRegistry.from_env()

    def persist_interaction(
        self,
        *,
        context: ConversationContext,
        result: LLMConversationResult,
        source_channel: str = "H5",
    ) -> PersistenceResult | None:
        if context.selected_order is None:
            return None

        request = build_after_sales_request(context)
        policy_resolution = self.policy_registry.resolve_with_context(
            order=context.selected_order,
            request=request,
        )
        service_policy = policy_resolution.service_policy
        knowledge_base = policy_resolution.knowledge_base
        policy_code = service_policy.policy_code
        policy_version = service_policy.policy_version

        order_db_id = self.repository.resolve_order_db_id(context.selected_order.order_id)
        user_id = None
        if order_db_id is not None:
            user_id = self.repository.resolve_order_owner_user_id(context.selected_order.order_id)
        if user_id is None:
            try:
                user_id = int(context.selected_order.user_id)
            except (TypeError, ValueError):
                return None

        ticket_id = None
        if order_db_id and result.fallback_result.ticket is not None:
            ticket_id = self.repository.find_or_create_agent_ticket(
                order_db_id=order_db_id,
                order_no=context.selected_order.order_id,
                user_id=user_id,
                policy_code=policy_code,
                policy_version=policy_version,
                product_name=context.selected_order.items[0].product_name
                if context.selected_order.items
                else "售后商品",
                refund_amount=context.selected_order.amount,
                description=self._handoff_problem_description(context, result),
                ticket=result.fallback_result.ticket,
                confidence=self._conversation_confidence(result),
                audit_note=result.fallback_result.audit_note,
            )
        elif order_db_id and result.fallback_result.need_human:
            ticket_id = self.repository.find_or_create_handoff_ticket(
                order_db_id=order_db_id,
                order_no=context.selected_order.order_id,
                user_id=user_id,
                policy_code=policy_code,
                policy_version=policy_version,
                product_name=context.selected_order.items[0].product_name
                if context.selected_order.items
                else "售后商品",
                refund_amount=context.selected_order.amount,
                description=self._handoff_problem_description(context, result),
                ai_summary=result.fallback_result.handoff_summary,
                ai_confidence=self._conversation_confidence(result),
            )
        elif order_db_id:
            ticket_id = self.repository.resolve_recent_ticket_id(order_db_id)
        ticket_no = self.repository.resolve_ticket_no(ticket_id)

        session = self.repository.find_or_create_session(
            user_id=user_id,
            order_db_id=order_db_id,
            ticket_id=ticket_id,
            policy_code=policy_code,
            policy_version=policy_version,
            source_channel=source_channel,
        )

        user_emotion = self.emotion_agent.analyze(
            request,
            context.selected_order,
            recent_user_messages=tuple(
                message.content for message in context.recent_history if message.role == "user"
            ),
            knowledge_base=knowledge_base,
            handoff_min_level=service_policy.emotion_handoff_min_level,
        )
        user_emotion_label = self._map_emotion_label(user_emotion.label.value)
        user_emotion_score = self._normalize_emotion_score(user_emotion.score)
        user_emotion_confidence = self._normalize_confidence(user_emotion.confidence)

        assistant_emotion = result.fallback_result.emotion or user_emotion
        assistant_emotion_label = self._map_emotion_label(assistant_emotion.label.value)
        assistant_emotion_score = self._normalize_emotion_score(assistant_emotion.score)
        assistant_emotion_confidence = self._normalize_confidence(
            getattr(assistant_emotion, "confidence", 0.8)
        )

        user_message_ids: list[int] = []
        attachment_url_map: dict[str, str] = {}
        if isinstance(result.raw, dict):
            attachment_url_map = result.raw.get("_attachment_urls") or {}

        for attachment in context.attachments:
            if not attachment.source:
                continue
            saved_url = attachment_url_map.get(attachment.name)
            content = saved_url if saved_url else attachment.source
            user_message_ids.append(
                self.repository.insert_chat_message(
                    session_id=session["id"],
                    sender_id=user_id,
                    sender_role="USER",
                    content=content,
                    ai_intent=result.intent,
                    emotion_label=user_emotion_label,
                    emotion_score=user_emotion_score,
                    emotion_confidence=user_emotion_confidence,
                    message_type="IMAGE",
                )
            )

        for user_content in self._user_message_contents(context):
            user_message_ids.append(
                self.repository.insert_chat_message(
                    session_id=session["id"],
                    sender_id=user_id,
                    sender_role="USER",
                    content=user_content,
                    ai_intent=result.intent,
                    emotion_label=user_emotion_label,
                    emotion_score=user_emotion_score,
                    emotion_confidence=user_emotion_confidence,
                )
            )

        user_message_id = user_message_ids[0]
        self.repository.update_session_snapshot(
            session_id=session["id"],
            last_message_content=self._user_message_contents(context)[-1],
            ai_summary=f"用户意图={result.intent}; 建议动作={result.suggested_action}",
            emotion_label=user_emotion_label,
            emotion_score=user_emotion_score,
            emotion_confidence=user_emotion_confidence,
            increase_service_unread=True,
        )

        assistant_message_id = self.repository.insert_chat_message(
            session_id=session["id"],
            sender_id=0,
            sender_role="AI",
            content=result.assistant_reply,
            ai_intent=result.intent,
            confidence=self._conversation_confidence(result),
            emotion_label=assistant_emotion_label,
            emotion_score=assistant_emotion_score,
            emotion_confidence=assistant_emotion_confidence,
        )
        self.repository.update_session_snapshot(
            session_id=session["id"],
            last_message_content=result.assistant_reply,
            ai_summary=self._build_ai_summary(context, result),
            emotion_label=user_emotion_label,
            emotion_score=user_emotion_score,
            emotion_confidence=user_emotion_confidence,
            increase_user_unread=True,
        )

        if result.fallback_result.need_human:
            self.repository.mark_session_waiting_human(
                session_id=session["id"],
                ticket_id=ticket_id,
                summary=self._build_human_session_summary(context, result),
                emotion_label=assistant_emotion_label,
                emotion_score=assistant_emotion_score,
                emotion_confidence=assistant_emotion_confidence,
            )

        ticket_log_id = None
        notice_id = None
        if ticket_id:
            ticket_log_id = self.repository.insert_ticket_log(
                ticket_id=ticket_id,
                operator_id=0,
                operator_role="AI",
                old_status=None,
                new_status=self._ticket_log_status(result),
                action_type="TRANSFER" if result.fallback_result.need_human else "AI_REPLY",
                action_desc=self._build_ticket_log_desc(context, result),
            )
            notice_id = self.repository.insert_message_notice(
                receiver_id=0 if result.fallback_result.need_human else user_id,
                receiver_role="AGENT" if result.fallback_result.need_human else "USER",
                title="有新的人工客服接入请求" if result.fallback_result.need_human else "售后咨询已更新",
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
            ticket_no=ticket_no,
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
    def _normalize_emotion_score(score: float | int | None) -> float | None:
        if score is None:
            return None
        try:
            normalized = float(score)
        except (TypeError, ValueError):
            return None
        if normalized > 1:
            normalized = normalized / 100.0
        return max(0.0, min(1.0, normalized))

    @staticmethod
    def _normalize_confidence(value: float | int | None) -> float | None:
        if value is None:
            return None
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return None
        if confidence > 1:
            confidence = confidence / 100.0
        return max(0.0, min(1.0, confidence))

    @staticmethod
    def _build_ai_summary(context: ConversationContext, result: LLMConversationResult) -> str:
        return (
            f"订单={context.selected_order.order_id}; "
            f"意图={result.intent}; "
            f"动作={result.suggested_action}; "
            f"回复={result.assistant_reply[:120]}"
        )

    @staticmethod
    def _user_message_contents(context: ConversationContext) -> list[str]:
        contents = [context.message.strip()] if context.message and context.message.strip() else []
        description = (context.description or "").strip()
        if description and description not in contents:
            contents.append(f"补充说明：{description}")
        return contents or ["用户发起售后咨询"]

    @staticmethod
    def _handoff_problem_description(context: ConversationContext, result: LLMConversationResult) -> str:
        parts = []
        if context.description:
            parts.append(context.description)
        if context.message and context.message not in parts:
            parts.append(context.message)
        if result.fallback_result.progress_hint:
            parts.append(result.fallback_result.progress_hint)
        return "；".join(part.strip() for part in parts if part and part.strip())[:1000]

    @staticmethod
    def _conversation_confidence(result: LLMConversationResult) -> float:
        understanding = None
        if isinstance(result.raw, dict):
            understanding = result.raw.get("conversation_understanding")
        if isinstance(understanding, dict):
            try:
                return float(understanding.get("confidence") or 0.8)
            except (TypeError, ValueError):
                return 0.8
        return 0.8

    @staticmethod
    def _ticket_log_status(result: LLMConversationResult) -> str:
        ticket = result.fallback_result.ticket
        if ticket is not None:
            if ticket.status.value == "auto_approved":
                return "PROCESSING"
            if ticket.status.value in {"pending_review", "waiting_user", "human_handoff"}:
                return "PENDING"
            if ticket.status.value == "closed":
                return "CLOSED"
        status_value = result.fallback_result.current_status.value.upper()
        mapping = {
            "MERCHANT_REVIEW": "PENDING",
            "PLATFORM_REVIEW": "PENDING",
            "WAITING_EVIDENCE": "PENDING",
            "WAITING_RETURN": "PROCESSING",
            "REFUND_PROCESSING": "PROCESSING",
            "EXCHANGE_PROCESSING": "PROCESSING",
            "COMPLETED": "COMPLETED",
            "REJECTED": "REJECTED",
        }
        return mapping.get(status_value, "PENDING")

    @staticmethod
    def _build_human_session_summary(context: ConversationContext, result: LLMConversationResult) -> str:
        return (
            f"AI建议转人工；订单={context.selected_order.order_id}; "
            f"问题={ConversationPersistenceService._handoff_problem_description(context, result)}; "
            f"原因={result.suggested_action}"
        )[:500]

    @staticmethod
    def _build_ticket_log_desc(context: ConversationContext, result: LLMConversationResult) -> str:
        return (
            f"AI识别用户问题“{context.message}”，"
            f"判断意图为 {result.intent}，"
            f"生成回复“{result.assistant_reply[:200]}”"
        )
