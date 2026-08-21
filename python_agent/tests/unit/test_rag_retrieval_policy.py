from __future__ import annotations

from after_sales_agent.application.rag_retrieval_policy import RagRetrievalPolicy


def test_infrastructure_failure_never_requests_query_rewrite() -> None:
    failed = RagRetrievalPolicy().is_infrastructure_failure(
        {
            "mode": "pgvector_error",
            "hits": [],
            "no_answer": True,
            "failure_reason": "PGVECTOR_ERROR",
        },
    )

    assert failed


def test_degraded_reranker_result_does_not_request_query_rewrite() -> None:
    failed = RagRetrievalPolicy().is_infrastructure_failure(
        {
            "mode": "hybrid_rrf_degraded",
            "hits": [{"source_type": "after_sales_policy"}],
            "no_answer": False,
            "failure_reason": "RERANK_TIMEOUT",
        },
    )

    assert failed


def test_normal_result_is_not_infrastructure_failure() -> None:
    assert not RagRetrievalPolicy().is_infrastructure_failure(
        {
            "mode": "hybrid_reranked",
            "hits": [],
            "no_answer": True,
            "failure_reason": "NO_MATCH",
        }
    )
