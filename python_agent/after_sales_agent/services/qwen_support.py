from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from ..models import (
    AfterSalesRequest,
    AfterSalesScene,
    AgentResult,
    ConversationMessage,
    Decision,
    DecisionEnvelope,
    Intent,
)
from ..utils.vision_utils import serialize_image_review
from .conversation import ConversationContext


def has_valid_conversation_understanding(review: dict[str, Any] | None) -> bool:
    return bool(review and review.get("mode") == "llm")


def understanding_error(review: dict[str, Any] | None) -> str | None:
    if not review or review.get("mode") == "llm":
        return None
    if review.get("error"):
        return str(review["error"])
    return str(review.get("mode") or "understanding_unavailable")


def build_conversation_understanding_system_prompt() -> str:
    schema = {
        "intent": "apply_after_sales|refund_progress|return_logistics|supplement_evidence|merchant_rejected|refund_only|exchange_repair|human_service|complaint|general",
        "scene": "quality_issue|product_damage|package_damage|wrong_or_missing_items|logistics_issue|progress_query|general",
        "confidence": "0到1之间的小数",
        "quality_description_detailed": "boolean|null，仅质量/功能异常场景需要判断",
        "normalized_issue": "提炼出的具体异常，无法提炼则为空字符串",
        "missing_detail": "如果信息不够，还缺什么信息",
        "reason": "一句话说明判断依据",
    }
    return (
        "你是售后系统里的对话理解器，负责把用户当前消息结合近期上下文转换成结构化结论。\n"
        "必须识别用户当前是在申请售后、查询进度、补充凭证、要求人工，还是普通咨询。\n"
        "如果上一轮客服要求用户补充异常表现，当前用户只回复“没有声音”“连不上”“充不了电”等短句，"
        "也要理解为正在补充售后申请的质量/功能异常，而不是普通咨询。\n"
        "quality_description_detailed 判定为 true 的条件：用户描述了具体异常现象、受影响部位或故障行为，"
        "例如没有声音、某一侧不响、无法开机、充电异常、连接失败、按键失灵等。\n"
        "quality_description_detailed 判定为 false 的条件：只有质量问题、商品有问题、申请售后、补充说明、尽快处理、"
        "已上传图片等概括性表达。\n"
        "不要因为商品图片或凭证图片存在，就推断功能异常已经描述清楚；只根据文本里的异常描述判断。\n"
        "只输出 JSON，不要输出 Markdown 或额外解释。\n"
        f"JSON字段示例：{json.dumps(schema, ensure_ascii=False)}"
    )


