"""Reranker client wrapper.

Wraps the existing RerankerClient for the new retrieval pipeline.
"""
from __future__ import annotations

from typing import Any

from after_sales_agent.providers.reranker_client import RerankerClient, RERANKER_CLIENTS, RerankResult
from after_sales_agent.retrieval.ranking.rank_fusion import fuse_rankings_v2


def rerank_hits(
    hits: list[dict[str, Any]],
    query: str,
    *,
    reranker_client: RerankerClient | None = None,
    top_k: int = 20,
) -> list[dict[str, Any]]:
    """Rerank a list of hits using the configured reranker.

    Returns the original list if no reranker is configured.
    """
    if not reranker_client or not hits:
        return hits
    try:
        reranked = reranker_client.rerank(query=query, hits=hits, top_k=top_k)
    except Exception:
        return hits
    if not reranked or not isinstance(reranked, list):
        return hits
    for rank, hit in enumerate(reranked, start=1):
        hit["rank"] = rank
        hit["rerank_rank"] = rank
        hit["rerank_score"] = float(hit.get("score") or 0.0)
        hit["channel"] = "reranker"
        hit["retrieval_channels"] = list(dict.fromkeys(["reranker"] + hit.get("retrieval_channels", [])))
    return list(dict.fromkeys(hit["id"] for hit in reranked))[:top_k] or reranked


def fuse_and_rerank(
    all_queries: list[str],
    all_hits: list[list[dict[str, Any]]],
    *,
    top_k: int = 20,
    reranker_client: RerankerClient | None = None,
) -> list[dict[str, Any]]:
    """Fuse multi-query results and rerank."""
    if not reranker_client or not all_hits or not all(all_hits):
        return all_hits[0] if all_hits else []
    fused = fuse_rankings_v2(all_hits, limit=top_k)
    return rerank_hits(fused, query=all_queries[0] if all_queries else "", reranker_client=reranker_client, top_k=top_k)


def _finalize_reranked_result(
    *,
    query: str,
    dense_hits: list[dict[str, Any]],
    keyword_hits: list[dict[str, Any]],
    plan: Any,
    limit: int,
    trace: dict[str, Any],
    reranker_client: Any,
) -> dict[str, Any]:
    """Execute the reranking pipeline and return a finalized result dict.

    Extracted from PgVectorKnowledgeRetriever._finalize_reranked_result.
    """
    from after_sales_agent.retrieval.rrf import rrf_fuse
    from after_sales_agent.retrieval.knowledge_filters import POLICY_SOURCE_TYPES
    from after_sales_agent.providers.reranker_client import RerankResult

    fused = rrf_fuse(dense_hits, keyword_hits, limit=20)
    from after_sales_agent.retrieval.retrieval_result import annotate_hits_with_filter_contract
    annotate_hits_with_filter_contract(fused, plan)
    try:
        reranked = reranker_client.rerank(query, fused, top_n=limit)
    except Exception:
        reranked = RerankResult(
            items=fused[:limit],
            mode="hybrid_rrf_degraded",
            degraded=True,
            failure_reason="UNEXPECTED_ERROR",
            latency_ms=0.0,
        )

    from after_sales_agent.retrieval.retrieval_result import hit_source_type, threshold_for_source, rerank_score
    default_source = plan.source_type or hit_source_type(fused[0] if fused else {})
    threshold = threshold_for_source(default_source)
    output_hits: list[dict[str, Any]] = []
    for raw_hit in reranked.items:
        hit = dict(raw_hit)
        source = hit_source_type(hit)
        hit_threshold = threshold_for_source(source)
        hit["threshold"] = hit_threshold
        hit["relaxation_level"] = plan.level
        hit["trusted_policy_eligible"] = False
        if reranked.degraded:
            output_hits.append(hit)
            continue
        score = rerank_score(hit)
        if score < hit_threshold:
            continue
        if plan.level == "strict" and source in POLICY_SOURCE_TYPES:
            hit["trusted_policy_eligible"] = True
        output_hits.append(hit)

    reranker_succeeded = not reranked.degraded
    trusted_policy_eligible = bool(
        reranker_succeeded
        and plan.level == "strict"
        and any(hit.get("trusted_policy_eligible") is True for hit in output_hits)
    )
    stage_latency = trace.get("stage_latency_ms")
    if not isinstance(stage_latency, dict):
        stage_latency = {}
    if "vector_latency_ms" in trace:
        stage_latency["vector"] = trace["vector_latency_ms"]
    stage_latency["reranker"] = reranked.latency_ms
    trace["stage_latency_ms"] = stage_latency
    trace["filter_level"] = plan.level
    trace["reranker_succeeded"] = reranker_succeeded
    trace["reranker_failure_reason"] = reranked.failure_reason
    trace["threshold"] = threshold
    trace["trusted_policy_eligible"] = trusted_policy_eligible
    trace["dense_candidate_count"] = len(dense_hits)
    trace["keyword_candidate_count"] = len(keyword_hits)
    trace["rrf_candidate_count"] = len(fused)
    trace["rerank_candidate_count"] = len(reranked.items)
    trace["retrieval_mode"] = reranked.mode
    trace["fallback_reason"] = reranked.failure_reason
    no_answer = bool(reranked.degraded or not output_hits)
    failure_reason = reranked.failure_reason if reranked.degraded else ("NO_MATCH" if no_answer else None)
    from after_sales_agent.retrieval.retrieval_result import finalize_result
    return finalize_result(
        {
            "mode": reranked.mode,
            "query": query,
            "hits": output_hits,
            "trace": trace,
        },
        plan=plan,
        failure_reason=failure_reason,
        reranker_succeeded=reranker_succeeded,
        no_answer=no_answer,
        trusted_policy_eligible=trusted_policy_eligible,
        threshold=threshold,
    )
