from __future__ import annotations

from after_sales_agent.providers.reranker_client import RerankerConfig
from after_sales_agent.retrieval import pgvector_retriever


def test_layered_rag_rollout_defaults_are_safe(monkeypatch) -> None:
    for name in (
        "RAG_LAYERED_RETRIEVAL_ENABLED",
        "RERANK_TIMEOUT_SECONDS",
        "RERANK_MAX_RETRIES",
        "RERANK_MAX_CANDIDATES",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(pgvector_retriever, "_read_local_env", lambda: {})

    retrieval = pgvector_retriever.PgVectorConfig.from_env()
    reranker = RerankerConfig.from_env()

    assert retrieval.layered_retrieval_enabled is False
    assert reranker.timeout_seconds == 3.0
    assert reranker.max_retries == 1
    assert reranker.max_candidates == 20


def test_compatibility_switch_skips_embedding_and_reranking() -> None:
    class CompatibilityRetriever(pgvector_retriever.PgVectorKnowledgeRetriever):
        def _get_query_embedding(self, _query):
            raise AssertionError("compatibility mode must not request embeddings")

        def _lexical_fallback(self, **kwargs):
            return {
                "mode": "lexical_fallback",
                "query": kwargs["query"],
                "hits": [{"chunk_id": "legacy-1", "source_type": "faq"}],
                "trace": {},
            }

    retriever = CompatibilityRetriever(
        pgvector_retriever.PgVectorConfig(
            dsn="postgresql://unused",
            layered_retrieval_enabled=False,
            embedding_api_key="unused",
        )
    )

    result = retriever.retrieve(query="refund", source_type="faq")

    assert result["mode"] == "lexical_compatibility"
    assert result["reranker_succeeded"] is False
    assert result["trusted_policy_eligible"] is False
    assert result["no_answer"] is False
    assert result["trace"]["retrieval_mode"] == "compatibility"
    assert result["trace"]["fallback_reason"] == "RAG_LAYERED_RETRIEVAL_DISABLED"