def build_conversation_understanding_user_prompt(
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


def is_generic_quality_description_only(
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


def should_skip_model(fallback_result: AgentResult) -> bool:
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


def build_reply_system_prompt() -> str:
    schema = {
        "assistant_reply": "给用户看的中文回复，20到100字",
        "item_opened": "true|false|null",
        "confidence": "0到1之间的小数，表示你对本次回复是否合适的把握程度",
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


def build_reply_user_prompt(
    context: ConversationContext,
    decision_envelope: DecisionEnvelope,
) -> str:
    fallback_result = decision_envelope.result
    order = context.selected_order
    if order is None:
        raise ValueError("selected_order is required to build reply prompt")
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
        "history_summary": build_history_summary(context, decision_envelope),
        "recent_history": [
            {
                "role": message.role,
                "content": message.content,
                "create_time": format_message_time(message),
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
        "image_review": serialize_image_review(context.image_review, include_items=False),
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


def build_history_summary(
    context: ConversationContext,
    decision_envelope: DecisionEnvelope,
) -> dict[str, Any]:
    fallback_result = decision_envelope.result
    if context.history_summary is not None:
        return context.history_summary
    return {
        "用户核心诉求": fallback_result.intent.value,
        "已提供证据": list(context.selected_order.uploaded_evidence if context.selected_order else ()),
        "仍缺少证据": list(fallback_result.missing_fields),
        "当前售后状态": fallback_result.current_status.value,
        "是否已解释过": has_explained_progress(context.recent_history),
        "是否多次追问": has_multiple_follow_ups(context),
        "是否要求人工": asked_for_human(context),
        "用户情绪": infer_emotion(decision_envelope),
    }


def format_message_time(message: ConversationMessage) -> str | None:
    if not isinstance(message.create_time, datetime):
        return None
    return message.create_time.strftime("%Y-%m-%d %H:%M:%S")


def has_explained_progress(history: tuple[ConversationMessage, ...]) -> bool:
    progress_keywords = ("审核", "进度", "退款流程", "状态更新", "处理中", "催办")
    return any(
        message.role == "assistant"
        and any(keyword in message.content for keyword in progress_keywords)
        for message in history
    )


def has_multiple_follow_ups(context: ConversationContext) -> bool:
    user_messages = [message for message in context.recent_history if message.role == "user"]
    return context.human_request_count >= 2 or len(user_messages) >= 2


def asked_for_human(context: ConversationContext) -> bool:
    human_keywords = ("人工", "真人", "客服")
    if context.human_request_count > 0:
        return True
    if any(keyword in context.message for keyword in human_keywords):
        return True
    return any(
        message.role == "user" and any(keyword in message.content for keyword in human_keywords)
        for message in context.recent_history
    )


def infer_emotion(decision_envelope: DecisionEnvelope) -> str:
    emotion = decision_envelope.result.emotion
    if emotion is None:
        return "平稳"
    mapping = {
        "satisfied": "满意",
        "calm": "平稳",
        "anxious": "着急",
        "dissatisfied": "不满",
        "angry": "愤怒",
    }
    return mapping.get(emotion.label.value, "平稳")


def parse_bool(value: Any, fallback: bool | None) -> bool | None:
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


def parse_intent(value: Any) -> Intent | None:
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


def parse_scene(value: Any) -> AfterSalesScene | None:
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


def parse_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, confidence))


def extract_understanding_confidence(review: dict[str, Any] | None) -> float | None:
    if not review or review.get("mode") != "llm":
        return None
    value = review.get("confidence")
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, confidence))


def reply_confidence(raw: dict[str, Any], understanding_confidence: float | None) -> float:
    candidate = parse_confidence(raw.get("confidence"))
    if candidate > 0:
        return candidate
    return fallback_reply_confidence(understanding_confidence)


def fallback_reply_confidence(understanding_confidence: float | None) -> float:
    if understanding_confidence is not None and understanding_confidence > 0:
        return understanding_confidence
    return 0.9


def ticket_ai_confidence(
    understanding_confidence: float | None,
    fallback_result: AgentResult,
) -> float | None:
    if fallback_result.decision not in {Decision.CREATE_TICKET, Decision.ESCALATE_HUMAN}:
        return None
    if understanding_confidence is not None and understanding_confidence > 0:
        return understanding_confidence
    return 0.85


def normalize_reply(reply: str, fallback_reply: str) -> str:
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
    for bad, good in (
        ("，！", "！"),
        ("，。", "。"),
        ("，？", "？"),
        ("。。", "。"),
        ("！！", "！"),
        ("？？", "？"),
    ):
        cleaned = cleaned.replace(bad, good)
    cleaned = cleaned.rstrip(" ，、；：,;:")
    cleaned = cleaned.strip()
    if not cleaned:
        return fallback_reply
    if len(cleaned) > 100:
        return fallback_reply
    if not cleaned.endswith(("。", "！", "？")):
        cleaned = cleaned + "。"
    return cleaned


def build_user_reply(raw: dict[str, Any], fallback_result: AgentResult) -> str:
    if should_skip_model(fallback_result):
        return fallback_result.user_reply
    candidate = normalize_reply(
        str(raw.get("assistant_reply") or fallback_result.user_reply),
        fallback_result.user_reply,
    )
    if should_use_fallback_reply(candidate, fallback_result.user_reply):
        return fallback_result.user_reply
    return candidate


def should_use_fallback_reply(candidate: str, fallback_reply: str) -> bool:
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


def build_conversation_understanding_system_prompt_v2() -> str:
    allowed_intents = [
        "apply_after_sales",
        "refund_progress",
        "return_logistics",
        "supplement_evidence",
        "merchant_rejected",
        "refund_only",
        "exchange_repair",
        "human_service",
        "complaint",
        "general",
    ]
    allowed_scenes = [
        "quality_issue",
        "product_damage",
        "package_damage",
        "wrong_or_missing_items",
        "logistics_issue",
        "progress_query",
        "general",
    ]
    schema = {
        "intent": "必须从 intent_allowed 中且只能选择 1 个值",
        "scene": "必须从 scene_allowed 中且只能选择 1 个值",
        "confidence": "0 到 1 之间的小数",
        "quality_description_detailed": "boolean|null，仅质量/功能异常场景需要判断",
        "normalized_issue": "提炼出的具体异常；无法提炼则为空字符串",
        "missing_detail": "如果信息不够，还缺什么信息",
        "reason": "一句话说明判断依据",
    }
    example = {
        "intent": "apply_after_sales",
        "scene": "quality_issue",
        "confidence": 0.88,
        "quality_description_detailed": False,
        "normalized_issue": "商品有问题",
        "missing_detail": "缺少具体异常表现",
        "reason": "用户表达了售后诉求，但还没有说明具体故障表现。",
    }
    return (
        "你是售后系统里的对话理解器，负责把用户当前消息结合最近上下文转换成结构化结论。\n"
        "你必须识别用户当前是在申请售后、查询进度、补充凭证、要求人工，还是普通咨询。\n"
        "intent 和 scene 都必须只输出 1 个最终值，不能输出候选集合，不能输出类似 "
        "'apply_after_sales|refund_progress|...' 这样的并列字符串。\n"
        "如果信息不足，也必须返回最接近的一项，并把缺失信息写入 missing_detail。\n"
        "如果上一轮客服要求用户补充异常表现，而用户当前只回复“没有声音”“连不上”“充不了电”等短句，"
        "也要理解为正在补充质量/功能异常，而不是普通咨询。\n"
        "quality_description_detailed 为 true 的条件：用户描述了具体异常现象、受影响部位或故障行为，"
        "例如没有声音、无法开机、充电异常、连接失败、按键失灵等。\n"
        "quality_description_detailed 为 false 的条件：只有“商品有问题”“质量问题”“申请售后”“尽快处理”"
        "这类概括性表达，没有明确故障表现。\n"
        "不要因为有图片或凭证，就自动判断异常描述已经足够具体；只根据文字内容判断。\n"
        "只输出 JSON，不要输出 Markdown，不要输出解释。\n"
        f"intent_allowed: {json.dumps(allowed_intents, ensure_ascii=False)}\n"
        f"scene_allowed: {json.dumps(allowed_scenes, ensure_ascii=False)}\n"
        f"字段说明: {json.dumps(schema, ensure_ascii=False)}\n"
        f"正确输出示例: {json.dumps(example, ensure_ascii=False)}"
    )
