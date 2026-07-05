from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import json
from typing import Any

from ..agents.return_agent import ReturnAgent
from .conversation import ConversationContext, build_after_sales_request
from ..agents.emotion_agent import EmotionAgent
from .llm import LLMError, OpenAICompatibleClient, OpenAICompatibleConfig
from ..models import (
    AfterSalesRequest,
    AfterSalesScene,
    AfterSalesStatus,
    AgentResult,
    ConversationMessage,
    Decision,
    Intent,
    RiskLevel,
    TicketStatus,
)
from ..infra.trace import TraceRecorder
from ..utils.vision_utils import serialize_image_review


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
        request, conversation_understanding = self._build_request_with_conversation_understanding(context)
        if not self._has_valid_conversation_understanding(conversation_understanding):
            return self._understanding_unavailable_result(context, request, conversation_understanding)

        fallback_result = self.rule_agent.handle(
            request=request,
            order=context.selected_order,
        )
        if context.selected_order is None or self._should_skip_model(fallback_result):
            return LLMConversationResult(
                assistant_reply=fallback_result.user_reply,
                intent=fallback_result.intent.value,
                item_opened=context.item_opened,
                evidence_needed=fallback_result.missing_fields,
                suggested_action=fallback_result.suggested_action or fallback_result.decision.value,
                raw={
                    "mode": "rule_after_understanding",
                    "conversation_understanding": conversation_understanding,
                },
                fallback_result=fallback_result,
            )

        try:
            raw = self.client.chat_json(
                system_prompt=self._system_prompt(),
                user_prompt=self._user_prompt(context, fallback_result),
            )
            if conversation_understanding is not None:
                raw["conversation_understanding"] = conversation_understanding
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
                raw={
                    "mode": "reply_model_unavailable",
                    "error": str(exc),
                    "conversation_understanding": conversation_understanding,
                },
                fallback_result=fallback_result,
            )

    def _build_request_with_conversation_understanding(
        self,
        context: ConversationContext,
    ) -> tuple[AfterSalesRequest, dict[str, Any] | None]:
        request = build_after_sales_request(context)

        try:
            raw = self.client.chat_json(
                system_prompt=self._conversation_understanding_system_prompt(),
                user_prompt=self._conversation_understanding_user_prompt(context, request),
                temperature=0.0,
                max_tokens=260,
            )
        except LLMError as exc:
            return request, {"mode": "model_unavailable", "error": str(exc)}

        normalized_issue = str(raw.get("normalized_issue") or "")
        reason = str(raw.get("reason") or "")
        intent = self._parse_intent(raw.get("intent"))
        scene = self._parse_scene(raw.get("scene"))
        if intent is None or scene is None:
            intent, scene = self._repair_understanding_choice(
                raw=raw,
                request=request,
                normalized_issue=normalized_issue,
                reason=reason,
                intent=intent,
                scene=scene,
            )
        confidence = self._parse_confidence(raw.get("confidence"))
        is_detailed = self._parse_bool(raw.get("quality_description_detailed"), None)
        evidence_consistent = self._parse_bool(raw.get("evidence_consistent"), None)
        if intent is None or scene is None:
            return request, {"mode": "invalid_model_output", "raw": raw}
        if self._looks_like_specific_issue(request.message):
            normalized_issue = str(request.message or "").strip()
        elif not normalized_issue:
            normalized_issue = self._fallback_normalized_issue(request)
        if self._is_refund_progress_query(context, request):
            intent = Intent.REFUND_PROGRESS
            scene = AfterSalesScene.PROGRESS_QUERY
            normalized_issue = ""
            is_detailed = None
            if confidence < 0.8:
                confidence = 0.8
        if is_detailed is None and normalized_issue:
            is_detailed = self._looks_like_specific_issue(normalized_issue)
        if self._is_generic_quality_description_only(request, normalized_issue):
            is_detailed = False
        if (
            intent == Intent.SUPPLEMENT_EVIDENCE
            and context.selected_order is not None
            and getattr(
                context.selected_order.after_sales_status,
                "value",
                context.selected_order.after_sales_status,
            ) == AfterSalesStatus.NOT_APPLIED.value
            and (normalized_issue or request.visual_evidence)
        ):
            intent = Intent.APPLY_AFTER_SALES
        if (
            intent == Intent.APPLY_AFTER_SALES
            and scene != AfterSalesScene.GENERAL
            and normalized_issue
            and confidence < 0.6
        ):
            confidence = 0.8
        missing_detail = str(raw.get("missing_detail") or "")
        if (
            scene == AfterSalesScene.QUALITY_ISSUE
            and is_detailed is True
            and self._is_generic_quality_description_only(request, normalized_issue)
        ):
            is_detailed = False
            missing_detail = missing_detail or "具体异常表现"
            reason = f"{reason}；文本只有概括性质量问题描述，未采纳详细描述判断。".strip("；")

        review = {
            "mode": "llm",
            "intent": intent.value,
            "scene": scene.value,
            "confidence": confidence,
            "quality_description_detailed": is_detailed,
            "evidence_consistent": evidence_consistent,
            "reason": reason,
            "normalized_issue": normalized_issue,
            "missing_detail": missing_detail,
        }
        return replace(
            request,
            llm_intent=intent,
            llm_scene=scene,
            llm_confidence=confidence,
            normalized_issue=review["normalized_issue"],
            quality_description_detailed=is_detailed,
            evidence_consistent=evidence_consistent,
        ), review

    @staticmethod
    def _fallback_normalized_issue(request: AfterSalesRequest) -> str:
        for value in (request.message, request.description, request.reason):
            text = str(value or "").strip()
            if text and QwenReturnService._looks_like_specific_issue(text):
                return text
        return ""

    @staticmethod
    def _looks_like_specific_issue(text: str) -> bool:
        normalized = str(text or "").strip().lower()
        if not normalized:
            return False
        generic_words = ("质量问题", "商品有问题", "申请售后", "售后申请", "补充说明")
        if normalized in generic_words:
            return False
        specific_markers = (
            "破", "裂", "碎", "坏", "损", "凹", "断",
            "没声音", "没有声音", "不响", "无法开机", "不能开机", "充电", "连接失败", "按键失灵",
        )
        return any(marker in normalized for marker in specific_markers)

    @staticmethod
    def _repair_understanding_choice(
        *,
        raw: dict[str, Any],
        request: AfterSalesRequest,
        normalized_issue: str,
        reason: str,
        intent: Intent | None,
        scene: AfterSalesScene | None,
    ) -> tuple[Intent | None, AfterSalesScene | None]:
        raw_intent = str(raw.get("intent") or "").strip().lower()
        raw_scene = str(raw.get("scene") or "").strip().lower()
        combined = " ".join(
            part
            for part in (request.message, request.description, normalized_issue, reason)
            if part
        ).lower()

        if intent is None:
            if raw_intent == "progress_query" or QwenReturnService._has_refund_progress_keywords(combined):
                intent = Intent.REFUND_PROGRESS
            elif any(keyword in combined for keyword in ("人工", "客服", "真人")):
                intent = Intent.HUMAN_SERVICE
            elif any(keyword in combined for keyword in ("进度", "退款", "到账")):
                intent = Intent.REFUND_PROGRESS
            elif any(keyword in combined for keyword in ("凭证", "图片", "照片", "补充")):
                intent = Intent.SUPPLEMENT_EVIDENCE
            elif "|" in raw_intent and combined:
                intent = Intent.APPLY_AFTER_SALES
            elif "|" in raw_intent:
                intent = Intent.GENERAL

        if scene is None:
            if raw_scene == "progress_query" or QwenReturnService._has_refund_progress_keywords(combined):
                scene = AfterSalesScene.PROGRESS_QUERY
            elif any(keyword in combined for keyword in ("包装", "外包装", "盒子", "快递袋")):
                scene = AfterSalesScene.PACKAGE_DAMAGE
            elif any(keyword in combined for keyword in ("破", "裂", "碎", "坏", "损", "外壳")):
                scene = AfterSalesScene.PRODUCT_DAMAGE
            elif any(keyword in combined for keyword in ("少", "漏", "错发", "数量")):
                scene = AfterSalesScene.WRONG_OR_MISSING_ITEMS
            elif any(keyword in combined for keyword in ("物流", "快递", "配送")):
                scene = AfterSalesScene.LOGISTICS_ISSUE
            elif "|" in raw_scene and combined:
                scene = AfterSalesScene.QUALITY_ISSUE
            elif "|" in raw_scene:
                scene = AfterSalesScene.GENERAL

        return intent, scene

    @staticmethod
    def _has_valid_conversation_understanding(review: dict[str, Any] | None) -> bool:
        return bool(review and review.get("mode") == "llm")

    def _understanding_unavailable_result(
        self,
        context: ConversationContext,
        request: AfterSalesRequest,
        review: dict[str, Any] | None,
    ) -> LLMConversationResult:
        fallback_request = self._repair_request_without_understanding(request, context)
        fallback_result = self.rule_agent.handle(
            request=fallback_request,
            order=context.selected_order,
        )
        fallback_result = replace(
            fallback_result,
            audit_note=self._merge_note(
                fallback_result.audit_note,
                f"conversation_understanding_unavailable review={review}",
            ),
        )
        return LLMConversationResult(
            assistant_reply=fallback_result.user_reply,
            intent=fallback_result.intent.value,
            item_opened=context.item_opened,
            evidence_needed=fallback_result.missing_fields,
            suggested_action=fallback_result.suggested_action or fallback_result.decision.value,
            raw={
                "mode": "understanding_unavailable",
                "conversation_understanding": review,
            },
            fallback_result=fallback_result,
        )

    @staticmethod
    def _repair_request_without_understanding(
        request: AfterSalesRequest,
        context: ConversationContext,
    ) -> AfterSalesRequest:
        text = QwenReturnService._combined_user_text(context, request)
        if QwenReturnService._has_refund_progress_keywords(text):
            return replace(
                request,
                llm_intent=Intent.REFUND_PROGRESS,
                llm_scene=AfterSalesScene.PROGRESS_QUERY,
                llm_confidence=max(request.llm_confidence, 0.8),
            )
        if any(keyword in text for keyword in ("人工", "真人客服", "转人工")):
            return replace(
                request,
                llm_intent=Intent.HUMAN_SERVICE,
                llm_confidence=max(request.llm_confidence, 0.8),
            )
        if any(keyword in text for keyword in ("补充凭证", "上传凭证", "补充图片", "上传图片", "补充照片")):
            return replace(
                request,
                llm_intent=Intent.SUPPLEMENT_EVIDENCE,
                llm_confidence=max(request.llm_confidence, 0.8),
            )
        return request

    @staticmethod
    def _combined_user_text(context: ConversationContext, request: AfterSalesRequest) -> str:
        parts = [request.message or "", request.description or "", request.reason or ""]
        parts.extend(
            message.content
            for message in context.recent_history[-4:]
            if message.role == "user" and message.content
        )
        return "".join(parts).lower()

    @staticmethod
    def _is_refund_progress_query(
        context: ConversationContext,
        request: AfterSalesRequest,
    ) -> bool:
        current_text = "".join(
            part for part in (request.message, request.description, request.reason) if part
        ).lower()
        if QwenReturnService._has_refund_progress_keywords(current_text):
            return True
        return QwenReturnService._has_refund_progress_keywords(
            QwenReturnService._combined_user_text(context, request)
        )

    @staticmethod
    def _has_refund_progress_keywords(text: str) -> bool:
        return any(
            keyword in text
            for keyword in (
                "退款进度",
                "查看退款",
                "查退款",
                "退款状态",
                "什么时候退款",
                "什么时候退",
                "什么时候能退",
                "多久到账",
                "退钱",
                "到账",
            )
        )

    @staticmethod
    def _merge_note(base: str | None, extra: str) -> str:
        return f"{base}; {extra}" if base else extra

    @staticmethod
    def _conversation_understanding_system_prompt() -> str:
        schema = {
            "intent": "apply_after_sales|refund_progress|return_logistics|supplement_evidence|merchant_rejected|refund_only|exchange_repair|human_service|complaint|general",
            "scene": "quality_issue|product_damage|package_damage|wrong_or_missing_items|logistics_issue|progress_query|general",
            "confidence": "0到1之间的小数",
            "quality_description_detailed": "boolean|null，仅质量/功能异常场景需要判断",
            "evidence_consistent": "boolean|null。图与描述是否一致。可见破损+损伤描述=true 功能异常描述+可见破损=false 无图=null",
            "normalized_issue": "提炼出的具体异常，无法提炼则为空字符串",
            "missing_detail": "如果信息不够，还缺什么信息",
            "reason": "一句话说明判断依据",
        }
        return (
            "你是售后系统里的对话理解器，负责把用户当前消息结合图片审核结果转换成结构化结论。\n"
            "必须识别用户是在申请售后、查询进度、补充凭证、要求人工，还是普通咨询。\n"
            "quality_description_detailed true=具体异常(没声音 无法开机 闪烁 裂开 碎裂 按键失灵) false=概括(质量问题 已上传图片)。\n"
            "evidence_consistent 根据 image_review 的 has_damage_area/has_outer_package/has_logistics_label 与用户描述对比：\n"
            "  true=图片可印证描述(破损图+破损描述 物流面单+物流问题)\n"
            "  false=图片无法印证(破损图+功能异常描述如没声音/闪烁)\n"
            "  null=无图片或无法判断\n"
            "只输出 JSON，不要输出 Markdown 或额外解释。\n"
            f"JSON字段示例：{json.dumps(schema, ensure_ascii=False)}"
        )

    @staticmethod
    def _conversation_understanding_user_prompt(
        context: ConversationContext,
        request: AfterSalesRequest,
    ) -> str:
        order = context.selected_order
        payload = {
            "product": {
                "name": order.items[0].product_name if order and order.items else "",
                "category": order.items[0].category if order and order.items else "",
            },
            "current_message": request.message,
            "description": request.description,
            "image_review": serialize_image_review(context.image_review, include_items=False),
            "recent_user_history": [
                message.content
                for message in context.recent_history
                if message.role == "user" and message.content
            ][-5:],
            "recent_assistant_history": [
                message.content
                for message in context.recent_history
                if message.role == "assistant" and message.content
            ][-5:],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @staticmethod
    def _is_generic_quality_description_only(
        request: AfterSalesRequest,
        normalized_issue: str,
    ) -> bool:
        combined = " ".join(
            part.strip()
            for part in (
                request.message,
                request.reason,
                request.description,
                normalized_issue,
            )
            if part
        )
        if not combined:
            return True
        normalized = "".join(ch for ch in combined.lower() if ch not in " ，。！？：；、,.!?:;/\\|_-")
        generic_phrases = (
            "历史用户补充",
            "我想申请售后",
            "申请售后",
            "售后申请",
            "我想",
            "想",
            "原因是",
            "补充说明",
            "问题类型",
            "质量问题",
            "商品质量",
            "产品质量",
            "质量",
            "问题",
            "异常表现",
            "异常",
            "图片",
            "照片",
            "凭证",
            "商品",
            "已经上传",
            "已上传",
            "请先分析",
            "售后",
            "处理",
        )
        for phrase in generic_phrases:
            normalized = normalized.replace(phrase, "")
        return len(normalized) < 2

    @staticmethod
    def _should_skip_model(fallback_result: AgentResult) -> bool:
        if fallback_result.decision == Decision.ESCALATE_HUMAN:
            return True
        if (
            fallback_result.ticket is not None
            and fallback_result.ticket.status == TicketStatus.AUTO_APPROVED
        ):
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
            "7. 每次回复不超过100字；\n"
            "8. 不要说已提交或已创建售后申请，不要展示售后编号、工单编号或ticket_id；\n"
            "9. 不要暴露自动审核、图片识别、风险等级、策略引擎、Agent等系统术语。\n"
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
            "image_review": serialize_image_review(image_review, include_items=False),
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
        emotion = EmotionAgent().analyze(
            build_after_sales_request(context),
            context.selected_order,
            recent_history=context.recent_history,
        )
        mapping = {
            "calm": "平稳",
            "anxious": "着急",
            "dissatisfied": "不满",
            "angry": "愤怒",
        }
        return mapping.get(emotion.label.value, "平稳")

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
    def _parse_intent(value: Any) -> Intent | None:
        if isinstance(value, Intent):
            return value
        text = str(value or "").strip().lower()
        for intent in Intent:
            if intent.value == text:
                return intent
        alias_map = {
            "申请售后": Intent.APPLY_AFTER_SALES,
            "售后申请": Intent.APPLY_AFTER_SALES,
            "查询进度": Intent.REFUND_PROGRESS,
            "退款进度": Intent.REFUND_PROGRESS,
            "退货物流": Intent.RETURN_LOGISTICS,
            "补充凭证": Intent.SUPPLEMENT_EVIDENCE,
            "转人工": Intent.HUMAN_SERVICE,
            "人工客服": Intent.HUMAN_SERVICE,
            "投诉": Intent.COMPLAINT,
            "普通咨询": Intent.GENERAL,
        }
        return alias_map.get(text)

    @staticmethod
    def _parse_scene(value: Any) -> AfterSalesScene | None:
        if isinstance(value, AfterSalesScene):
            return value
        text = str(value or "").strip().lower()
        for scene in AfterSalesScene:
            if scene.value == text:
                return scene
        alias_map = {
            "质量问题": AfterSalesScene.QUALITY_ISSUE,
            "功能异常": AfterSalesScene.QUALITY_ISSUE,
            "质量问题/功能异常": AfterSalesScene.QUALITY_ISSUE,
            "商品破损": AfterSalesScene.PRODUCT_DAMAGE,
            "包装破损": AfterSalesScene.PACKAGE_DAMAGE,
            "少发漏发": AfterSalesScene.WRONG_OR_MISSING_ITEMS,
            "错发": AfterSalesScene.WRONG_OR_MISSING_ITEMS,
            "物流异常": AfterSalesScene.LOGISTICS_ISSUE,
            "进度查询": AfterSalesScene.PROGRESS_QUERY,
            "普通咨询": AfterSalesScene.GENERAL,
        }
        return alias_map.get(text)

    @staticmethod
    def _parse_confidence(value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, confidence))

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
        banned_markers = (
            "已为您提交售后申请",
            "已帮您创建售后申请",
            "售后申请已提交",
            "售后编号",
            "工单编号",
            "工单",
            "ticket_id",
            "Ticket",
            "AS",
            "AI自动审核",
            "自动审核",
            "图片识别",
            "意图识别",
            "风险等级",
            "策略引擎",
            "自动化决策",
            "当前已进入处理中状态",
        )
        if candidate == fallback_reply:
            return False
        return any(marker in candidate for marker in generic_markers + banned_markers)


def sample_context() -> ConversationContext:
    from datetime import timedelta
    from ..models import AfterSalesStatus, Attachment, Order, OrderItem, OrderStatus

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
