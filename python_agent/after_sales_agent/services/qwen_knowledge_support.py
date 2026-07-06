from __future__ import annotations

from typing import Any

from .conversation import ConversationContext
from ..models import AfterSalesScene, AgentResult, Intent


def knowledge_query(context: ConversationContext) -> str:
    parts = [str(context.message or "").strip()]
    if context.description:
        parts.append(str(context.description).strip())
    recent_user_messages = [
        message.content.strip()
        for message in context.recent_history[-3:]
        if message.role == "user" and message.content
    ]
    parts.extend(recent_user_messages)
    return " ".join(part for part in parts if part)


def knowledge_sources(fallback_result: AgentResult) -> list[str]:
    if fallback_result.intent == Intent.REFUND_PROGRESS:
        return ["faq", "policy"]
    if fallback_result.scene in {
        AfterSalesScene.QUALITY_ISSUE,
        AfterSalesScene.PRODUCT_DAMAGE,
        AfterSalesScene.PACKAGE_DAMAGE,
        AfterSalesScene.WRONG_OR_MISSING_ITEMS,
        AfterSalesScene.LOGISTICS_ISSUE,
    }:
        return ["scene_evidence", "policy", "product", "faq"]
    return ["faq", "policy", "product", "scene_evidence", "review_interpretation"]


def prompt_ready_knowledge(retrieved_knowledge: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(retrieved_knowledge, dict):
        return {"mode": "unavailable", "hits": []}
    prompt_hits: list[dict[str, Any]] = []
    for item in list(retrieved_knowledge.get("hits") or [])[:4]:
        if not isinstance(item, dict):
            continue
        prompt_hits.append(
            {
                "source_type": item.get("source_type"),
                "title": item.get("title"),
                "summary": item.get("summary"),
                "snippet": item.get("snippet"),
                "score": item.get("score"),
                "tags": item.get("tags"),
            }
        )
    return {
        "mode": retrieved_knowledge.get("mode"),
        "query": retrieved_knowledge.get("query"),
        "retrieval_mode": retrieved_knowledge.get("retrieval_mode"),
        "total_hits": retrieved_knowledge.get("total_hits"),
        "hits": prompt_hits,
    }


def pick_knowledge_answer_hit(
    context: ConversationContext,
    fallback_result: AgentResult,
    retrieved_knowledge: dict[str, Any] | None,
    *,
    has_logistics_keywords,
) -> dict[str, Any] | None:
    if not isinstance(retrieved_knowledge, dict):
        return None
    hits = [item for item in list(retrieved_knowledge.get("hits") or []) if isinstance(item, dict)]
    if not hits:
        return None
    top_hit = hits[0]
    if not is_knowledge_short_circuit_candidate(
        context,
        fallback_result,
        top_hit,
        hits[1:2],
        has_logistics_keywords=has_logistics_keywords,
    ):
        return None
    return top_hit


def is_knowledge_short_circuit_candidate(
    context: ConversationContext,
    fallback_result: AgentResult,
    top_hit: dict[str, Any],
    secondary_hits: list[dict[str, Any]],
    *,
    has_logistics_keywords,
) -> bool:
    source_type = str(top_hit.get("source_type") or "").strip().lower()
    if source_type not in {"faq", "policy", "product"}:
        return False
    if context.attachments or context.image_review is not None:
        return False
    if fallback_result.need_human:
        return False
    if fallback_result.intent in {
        Intent.APPLY_AFTER_SALES,
        Intent.SUPPLEMENT_EVIDENCE,
        Intent.RETURN_LOGISTICS,
        Intent.EXCHANGE_REPAIR,
        Intent.REFUND_ONLY,
        Intent.MERCHANT_REJECTED,
        Intent.HUMAN_SERVICE,
        Intent.COMPLAINT,
    }:
        return False
    if fallback_result.intent == Intent.REFUND_PROGRESS and context.selected_order is not None:
        return False
    text = knowledge_query(context).lower()
    if has_logistics_keywords(text):
        return False
    if not looks_like_knowledge_question(text, source_type):
        return False
    try:
        top_score = float(top_hit.get("score") or 0.0)
    except (TypeError, ValueError):
        top_score = 0.0
    min_score = {
        "faq": 80.0,
        "policy": 95.0,
        "product": 95.0,
    }.get(source_type, 999.0)
    if top_score < min_score:
        return False
    second_score = 0.0
    if secondary_hits:
        try:
            second_score = float(secondary_hits[0].get("score") or 0.0)
        except (TypeError, ValueError):
            second_score = 0.0
    if source_type != "faq" and top_score - second_score < 12.0:
        return False
    return True


def looks_like_knowledge_question(text: str, source_type: str) -> bool:
    question_markers = (
        "吗",
        "么",
        "嘛",
        "?",
        "？",
        "怎么",
        "多久",
        "多长时间",
        "是否",
        "能不能",
        "可以不可以",
        "可不可以",
        "谁承担",
        "怎么算",
        "是什么",
        "保修",
        "范围",
        "规则",
        "政策",
        "流程",
        "审核多久",
        "多久到账",
        "运费",
    )
    if any(marker in text for marker in question_markers):
        return True
    if source_type == "faq":
        return True
    return False


def build_knowledge_answer_reply(
    hit: dict[str, Any],
    fallback_reply: str,
    *,
    normalize_reply_text,
) -> str:
    answer = str(hit.get("summary") or hit.get("snippet") or "").strip()
    if not answer:
        return ""
    return normalize_reply_text(answer, fallback_reply or answer)

