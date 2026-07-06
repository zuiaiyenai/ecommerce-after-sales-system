from __future__ import annotations

from dataclasses import replace
from typing import Any

from .conversation import ConversationContext
from ..models import AfterSalesRequest, AfterSalesScene, Intent


def fallback_normalized_issue(request: AfterSalesRequest) -> str:
    for value in (request.message, request.description, request.reason):
        text = str(value or "").strip()
        if text and looks_like_specific_issue(text):
            return text
    return ""


def looks_like_specific_issue(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    generic_words = ("质量问题", "商品有问题", "申请售后", "售后申请", "补充说明")
    if normalized in generic_words:
        return False
    specific_markers = (
        "破",
        "裂",
        "碎",
        "坏",
        "损",
        "凹",
        "断",
        "没声音",
        "没有声音",
        "不响",
        "无法开机",
        "不能开机",
        "充电",
        "连接失败",
        "按键失灵",
    )
    return any(marker in normalized for marker in specific_markers)


def should_force_quality_issue(
    scene: AfterSalesScene,
    request: AfterSalesRequest,
    normalized_issue: str,
) -> bool:
    if scene != AfterSalesScene.PRODUCT_DAMAGE:
        return False
    combined = " ".join(
        part
        for part in (request.message, request.description, request.reason, normalized_issue)
        if part
    ).lower()
    if not combined:
        return False
    quality_markers = (
        "无法开机",
        "开不了机",
        "不能开机",
        "没声音",
        "没有声音",
        "不响",
        "充不进电",
        "充电无反应",
        "按键失灵",
        "触控失灵",
        "连接失败",
        "故障",
        "异常",
    )
    damage_markers = (
        "破损",
        "裂开",
        "裂纹",
        "碎了",
        "磕碰",
        "变形",
        "外壳裂",
        "屏幕碎",
        "花屏",
    )
    return any(marker in combined for marker in quality_markers) and not any(
        marker in combined for marker in damage_markers
    )


def apply_scene_guardrail(
    scene: AfterSalesScene,
    request: AfterSalesRequest,
    normalized_issue: str,
) -> AfterSalesScene:
    combined = " ".join(
        part
        for part in (request.message, request.description, request.reason, normalized_issue)
        if part
    ).lower()
    if not combined:
        return scene
    if has_logistics_keywords(combined):
        return AfterSalesScene.LOGISTICS_ISSUE
    if should_force_quality_issue(scene, request, normalized_issue):
        return AfterSalesScene.QUALITY_ISSUE
    missing_item_markers = (
        "少发",
        "漏发",
        "错发",
        "发错",
        "少了一件",
        "缺件",
        "补发",
    )
    if any(marker in combined for marker in missing_item_markers):
        return AfterSalesScene.WRONG_OR_MISSING_ITEMS
    return scene


def repair_understanding_choice(
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
        if has_logistics_keywords(combined):
            intent = Intent.RETURN_LOGISTICS
        elif raw_intent == "progress_query" or has_refund_progress_keywords(combined):
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
        if has_logistics_keywords(combined):
            scene = AfterSalesScene.LOGISTICS_ISSUE
        elif raw_scene == "progress_query" or has_refund_progress_keywords(combined):
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


def repair_request_without_understanding(
    request: AfterSalesRequest,
    context: ConversationContext,
) -> AfterSalesRequest:
    text = combined_user_text(context, request)
    if has_logistics_keywords(text):
        return replace(
            request,
            llm_intent=Intent.RETURN_LOGISTICS,
            llm_scene=AfterSalesScene.LOGISTICS_ISSUE,
            llm_confidence=max(request.llm_confidence, 0.8),
        )
    if has_refund_progress_keywords(text):
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


def combined_user_text(context: ConversationContext, request: AfterSalesRequest) -> str:
    parts = [request.message or "", request.description or "", request.reason or ""]
    parts.extend(
        message.content
        for message in context.recent_history[-4:]
        if message.role == "user" and message.content
    )
    return "".join(parts).lower()


def is_refund_progress_query(
    context: ConversationContext,
    request: AfterSalesRequest,
) -> bool:
    current_text = "".join(
        part for part in (request.message, request.description, request.reason) if part
    ).lower()
    if has_logistics_keywords(current_text):
        return False
    if has_refund_progress_keywords(current_text):
        return True
    history_text = combined_user_text(context, request)
    if has_logistics_keywords(history_text):
        return False
    return has_refund_progress_keywords(history_text)


def has_refund_progress_keywords(text: str) -> bool:
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


def has_logistics_keywords(text: str) -> bool:
    return any(
        keyword in text
        for keyword in (
            "物流",
            "快递",
            "单号",
            "寄回",
            "寄出",
            "退货地址",
            "寄回地址",
            "没收到货",
            "未收到货",
            "配送",
            "揽收",
            "派送",
            "签收",
            "物流没更新",
            "快递没更新",
            "一直没更新",
            "一直不动",
        )
    )

