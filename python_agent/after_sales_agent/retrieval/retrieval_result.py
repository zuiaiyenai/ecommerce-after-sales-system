"""Retrieval result formatting and safety helpers.

Extracted from PgVectorKnowledgeRetriever._finalize_result and related methods.
Used by the refactored retrieval pipeline.
"""
from __future__ import annotations

import math
from typing import Any

from after_sales_agent.retrieval.knowledge_filters import FilterPlan

RERANK_THRESHOLDS = {
    # Lowered from 0.55 to 0.35 to avoid filtering out relevant chunks
    # that Reranker ranks lower but are still correct.
    # Reranker's job is ranking (put correct ones first) + rejection (FPR=0),
    # not recall trimming (deleting correct chunks RRF already found).
    "after_sales_policy": 0.35,
    "refund_policy": 0.35,
    "exchange_rule": 0.35,
    "evidence_requirement": 0.45,
    "faq": 0.40,
}


def hit_source_type(hit: dict[str, Any]) -> str:
    """Extract source type from a hit dict."""
    metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
    return str(hit.get("source_type") or metadata.get("source_type") or "").strip()


def threshold_for_source(source_type: str | None) -> float:
    """Return the relevance score threshold for a source type."""
    return RERANK_THRESHOLDS.get(str(source_type or "").strip(), 0.60)


def rerank_score(hit: dict[str, Any]) -> float:
    """Extract rerank score from a hit dict."""
    raw = hit.get("rerank_score")
    if raw is None:
        raw = hit.get("relevance_score")
    try:
        score = float(raw)
    except (TypeError, ValueError):
        return -1.0
    return score if math.isfinite(score) else -1.0


def safe_trace_count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def safe_trace_name(value: Any, default: str | None) -> str | None:
    candidate = str(value).strip() if value is not None else ""
    if candidate and len(candidate) <= 64 and all(char.isalnum() or char == "_" for char in candidate):
        return candidate
    return default


def annotate_hits_with_filter_contract(
    hits: list[dict[str, Any]],
    plan: FilterPlan,
) -> list[dict[str, Any]]:
    for hit in hits:
        hit["trusted_policy_eligible"] = False
        hit["relaxation_level"] = plan.level
    return hits


