from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import json
from typing import Any

from ..agents.return_agent import ReturnAgent
from .conversation import ConversationContext, build_after_sales_request
from ..agents.emotion_agent import EmotionAgent
from .knowledge_retrieval import KnowledgeRetrievalClient
from .llm import LLMError, OpenAICompatibleClient, OpenAICompatibleConfig
from .qwen_knowledge_support import (
    build_knowledge_answer_reply,
    knowledge_query,
    knowledge_sources,
    pick_knowledge_answer_hit,
    prompt_ready_knowledge,
)
from .qwen_reply_support import (
    build_user_reply,
    normalize_reply_text,
    parse_bool,
    parse_confidence,
    parse_intent,
    parse_scene,
)
from .qwen_understanding_support import (
    apply_scene_guardrail,
    fallback_normalized_issue,
    has_logistics_keywords,
    has_refund_progress_keywords,
    is_refund_progress_query,
    looks_like_specific_issue,
    repair_request_without_understanding,
    repair_understanding_choice,
)
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
        self.knowledge_client = KnowledgeRetrievalClient()
        self.rule_agent = rule_agent or ReturnAgent()

    def bind_trace(self, trace_recorder: TraceRecorder | None) -> None:
        self.client.bind_trace(trace_recorder)
        self.knowledge_client.bind_trace(trace_recorder)

    def handle(self, context: ConversationContext) -> LLMConversationResult:
        request, conversation_understanding = self._build_request_with_conversation_understanding(context)
        if not self._has_valid_conversation_understanding(conversation_understanding):
            return self._understanding_unavailable_result(context, request, conversation_understanding)

        fallback_result = self.rule_agent.handle(
            request=request,
            order=context.selected_order,
        )
        retrieved_knowledge = self._retrieve_knowledge(context, fallback_result)
        knowledge_result = self._maybe_build_knowledge_short_circuit(
            context=context,
            fallback_result=fallback_result,
            retrieved_knowledge=retrieved_knowledge,
            mode="knowledge_short_circuit",
            conversation_understanding=conversation_understanding,
        )
        if knowledge_result is not None:
            return knowledge_result
        if self._should_skip_model(fallback_result):
            return LLMConversationResult(
                assistant_reply=fallback_result.user_reply,
                intent=fallback_result.intent.value,
                item_opened=context.item_opened,
                evidence_needed=fallback_result.missing_fields,
                suggested_action=fallback_result.suggested_action or fallback_result.decision.value,
                raw={
                    "mode": "rule_after_understanding",
                    "conversation_understanding": conversation_understanding,
                    "retrieved_knowledge": retrieved_knowledge,
                },
                fallback_result=fallback_result,
            )

        try:
            raw = self.client.chat_json(
                system_prompt=self._system_prompt(),
                user_prompt=self._user_prompt(context, fallback_result, retrieved_knowledge),
            )
            if conversation_understanding is not None:
                raw["conversation_understanding"] = conversation_understanding
            raw["retrieved_knowledge"] = retrieved_knowledge
            reply = build_user_reply(
                raw,
                fallback_result,
                use_rule_reply=self._should_skip_model(fallback_result),
            )
            item_opened = parse_bool(raw.get("item_opened"), context.item_opened)
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
                    "retrieved_knowledge": retrieved_knowledge,
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
        intent = parse_intent(raw.get("intent"))
        scene = parse_scene(raw.get("scene"))
        if intent is None or scene is None:
            intent, scene = repair_understanding_choice(
                raw=raw,
                request=request,
                normalized_issue=normalized_issue,
                reason=reason,
                intent=intent,
                scene=scene,
            )
        confidence = parse_confidence(raw.get("confidence"))
        is_detailed = parse_bool(raw.get("quality_description_detailed"), None)
        evidence_consistent = parse_bool(raw.get("evidence_consistent"), None)
        if intent is None or scene is None:
            return request, {"mode": "invalid_model_output", "raw": raw}
        if looks_like_specific_issue(request.message):
            normalized_issue = str(request.message or "").strip()
        elif not normalized_issue:
            normalized_issue = fallback_normalized_issue(request)
        if is_refund_progress_query(context, request):
            intent = Intent.REFUND_PROGRESS
            scene = AfterSalesScene.PROGRESS_QUERY
            normalized_issue = ""
            is_detailed = None
            if confidence < 0.8:
                confidence = 0.8
        if is_detailed is None and normalized_issue:
            is_detailed = looks_like_specific_issue(normalized_issue)
        if self._is_generic_quality_description_only(request, normalized_issue):
            is_detailed = False
        scene = apply_scene_guardrail(scene, request, normalized_issue)
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
    def _has_valid_conversation_understanding(review: dict[str, Any] | None) -> bool:
        return bool(review and review.get("mode") == "llm")

    def _understanding_unavailable_result(
        self,
        context: ConversationContext,
        request: AfterSalesRequest,
        review: dict[str, Any] | None,
    ) -> LLMConversationResult:
        fallback_request = repair_request_without_understanding(request, context)
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
        retrieved_knowledge = self._retrieve_knowledge(context, fallback_result)
        knowledge_result = self._maybe_build_knowledge_short_circuit(
            context=context,
            fallback_result=fallback_result,
            retrieved_knowledge=retrieved_knowledge,
            mode="knowledge_short_circuit_after_understanding_fallback",
            conversation_understanding=review,
        )
        if knowledge_result is not None:
            return knowledge_result
        return LLMConversationResult(
            assistant_reply=fallback_result.user_reply,
            intent=fallback_result.intent.value,
            item_opened=context.item_opened,
            evidence_needed=fallback_result.missing_fields,
            suggested_action=fallback_result.suggested_action or fallback_result.decision.value,
            raw={
                "mode": "understanding_unavailable",
                "conversation_understanding": review,
                "retrieved_knowledge": retrieved_knowledge,
            },
            fallback_result=fallback_result,
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
    def _user_prompt(
        context: ConversationContext,
        fallback_result: AgentResult,
        retrieved_knowledge: dict[str, Any] | None,
    ) -> str:
        order = context.selected_order
        image_review = context.image_review
        payload = {
            "order_info": {
                "order_id": order.order_id if order else None,
                "product_name": order.items[0].product_name if order and order.items else "",
                "category": order.items[0].category if order and order.items else "",
                "order_status": order.status.value if order else None,
                "after_sales_status": order.after_sales_status.value if order else None,
                "amount": order.amount if order else None,
                "refund_status": order.refund_status if order else None,
                "logistics_status": order.logistics_status if order else None,
                "uploaded_evidence": list(order.uploaded_evidence) if order else [],
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
            "knowledge_usage_rules": {
                "goal": "Use retrieved knowledge only for explanation and reply grounding.",
                "must_not_override": [
                    "rule_result.decision",
                    "rule_result.intent",
                    "rule_result.missing_fields",
                    "rule_result.need_human",
                    "rule_result.suggested_action",
                ],
            },
            "retrieved_knowledge": prompt_ready_knowledge(retrieved_knowledge),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _retrieve_knowledge(
        self,
        context: ConversationContext,
        fallback_result: AgentResult,
    ) -> dict[str, Any]:
        order = context.selected_order
        product_category = order.items[0].category if order and order.items else None
        merchant_code = order.merchant_code if order else None
        return self.knowledge_client.retrieve(
            query=knowledge_query(context),
            merchant_code=merchant_code,
            product_category=product_category,
            scene=fallback_result.scene.value,
            intent=fallback_result.intent.value,
            top_k=4,
            sources=knowledge_sources(fallback_result),
        )

    @classmethod
    def _maybe_build_knowledge_short_circuit(
        cls,
        *,
        context: ConversationContext,
        fallback_result: AgentResult,
        retrieved_knowledge: dict[str, Any] | None,
        mode: str,
        conversation_understanding: dict[str, Any] | None,
    ) -> LLMConversationResult | None:
        knowledge_hit = pick_knowledge_answer_hit(
            context,
            fallback_result,
            retrieved_knowledge,
            has_logistics_keywords=has_logistics_keywords,
        )
        if knowledge_hit is None:
            return None
        reply = build_knowledge_answer_reply(
            knowledge_hit,
            fallback_result.user_reply,
            normalize_reply_text=normalize_reply_text,
        )
        if not reply:
            return None
        knowledge_result = replace(
            fallback_result,
            decision=Decision.RESPOND,
            user_reply=reply,
            intent=Intent.GENERAL,
            next_agent="知识解释",
            need_human=False,
            missing_fields=(),
            suggested_action="知识解释",
            progress_hint=None,
            audit_note=cls._merge_note(
                fallback_result.audit_note,
                f"knowledge_short_circuit source={knowledge_hit.get('source_type')} title={knowledge_hit.get('title')}",
            ),
        )
        return LLMConversationResult(
            assistant_reply=reply,
            intent=knowledge_result.intent.value,
            item_opened=context.item_opened,
            evidence_needed=(),
            suggested_action=knowledge_result.suggested_action or knowledge_result.decision.value,
            raw={
                "mode": mode,
                "conversation_understanding": conversation_understanding,
                "knowledge_hit": {
                    "source_type": knowledge_hit.get("source_type"),
                    "source_code": knowledge_hit.get("source_code"),
                    "title": knowledge_hit.get("title"),
                    "summary": knowledge_hit.get("summary"),
                    "snippet": knowledge_hit.get("snippet"),
                    "score": knowledge_hit.get("score"),
                },
                "retrieved_knowledge": retrieved_knowledge,
            },
            fallback_result=knowledge_result,
        )

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
            "用户情绪": QwenReturnService._infer_emotion_summary(context),
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
            "satisfied": "满意",
            "calm": "平稳",
            "anxious": "着急",
            "dissatisfied": "不满",
            "angry": "愤怒",
        }
        return mapping.get(emotion.label.value, "平稳")

    @staticmethod
    def _infer_emotion_summary(context: ConversationContext) -> str:
        from ..merchant_policy import MerchantPolicyRegistry

        request = build_after_sales_request(context)
        policy_resolution = MerchantPolicyRegistry.from_env().resolve_with_context(
            order=context.selected_order,
            request=request,
        )
        emotion = EmotionAgent().analyze(
            request,
            context.selected_order,
            recent_history=context.recent_history,
            knowledge_base=policy_resolution.knowledge_base,
            handoff_min_level=policy_resolution.service_policy.emotion_handoff_min_level,
        )
        mapping = {
            "satisfied": "满意",
            "calm": "平稳",
            "anxious": "着急",
            "dissatisfied": "不满",
            "angry": "愤怒",
        }
        return mapping.get(emotion.label.value, "平稳")

def sample_context() -> ConversationContext:
    from datetime import timedelta
    from ..models import AfterSalesStatus, Attachment, Order, OrderItem, OrderStatus

    now = datetime.now()
    order = Order(
        order_id="202405220123456789",
        user_id="u1001",
        status=OrderStatus.DELIVERED,
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
