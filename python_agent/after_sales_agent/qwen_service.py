from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any

from .agent import ReturnAgent
from .conversation import ConversationContext
from .llm import LLMError, OpenAICompatibleClient, OpenAICompatibleConfig
from .models import (
    AgentResult,
    AfterSalesRequest,
    ConversationMessage,
    Decision,
    ImageReviewResult,
)
from .trace import TraceRecorder


@dataclass(frozen=True)
class LLMConversationResult:
    assistant_reply: str
    intent: str
    item_opened: bool | None
    evidence_needed: tuple[str, ...]
    suggested_action: str
    raw: dict[str, Any]
    fallback_result: AgentResult


class QwenReturnService:
    def __init__(
        self,
        *,
        config: OpenAICompatibleConfig | None = None,
        rule_agent: ReturnAgent | None = None,
    ) -> None:
        self.client = OpenAICompatibleClient(config or OpenAICompatibleConfig.from_env())
        self.rule_agent = rule_agent or ReturnAgent()

    def bind_trace(self, trace_recorder: TraceRecorder | None) -> None:
        self.client.bind_trace(trace_recorder)

    def handle(self, context: ConversationContext) -> LLMConversationResult:
        fallback_result = self.rule_agent.handle(
            request=self._build_request(context),
            order=context.selected_order,
        )
        if context.selected_order is None or self._should_skip_model(fallback_result):
            return LLMConversationResult(
                assistant_reply=fallback_result.user_reply,
                intent=fallback_result.intent.value,
                item_opened=context.item_opened,
                evidence_needed=fallback_result.missing_fields,
                suggested_action=fallback_result.suggested_action or fallback_result.decision.value,
                raw={"mode": "rule_only"},
                fallback_result=fallback_result,
            )

        try:
            raw = self.client.chat_json(
                system_prompt=self._system_prompt(),
                user_prompt=self._user_prompt(context, fallback_result),
            )
            reply = self._build_user_reply(raw, fallback_result)
            item_opened = self._parse_bool(raw.get("item_opened"), context.item_opened)
            return LLMConversationResult(
                assistant_reply=reply,
                intent=fallback_result.intent.value,
                item_opened=item_opened,
                evidence_needed=fallback_result.missing_fields,
                suggested_action=fallback_result.suggested_action or fallback_result.decision.value,
                raw=raw,
                fallback_result=fallback_result,
            )
        except LLMError as exc:
            return LLMConversationResult(
                assistant_reply=fallback_result.user_reply,
                intent=fallback_result.intent.value,
                item_opened=context.item_opened,
                evidence_needed=fallback_result.missing_fields,
                suggested_action=fallback_result.suggested_action or "model_unavailable",
                raw={"mode": "model_unavailable", "error": str(exc)},
                fallback_result=fallback_result,
            )

    @staticmethod
    def _should_skip_model(fallback_result: AgentResult) -> bool:
        if fallback_result.decision == Decision.ESCALATE_HUMAN:
            return True
        if fallback_result.suggested_action in {
            "补充异常描述",
            "补充必要信息后转人工",
            "转接人工客服",
            "转人工核实功能异常",
        }:
            return True
        return False

    @staticmethod
    def _build_request(context: ConversationContext) -> AfterSalesRequest:
        visual_evidence = ()
        visual_review_failed = False
        if context.image_review is not None:
            visual_evidence = QwenReturnService._extract_visual_evidence(context.image_review)
            visual_review_failed = QwenReturnService._is_visual_review_failed(
                context.attachments,
                context.image_review,
            )
        return AfterSalesRequest(
            user_id=context.user_id,
            message=context.message,
            order_id=context.selected_order.order_id if context.selected_order else None,
            description=context.description,
            item_opened=context.item_opened,
            refund_amount=context.refund_amount,
            human_request_count=context.human_request_count,
            attachments=context.attachments,
            visual_evidence=visual_evidence,
            visual_review_failed=visual_review_failed,
        )

    @staticmethod
    def _system_prompt() -> str:
        schema = {
            "assistant_reply": "给用户看的中文回复，20到100字",
            "item_opened": "true|false|null",
        }
        return (
            "你是订单售后平台的客服回复Agent。\n"
            "你的职责：\n"
            "1. 只根据订单信息、售后状态、图片审核结果和规则结果生成面向用户的最终回复；\n"
            "2. 回复礼貌、简洁、自然；\n"
            "3. 不得编造退款时间、审核结果、物流结果；\n"
            "4. 不输出内部推理、规则分析过程、Agent名称；\n"
            "5. 信息不足时，只提示用户补充必要材料；\n"
            "6. 需要人工处理时，只说明已转人工处理；\n"
            "7. 每次回复不超过100字。\n"
            "限制：\n"
            "1. 只能使用输入中已有的信息；\n"
            "2. 可以适度安抚用户情绪，但不要空泛安慰；\n"
            "3. 规则结果已经决定了意图、动作、是否转人工、缺少哪些材料，你不能改这些结论；\n"
            "4. 你只负责把规则结果改写成更自然的客服话术；\n"
            "5. 如果规则回复已经给出明确信息，不要改写成更空泛的状态播报。\n"
            "输出要求：\n"
            "1. 只输出JSON；\n"
            "2. 不要输出Markdown；\n"
            "3. 不要输出额外解释。\n"
            f"JSON字段示例：{json.dumps(schema, ensure_ascii=False)}"
        )

    @staticmethod
    def _user_prompt(context: ConversationContext, fallback_result: AgentResult) -> str:
        order = context.selected_order
        image_review = context.image_review
        payload = {
            "order_info": {
                "order_id": order.order_id,
                "product_name": order.items[0].product_name if order.items else "",
                "category": order.items[0].category if order.items else "",
                "order_status": order.status.value,
                "after_sales_status": order.after_sales_status.value,
                "amount": order.amount,
                "refund_status": order.refund_status,
                "logistics_status": order.logistics_status,
                "uploaded_evidence": list(order.uploaded_evidence),
            },
            "history_summary": QwenReturnService._build_history_summary(context, fallback_result),
            "recent_history": [
                {
                    "role": message.role,
                    "content": message.content,
                    "create_time": QwenReturnService._format_message_time(message),
                }
                for message in context.recent_history
            ],
            "conversation": {
                "user_message": context.message,
                "description": context.description,
                "item_opened": context.item_opened,
                "human_request_count": context.human_request_count,
                "attachments": [attachment.kind for attachment in context.attachments],
            },
            "image_review": QwenReturnService._serialize_image_review(image_review),
            "rule_result": {
                "decision": fallback_result.decision.value,
                "intent": fallback_result.intent.value,
                "next_agent": fallback_result.next_agent,
                "need_human": fallback_result.need_human,
                "current_status": fallback_result.current_status.value,
                "scene": fallback_result.scene.value,
                "allowed_actions": list(fallback_result.allowed_actions),
                "missing_fields": list(fallback_result.missing_fields),
                "suggested_action": fallback_result.suggested_action,
                "user_reply": fallback_result.user_reply,
                "progress_hint": fallback_result.progress_hint,
                "risk_level": fallback_result.risk_level.value,
                "audit_note": fallback_result.audit_note,
            },
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @staticmethod
    def _build_history_summary(
        context: ConversationContext,
        fallback_result: AgentResult,
    ) -> dict[str, Any]:
        if context.history_summary is not None:
            return context.history_summary
        return {
            "用户核心诉求": fallback_result.intent.value,
            "已提供证据": list(context.selected_order.uploaded_evidence if context.selected_order else ()),
            "仍缺少证据": list(fallback_result.missing_fields),
            "当前售后状态": fallback_result.current_status.value,
            "是否已解释过": QwenReturnService._has_explained_progress(context.recent_history),
            "是否多次追问": QwenReturnService._has_multiple_follow_ups(context),
            "是否要求人工": QwenReturnService._asked_for_human(context),
            "用户情绪": QwenReturnService._infer_emotion(context),
        }

    @staticmethod
    def _format_message_time(message: ConversationMessage) -> str | None:
        if not isinstance(message.create_time, datetime):
            return None
        return message.create_time.strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _has_explained_progress(history: tuple[ConversationMessage, ...]) -> bool:
        progress_keywords = ("审核", "进度", "退款流程", "状态更新", "处理中", "催办")
        return any(
            message.role == "assistant"
            and any(keyword in message.content for keyword in progress_keywords)
            for message in history
        )

    @staticmethod
    def _has_multiple_follow_ups(context: ConversationContext) -> bool:
        user_messages = [message for message in context.recent_history if message.role == "user"]
        return context.human_request_count >= 2 or len(user_messages) >= 2

    @staticmethod
    def _asked_for_human(context: ConversationContext) -> bool:
        human_keywords = ("人工", "真人", "客服")
        if context.human_request_count > 0:
            return True
        if any(keyword in context.message for keyword in human_keywords):
            return True
        return any(
            message.role == "user" and any(keyword in message.content for keyword in human_keywords)
            for message in context.recent_history
        )

    @staticmethod
    def _infer_emotion(context: ConversationContext) -> str:
        anxious_keywords = ("怎么还", "什么时候", "多久", "一直没", "还没")
        complaint_keywords = ("投诉", "差评", "生气", "太慢", "举报")
        combined = " ".join([message.content for message in context.recent_history] + [context.message])
        if any(keyword in combined for keyword in complaint_keywords):
            return "不满"
        if any(keyword in combined for keyword in anxious_keywords):
            return "着急"
        return "平稳"

    @staticmethod
    def _serialize_image_review(image_review: ImageReviewResult | None) -> dict[str, Any] | None:
        if image_review is None:
            return None
        return {
            "success": image_review.success,
            "has_damage_area": image_review.has_damage_area,
            "has_outer_package": image_review.has_outer_package,
            "has_logistics_label": image_review.has_logistics_label,
            "logistics_matches_order": image_review.logistics_matches_order,
            "courier_company": image_review.courier_company,
            "tracking_number": image_review.tracking_number,
            "sender_name": image_review.sender_name,
            "receiver_name": image_review.receiver_name,
            "missing_visual_evidence": list(image_review.missing_visual_evidence),
            "summary": image_review.summary,
        }

    @staticmethod
    def _extract_visual_evidence(image_review: ImageReviewResult) -> tuple[str, ...]:
        if not image_review.success:
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
    def _is_visual_review_failed(
        attachments: tuple[Any, ...],
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
    def _parse_bool(value: Any, fallback: bool | None) -> bool | None:
        if isinstance(value, bool):
            return value
        if value is None:
            return fallback
        text = str(value).strip().lower()
        if text == "true":
            return True
        if text == "false":
            return False
        return fallback

    @staticmethod
    def _normalize_reply(reply: str, fallback_reply: str) -> str:
        cleaned = " ".join(reply.split())
        banned_phrases = (
            "请随时联系我们",
            "竭诚为您服务",
            "感谢您的理解",
            "感谢理解",
            "很抱歉给您带来不便",
            "谢谢您的配合",
            "感谢您的配合",
            "和支持",
        )
        for phrase in banned_phrases:
            cleaned = cleaned.replace(phrase, "")
        cleaned = cleaned.strip(" ，。")
        if not cleaned:
            return fallback_reply
        if len(cleaned) > 100:
            return fallback_reply
        if not cleaned.endswith(("。", "！", "？")):
            cleaned = cleaned + "。"
        return cleaned

    @classmethod
    def _build_user_reply(cls, raw: dict[str, Any], fallback_result: AgentResult) -> str:
        if cls._must_use_rule_reply(fallback_result):
            return fallback_result.user_reply
        candidate = cls._normalize_reply(
            str(raw.get("assistant_reply") or fallback_result.user_reply),
            fallback_result.user_reply,
        )
        if cls._should_use_fallback_reply(candidate, fallback_result.user_reply):
            return fallback_result.user_reply
        return candidate

    @staticmethod
    def _must_use_rule_reply(fallback_result: AgentResult) -> bool:
        return QwenReturnService._should_skip_model(fallback_result)

    @staticmethod
    def _should_use_fallback_reply(candidate: str, fallback_reply: str) -> bool:
        generic_markers = (
            "请详细描述",
            "请您详细描述",
            "请再说明一下",
            "请上传耳机的详细图片",
            "请上传详细图片",
            "以便我们更好地帮助您处理",
            "是想申请售后",
            "查询进度还是联系人工",
            "联系人工客服处理呢",
        )
        if candidate == fallback_reply:
            return False
        return any(marker in candidate for marker in generic_markers)


def sample_context() -> ConversationContext:
    from datetime import timedelta
    from .models import AfterSalesStatus, Attachment, Order, OrderItem, OrderStatus

    now = datetime.now()
    order = Order(
        order_id="202405220123456789",
        user_id="u1001",
        status=OrderStatus.AFTER_SALES,
        amount=399.0,
        created_at=now - timedelta(days=5),
        shipped_at=now - timedelta(days=4),
        delivered_at=now - timedelta(days=2),
        items=(OrderItem("sku-1", "轻音降噪无线耳机 X3", "数码", 1, 399.0),),
        has_open_after_sales=True,
        after_sales_status=AfterSalesStatus.MERCHANT_REVIEW,
        refund_status="未开始",
        uploaded_evidence=("破损照片",),
    )
    return ConversationContext(
        user_id="u1001",
        selected_order=order,
        message="我的耳机破损了，退款什么时候到账？",
        description="左耳没有声音",
        attachments=(Attachment(kind="破损照片", name="damage.jpg"),),
    )