def finalize_result(
    result: dict[str, Any],
    *,
    plan: FilterPlan,
    failure_reason: str | None,
    reranker_succeeded: bool = False,
    no_answer: bool = True,
    trusted_policy_eligible: bool = False,
    threshold: float | None = None,
) -> dict[str, Any]:
    """Format a retrieval result dict with consistent trace fields.

    Extracted from PgVectorKnowledgeRetriever._finalize_result.
    """
    finalized = dict(result)
    hits = finalized.get("hits")
    if not isinstance(hits, list):
        hits = []
    finalized["hits"] = hits
    resolved_threshold = float(
        threshold if threshold is not None else threshold_for_source(plan.source_type)
    )
    finalized["filter_level"] = plan.level
    finalized["relaxation_level"] = plan.level
    finalized["reranker_succeeded"] = bool(reranker_succeeded)
    finalized["threshold"] = resolved_threshold
    finalized["no_answer"] = bool(no_answer)
    finalized["trusted_policy_eligible"] = bool(trusted_policy_eligible)
    finalized["failure_reason"] = failure_reason

    raw_trace = finalized.get("trace")
    if not isinstance(raw_trace, dict):
        raw_trace = {}
    stage_latency = raw_trace.get("stage_latency_ms")
    if not isinstance(stage_latency, dict):
        stage_latency = {}
    safe_stage_latency = {
        str(stage): float(duration)
        for stage, duration in stage_latency.items()
        if stage in {"embedding", "vector", "keyword", "rrf", "reranker", "multi_query", "total"}
        and isinstance(duration, (int, float))
        and math.isfinite(float(duration))
        and float(duration) >= 0
    }
    if (
        "vector_latency_ms" in raw_trace
        and "vector" not in safe_stage_latency
        and isinstance(raw_trace["vector_latency_ms"], (int, float))
    ):
        safe_stage_latency["vector"] = max(0.0, float(raw_trace["vector_latency_ms"]))
    trace = {
        "stage_latency_ms": safe_stage_latency,
        "filter_level": plan.level,
        "reranker_succeeded": bool(reranker_succeeded),
        "threshold": resolved_threshold,
        "failure_reason": failure_reason,
        "dense_candidate_count": safe_trace_count(raw_trace.get("dense_candidate_count")),
        "keyword_candidate_count": safe_trace_count(raw_trace.get("keyword_candidate_count")),
        "rrf_candidate_count": safe_trace_count(raw_trace.get("rrf_candidate_count")),
        "rerank_candidate_count": safe_trace_count(raw_trace.get("rerank_candidate_count")),
        "candidate_query_count": safe_trace_count(raw_trace.get("candidate_query_count")),
        "candidate_success_count": safe_trace_count(raw_trace.get("candidate_success_count")),
        "candidate_failure_count": safe_trace_count(raw_trace.get("candidate_failure_count")),
        "candidate_hit_count": safe_trace_count(raw_trace.get("candidate_hit_count")),
        "unique_candidate_count": safe_trace_count(raw_trace.get("unique_candidate_count")),
        "rerank_query_count": safe_trace_count(raw_trace.get("rerank_query_count")),
        "rerank_query_success_count": safe_trace_count(
            raw_trace.get("rerank_query_success_count")
        ),
        "retrieval_mode": safe_trace_name(
            raw_trace.get("retrieval_mode"), str(finalized.get("mode") or "unknown")
        ),
        "rerank_query_source": safe_trace_name(
            raw_trace.get("rerank_query_source"), None
        ),
        "fallback_reason": safe_trace_name(raw_trace.get("fallback_reason"), failure_reason),
        "trusted_policy_eligible": bool(trusted_policy_eligible),
    }
    raw_candidate_traces = raw_trace.get("candidate_traces")
    if isinstance(raw_candidate_traces, list):
        safe_candidate_traces: list[dict[str, Any]] = []
        for item in raw_candidate_traces[:3]:
            if not isinstance(item, dict):
                continue
            candidate_trace = {
                "query_index": safe_trace_count(item.get("query_index")),
                "latency_ms": max(0.0, float(item.get("latency_ms") or 0.0)),
                "hit_count": safe_trace_count(item.get("hit_count")),
            }
            mode = safe_trace_name(item.get("mode"), None)
            error_type = safe_trace_name(item.get("error_type"), None)
            if mode is not None:
                candidate_trace["mode"] = mode
            if error_type is not None:
                candidate_trace["error_type"] = error_type
            safe_candidate_traces.append(candidate_trace)
        trace["candidate_traces"] = safe_candidate_traces
    fallback_level = raw_trace.get("fallback_level")
    if fallback_level in {"strict", "category_relaxed", "scene_relaxed", "category_and_scene_relaxed", "intent_relaxed"}:
        trace["fallback_level"] = fallback_level
    reranker_failure = safe_trace_name(raw_trace.get("reranker_failure_reason"), None)
    if reranker_failure is not None:
        trace["reranker_failure_reason"] = reranker_failure
    finalized["trace"] = trace

    for hit in hits:
        if not isinstance(hit, dict):
            continue
        hit["relaxation_level"] = plan.level
        if not trusted_policy_eligible:
            hit["trusted_policy_eligible"] = False
        else:
            hit.setdefault("trusted_policy_eligible", False)
    return finalized


def normalized_merchant_code(merchant_code: str | None) -> str:
    """Normalize merchant code to a non-empty string."""
    normalized = str(merchant_code or "").strip()
    return normalized or "GLOBAL"


def safe_query_id(query_id: str | None, query: str) -> str:
    """Safely encode a query_id to a valid identifier."""
    import hashlib
    candidate = str(query_id or "").strip()
    safe = "".join(char for char in candidate if char.isalnum() or char in {"-", "_"})[:64]
    if safe:
        return safe
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:12]


def serialize_time(value: Any) -> str | None:
    """Format a time value as ISO string, or return None."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


def apply_filter_contract(
    result: dict[str, Any],
    plan: FilterPlan,
) -> dict[str, Any]:
    """Apply filter contract to a result dict (modifies in-place)."""
    result["trusted_policy_eligible"] = False
    result["relaxation_level"] = plan.level
    trace = result.setdefault("trace", {})
    trace["trusted_policy_eligible"] = False
    trace["relaxation_level"] = plan.level
    hits = result.get("hits")
    if isinstance(hits, list):
        annotate_hits_with_filter_contract(hits, plan)
    return result


def finalize_ablation_result(
    *,
    mode: str,
    hits: list[dict[str, Any]],
    plan: FilterPlan,
    dense_count: int,
    keyword_count: int,
    rrf_count: int,
    trace: dict[str, Any],
) -> dict[str, Any]:
    """Format an ablation test result (no reranker path)."""
    no_answer = not hits
    trace.update(
        {
            "dense_candidate_count": dense_count,
            "keyword_candidate_count": keyword_count,
            "rrf_candidate_count": rrf_count,
            "rerank_candidate_count": 0,
            "retrieval_mode": mode,
            "fallback_reason": "NO_MATCH" if no_answer else None,
        }
    )
    return finalize_result(
        {"mode": mode, "hits": hits, "trace": trace},
        plan=plan,
        failure_reason="NO_MATCH" if no_answer else None,
        no_answer=no_answer,
    )
