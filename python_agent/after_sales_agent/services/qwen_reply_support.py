from __future__ import annotations

from typing import Any

from ..models import AfterSalesScene, AgentResult, Intent


def normalize_reply_text(reply: str, fallback_reply: str) -> str:
    cleaned = " ".join(str(reply or "").split())
    banned_phrases = (
        "请随时联系我们",
        "竭诚为您服务",
        "感谢您的理解与配合",
        "感谢您的理解和配合",
        "感谢您的配合与理解",
        "感谢您的理解",
        "感谢理解",
        "很抱歉给您带来不便",
        "谢谢您的配合",
        "感谢您的配合",
        "感谢您的支持",
        "谢谢您的支持",
    )
    for phrase in banned_phrases:
        cleaned = cleaned.replace(phrase, "")

    for old, new in (
        ("。！", "。"),
        ("。!", "。"),
        ("！。", "！"),
        ("!.", "!"),
        ("，，", "，"),
        ("。。", "。"),
        ("！！", "！"),
    ):
        while old in cleaned:
            cleaned = cleaned.replace(old, new)

    tail_fragments = ("与配合", "和配合", "感谢您", "谢谢您", "感谢", "谢谢")
    stripped = cleaned.rstrip(" ，。！？!,.、；;:：")
    for fragment in tail_fragments:
        if stripped.endswith(fragment):
            stripped = stripped[: -len(fragment)].rstrip(" ，。！？!,.、；;:：")
    cleaned = stripped

    if not cleaned:
        return fallback_reply
    if len(cleaned) > 100:
        return fallback_reply
    return cleaned + "。"


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


def build_user_reply(
    raw: dict[str, Any],
    fallback_result: AgentResult,
    *,
    use_rule_reply: bool,
) -> str:
    if use_rule_reply:
        return fallback_result.user_reply
    candidate = normalize_reply_text(
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
