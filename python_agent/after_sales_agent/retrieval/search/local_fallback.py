"""Local policy knowledge fallback.

Extracted from PgVectorKnowledgeRetriever._local_knowledge_fallback and
_build_local_policy_knowledge_index.
"""
from __future__ import annotations

import json
from typing import Any


def local_fallback(
    *,
    query: str,
    product_category: str | None,
    scene: str | None,
    merchant_code: str | None,
    limit: int = 3,
    _policy_knowledge_index: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return local keyword policy hits if available and relevant."""
    if not _policy_knowledge_index:
        return []
    local_hits = []
    for item in _policy_knowledge_index:
        score = _local_text_match_score(item, query)
        if score < 0.35:
            continue
        local_hits.append(
            {
                "id": item["id"],
                "chunk_id": item["id"],
                "source_type": "after_sales_policy",
                "source_code": "local_policy_fallback",
                "title": item.get("title") or "Local Policy",
                "snippet": item["text"][:300],
                "score": round(score, 4),
                "raw_score": score,
                "rank": 1,
                "channel": "local_policy",
                "local_policy_rank": 1,
                "local_policy_score": score,
                "retrieval_channels": ["local_policy"],
                "citation": {
                    "chunk_id": item["id"],
                    "source_type": "after_sales_policy",
                    "source_code": "local_policy_fallback",
                    "title": item.get("title") or "Local Policy",
                    "content": item["text"][:500],
                },
                "metadata": {
                    "source_type": "after_sales_policy",
                    "source_code": "local_policy_fallback",
                    "title": item.get("title") or "Local Policy",
                    "product_categories": item.get("product_categories") or [],
                    "scenes": item.get("scenes") or [],
                    "merchant_code": merchant_code,
                },
                "trusted_policy_eligible": True,
                "relaxation_level": "strict",
            }
            for _ in range(1)
        )[0]
    local_hits = local_hits[: max(1, min(int(limit), 10))]
    return local_hits


def load_local_policy_knowledge(
    source_types: list[str] | None = None,
) -> dict[str, Any] | None:
    """Load policy hints from the bundled local policy knowledge JSON.

    Extracted from PgVectorKnowledgeRetriever._load_local_policy_knowledge.
    """
    import importlib.util
    import os

    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "..", "data", "local_policy_knowledge.json"),
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "after_sales_agent", "data", "local_policy_knowledge.json"),
    ]
    for path in candidates:
        if not os.path.exists(path):
            continue
        spec = importlib.util.spec_from_file_location("local_policy_knowledge", path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except Exception:
                continue
            content = module.knowledge
            if isinstance(content, dict):
                if source_types:
                    filtered = [
                        item
                        for item in content.get("knowledge", [])
                        if item.get("source_type") in source_types
                    ]
                    return {"knowledge": filtered, "source_types": source_types}
                return content
    return None


def _local_text_match_score(item: dict[str, Any], query: str) -> float:
    score = 0.0
    if not query:
        return score
    query_tokens = set(query.lower().split())
    if not query_tokens:
        return score
    text_lower = (item.get("text") or "").lower()
    title_lower = (item.get("title") or "").lower()
    for token in query_tokens:
        if len(token) < 2:
            continue
        if title_lower and token in title_lower:
            score += 2.0
        if token in text_lower:
            score += 1.0
    return min(1.0, round(score, 4))


def _build_local_policy_knowledge_index() -> dict[str, Any]:
    return load_local_policy_knowledge(["after_sales_policy", "refund_policy", "exchange_rule"])


def local_knowledge_hits(
    *,
    query: str,
    merchant_code: str | None,
    product_category: str | None,
    scene: str | None,
    intent: str | None,
    source_type: str | None,
    policy_version: str | None,
    top_k: int | None,
    config: Any,
    _policy_knowledge_index: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build local knowledge hits and return (hits, trace_info).

    Extracted from PgVectorKnowledgeRetriever._local_knowledge_fallback.
    Returns a 2-tuple: (hits, trace_dict) for use by the class method.
    """
    from after_sales_agent.retrieval.alias_mapping import scene_aliases, product_category_aliases

    knowledge = _policy_knowledge_index if _policy_knowledge_index is not None else load_local_policy_knowledge()
    if knowledge is None:
        knowledge = {}

    hits: list[dict[str, Any]] = []
    scene_alias_set = set(scene_aliases(scene))
    limit = max(1, min(int(top_k or getattr(config, "top_k", 3)), 10))

    for item in knowledge.get("scene_evidence_knowledge") or []:
        if not isinstance(item, dict):
            continue
        item_scene = str(item.get("scene") or "").strip()
        if scene_alias_set and item_scene not in scene_alias_set:
            continue
        default_evidence = item.get("default_evidence")
        snippet = str(item.get("description") or "")
        hits.append(
            {
                "id": f"local-scene-{item_scene}",
                "source_type": "scene_evidence",
                "source_code": item_scene,
                "title": str(item.get("label") or item_scene),
                "snippet": snippet,
                "score": 0.99,
                "metadata": {
                    "scene": item_scene,
                    "default_evidence": default_evidence if isinstance(default_evidence, list) else [],
                    "merchant_code": merchant_code,
                    "product_category": product_category,
                    "intent": intent,
                    "policy_version": policy_version,
                },
            }
        )

    query_lower = query.lower()
    for section_name, source_name in (
        ("after_sales_policy_knowledge", "after_sales_policy"),
        ("faq_knowledge", "faq"),
        ("product_knowledge", "product_knowledge"),
        ("review_interpretation_knowledge", "review_interpretation"),
        ("reply_template_knowledge", "reply_template"),
    ):
        for item in knowledge.get(section_name) or []:
            if not isinstance(item, dict):
                continue
            text = " ".join(
                str(item.get(key) or "")
                for key in ("title", "question", "summary", "content", "template", "meaning", "description")
            )
            if not text.strip():
                continue
            score = _local_text_match_score(item, query_lower)
            if score <= 0:
                continue
            item_scene = str(item.get("scene") or "").strip()
            if scene_alias_set and item_scene and item_scene not in scene_alias_set:
                continue
            item_category = str(item.get("product_category") or item.get("product_name") or "").strip()
            category_alias_set = {alias.lower() for alias in product_category_aliases(product_category)}
            if (
                product_category
                and item_category
                and item_category.lower() not in category_alias_set
                and item_category not in {"general", "通用"}
            ):
                continue
            hits.append(
                {
                    "id": f"local-{section_name}-{item.get('code') or item.get('policy_code') or item.get('product_id') or len(hits)}",
                    "source_type": source_name,
                    "source_code": str(
                        item.get("code")
                        or item.get("policy_code")
                        or item.get("question")
                        or item.get("title")
                        or len(hits)
                    ),
                    "title": str(
                        item.get("title")
                        or item.get("question")
                        or item.get("policy_name")
                        or section_name
                    ),
                    "snippet": text[:700],
                    "score": round(score, 4),
                    "metadata": item,
                }
            )

    hits.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
    trace_info = {
        "scene": scene,
        "product_category": product_category,
        "merchant_code": merchant_code,
    }
    return hits[:limit], trace_info


def _lexical_tokens(query: str) -> list[str]:
    """Tokenize query using bigram/trigram for Chinese, word split for ASCII."""
    import re
    text = str(query or "")
    tokens: list[str] = []
    for segment in re.split(r"[^一-鿿]+", text):
        segment = segment.strip()
        if len(segment) >= 2:
            for i in range(len(segment) - 1):
                tokens.append(segment[i:i + 2])
            if len(segment) >= 3:
                for i in range(len(segment) - 2):
                    tokens.append(segment[i:i + 3])
    for raw in text.replace("_", " ").replace("/", " ").split():
        value = raw.strip()
        if len(value) >= 2 and not re.fullmatch(r"[一-鿿]+", value):
            tokens.append(value)
    seen: set[str] = set()
    result: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result[:16]


def _lexical_token_weight(token: str) -> float:
    length = len(token)
    if length >= 6:
        return 2.0
    if length >= 4:
        return 1.5
    return 1.0
