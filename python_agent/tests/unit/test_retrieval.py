from __future__ import annotations

import importlib.util
from datetime import datetime
import os
import pathlib
import sys
import types
import unittest
from unittest.mock import patch

from after_sales_agent.providers.reranker_client import RerankResult
from after_sales_agent.providers.reranker_client import RerankerConfig
from after_sales_agent.retrieval import pgvector_retriever
from after_sales_agent.retrieval.rrf import rrf_fuse, rrf_fuse_rankings
from after_sales_agent.retrieval.knowledge_filters import (
    FilterContext,
    build_hard_filter_sql,
    build_filter_plans,
)


RETRIEVER_PATH = pathlib.Path(__file__).resolve().parents[2] / "after_sales_agent" / "retrieval" / "pgvector_retriever.py"


def load_retriever_module():
    spec = importlib.util.spec_from_file_location("pgvector_retrieval_for_test", RETRIEVER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["pgvector_retrieval_for_test"] = module
    spec.loader.exec_module(module)
    return module


retriever_module = load_retriever_module()
PgVectorConfig = retriever_module.PgVectorConfig
PgVectorKnowledgeRetriever = retriever_module.PgVectorKnowledgeRetriever


def layered_config(**kwargs):
    return PgVectorConfig(layered_retrieval_enabled=True, **kwargs)


class PgVectorRetrievalTest(unittest.TestCase):
    def assert_degraded_contract(self, result, *, mode: str, filter_level: str, failure_reason: str) -> None:
        self.assertEqual(mode, result["mode"])
        self.assertEqual(filter_level, result["filter_level"])
        self.assertEqual(filter_level, result["relaxation_level"])
        self.assertFalse(result["reranker_succeeded"])
        self.assertTrue(result["no_answer"])
        self.assertFalse(result["trusted_policy_eligible"])
        self.assertEqual(failure_reason, result["failure_reason"])
        self.assertIsInstance(result["threshold"], float)
        self.assertIsInstance(result["trace"]["stage_latency_ms"], dict)
        self.assertEqual(filter_level, result["trace"]["filter_level"])
        self.assertEqual(failure_reason, result["trace"]["failure_reason"])
        self.assertFalse(result["trace"]["trusted_policy_eligible"])
        for hit in result["hits"]:
            self.assertFalse(hit["trusted_policy_eligible"])

    def test_empty_query_uses_stable_degraded_contract(self) -> None:
        result = PgVectorKnowledgeRetriever(layered_config(dsn="", embedding_api_key="")).retrieve(query="  ")

        self.assert_degraded_contract(
            result,
            mode="skipped",
            filter_level="strict",
            failure_reason="EMPTY_QUERY",
        )

    def test_missing_dsn_policy_query_uses_stable_degraded_contract(self) -> None:
        result = PgVectorKnowledgeRetriever(layered_config(dsn="", embedding_api_key="")).retrieve(
            query="refund policy",
            source_type="after_sales_policy",
        )

        self.assert_degraded_contract(
            result,
            mode="pgvector_not_configured",
            filter_level="strict",
            failure_reason="PGVECTOR_NOT_CONFIGURED",
        )

    def test_local_fallback_preserves_auxiliary_hits_but_is_untrusted(self) -> None:
        class LocalRetriever(PgVectorKnowledgeRetriever):
            def _local_knowledge_fallback(self, **kwargs):
                return {
                    "mode": "local_json_fallback",
                    "query": kwargs.get("query") or "",
                    "hits": [{"chunk_id": "LOCAL-1", "source_type": "faq", "snippet": "local help"}],
                    "trace": {},
                }

        result = LocalRetriever(layered_config(dsn="", embedding_api_key="")).retrieve(
            query="help",
            source_type="faq",
        )

        self.assertEqual(1, len(result["hits"]))
        self.assert_degraded_contract(
            result,
            mode="local_json_fallback",
            filter_level="strict",
            failure_reason="PGVECTOR_NOT_CONFIGURED",
        )

    def test_missing_psycopg_dependency_uses_stable_degraded_contract(self) -> None:
        retriever = PgVectorKnowledgeRetriever(layered_config(dsn="postgresql://unused", embedding_api_key="fake"))

        with patch.dict(sys.modules, {"psycopg": None}):
            result = retriever.retrieve(query="refund", source_type="after_sales_policy")

        self.assert_degraded_contract(
            result,
            mode="pgvector_dependency_missing",
            filter_level="strict",
            failure_reason="PGVECTOR_DEPENDENCY_MISSING",
        )

    def test_embedding_error_lexical_fallback_preserves_hits_under_stable_contract(self) -> None:
        class EmbeddingFailureRetriever(PgVectorKnowledgeRetriever):
            def _get_query_embedding(self, _text):
                raise RuntimeError("embedding unavailable")

            def _lexical_fallback(self, **kwargs):
                return {
                    "mode": "lexical_fallback",
                    "query": kwargs.get("query") or "",
                    "hits": [{"chunk_id": "LEX-1", "source_type": "after_sales_policy"}],
                    "trace": {},
                }

        result = _retrieve_with_fake_psycopg(
            EmbeddingFailureRetriever(layered_config(dsn="postgresql://unused", embedding_api_key="fake")),
            source_type="after_sales_policy",
        )

        self.assertEqual(1, len(result["hits"]))
        self.assert_degraded_contract(
            result,
            mode="lexical_fallback_after_embedding_error",
            filter_level="strict",
            failure_reason="EMBEDDING_ERROR",
        )

    def test_embedding_error_without_fallback_uses_stable_contract(self) -> None:
        class EmbeddingFailureRetriever(PgVectorKnowledgeRetriever):
            def _get_query_embedding(self, _text):
                raise RuntimeError("embedding unavailable")

            def _lexical_fallback(self, **kwargs):
                return {"mode": "lexical_fallback", "query": kwargs.get("query") or "", "hits": [], "trace": {}}

        result = _retrieve_with_fake_psycopg(
            EmbeddingFailureRetriever(layered_config(dsn="postgresql://unused", embedding_api_key="fake")),
            source_type="after_sales_policy",
        )

        self.assert_degraded_contract(
            result,
            mode="embedding_error",
            filter_level="strict",
            failure_reason="EMBEDDING_ERROR",
        )

    def test_pgvector_error_uses_stable_degraded_contract(self) -> None:
        class PgFailureRetriever(PgVectorKnowledgeRetriever):
            def _embed(self, _text):
                return [0.0]

            def _vector_search(self, **_kwargs):
                raise RuntimeError("database unavailable")

        result = _retrieve_with_fake_psycopg(
            PgFailureRetriever(layered_config(dsn="postgresql://unused", embedding_api_key="fake")),
            source_type="after_sales_policy",
        )

        self.assert_degraded_contract(
            result,
            mode="pgvector_error",
            filter_level="strict",
            failure_reason="PGVECTOR_ERROR",
        )

    def test_relaxed_vector_error_uses_current_plan_stable_degraded_contract(self) -> None:
        class RelaxedVectorFailureRetriever(PgVectorKnowledgeRetriever):
            def __init__(self) -> None:
                super().__init__(layered_config(dsn="postgresql://unused", embedding_api_key="fake"))
                self.vector_calls = 0

            def _embed(self, _text):
                return [0.0]

            def _vector_search(self, **_kwargs):
                self.vector_calls += 1
                if self.vector_calls == 1:
                    return []
                raise RuntimeError("relaxed vector database unavailable")

            def _lexical_fallback(self, **kwargs):
                return {"mode": "lexical_fallback", "query": kwargs.get("query") or "", "hits": [], "trace": {}}

        result = _retrieve_with_fake_psycopg(
            RelaxedVectorFailureRetriever(),
            source_type="faq",
            product_category="headphone",
            scene="quality_issue",
        )

        self.assertEqual([], result["hits"])
        self.assert_degraded_contract(
            result,
            mode="pgvector_error",
            filter_level="category_relaxed",
            failure_reason="PGVECTOR_ERROR",
        )

    def test_relaxed_lexical_error_uses_current_plan_stable_degraded_contract(self) -> None:
        class RelaxedLexicalFailureRetriever(PgVectorKnowledgeRetriever):
            def __init__(self) -> None:
                super().__init__(layered_config(dsn="postgresql://unused", embedding_api_key="fake"))
                self.lexical_calls = 0

            def _embed(self, _text):
                return [0.0]

            def _vector_search(self, **_kwargs):
                return []

            def _lexical_fallback(self, **kwargs):
                self.lexical_calls += 1
                if self.lexical_calls == 1:
                    return {"mode": "lexical_fallback", "query": kwargs.get("query") or "", "hits": [], "trace": {}}
                raise RuntimeError("relaxed lexical database unavailable")

        result = _retrieve_with_fake_psycopg(
            RelaxedLexicalFailureRetriever(),
            source_type="faq",
            product_category="headphone",
            scene="quality_issue",
        )

        self.assertEqual([], result["hits"])
        self.assert_degraded_contract(
            result,
            mode="lexical_error",
            filter_level="category_relaxed",
            failure_reason="LEXICAL_ERROR",
        )

    def test_relaxed_keyword_database_error_preserves_lexical_failure_contract(self) -> None:
        class RelaxedKeywordFailureRetriever(PgVectorKnowledgeRetriever):
            def __init__(self) -> None:
                super().__init__(layered_config(dsn="postgresql://unused", embedding_api_key="fake"))
                self.keyword_calls = 0

            def _embed(self, _text):
                return [0.0]

            def _vector_search(self, **_kwargs):
                return []

            def _keyword_search(self, **_kwargs):
                self.keyword_calls += 1
                if self.keyword_calls == 1:
                    return []
                raise RuntimeError("relaxed keyword database unavailable")

        result = _retrieve_with_fake_psycopg(
            RelaxedKeywordFailureRetriever(),
            source_type="faq",
            product_category="headphone",
            scene="quality_issue",
        )

        self.assertEqual([], result["hits"])
        self.assert_degraded_contract(
            result,
            mode="lexical_error",
            filter_level="category_relaxed",
            failure_reason="LEXICAL_ERROR",
        )

    def test_exhausted_relaxed_plans_use_stable_degraded_contract(self) -> None:
        class EmptyRetriever(PgVectorKnowledgeRetriever):
            def _embed(self, _text):
                return [0.0]

            def _vector_search(self, **_kwargs):
                return []

            def _lexical_fallback(self, **kwargs):
                return {"mode": "lexical_fallback", "query": kwargs.get("query") or "", "hits": [], "trace": {}}

        result = _retrieve_with_fake_psycopg(
            EmptyRetriever(layered_config(dsn="postgresql://unused", embedding_api_key="fake")),
            source_type="faq",
            product_category="headphone",
            scene="quality_issue",
            intent="refund",
        )

        self.assert_degraded_contract(
            result,
            mode="pgvector_relaxed_filters",
            filter_level="intent_relaxed",
            failure_reason="NO_MATCH",
        )

    def test_query_embedding_cache_reuses_vector_until_ttl_expiry(self) -> None:
        class CachedEmbeddingRetriever(PgVectorKnowledgeRetriever):
            def __init__(self) -> None:
                super().__init__(
                    layered_config(
                        dsn="",
                        embedding_api_key="",
                        embedding_cache_ttl_seconds=300,
                        embedding_cache_max_entries=2,
                    )
                )
                self.embed_calls = 0

            def _embed(self, text: str) -> list[float]:
                self.embed_calls += 1
                return [float(self.embed_calls)]

        retriever = CachedEmbeddingRetriever()
        first, first_hit = retriever._get_query_embedding("same question")
        second, second_hit = retriever._get_query_embedding("same question")

        self.assertEqual([1.0], first)
        self.assertEqual([1.0], second)
        self.assertFalse(first_hit)
        self.assertTrue(second_hit)
        self.assertEqual(1, retriever.embed_calls)

    def test_chinese_digital_category_matches_seeded_db_aliases(self) -> None:
        aliases = PgVectorKnowledgeRetriever._product_category_aliases("数码")

        self.assertIn("digital", aliases)
        self.assertIn("headphone", aliases)
        self.assertIn("phone", aliases)

    def test_controlled_product_categories_keep_java_and_python_filter_values_compatible(self) -> None:
        self.assertIn("apparel", PgVectorKnowledgeRetriever._product_category_aliases("服装"))
        self.assertIn("服装", PgVectorKnowledgeRetriever._product_category_aliases("apparel"))
        self.assertIn("home", PgVectorKnowledgeRetriever._product_category_aliases("家居"))

    def test_vector_filter_includes_global_knowledge_without_crossing_other_merchants(self) -> None:
        cursor = _CapturingCursor()
        psycopg = types.SimpleNamespace(connect=lambda _dsn: _FakeConnection(cursor))
        retriever = PgVectorKnowledgeRetriever(layered_config(dsn="postgresql://unused", embedding_api_key="fake"))

        hits = retriever._vector_search(
            psycopg_module=psycopg,
            embedding=[0.0],
            merchant_code="MERCHANT_DEMO",
            product_category=None,
            scene=None,
            intent=None,
            source_type=None,
            policy_version=None,
            limit=5,
        )

        self.assertEqual([], hits)
        search_sql, search_params = cursor.executions[1]
        self.assertIn("kd.merchant_code IN (%s, 'GLOBAL')", search_sql)
        self.assertIn("COALESCE(kd.metadata ->> 'deleted', 'false') <> 'true'", search_sql)
        self.assertIn("MERCHANT_DEMO", search_params)

    def test_lexical_filter_uses_same_global_scope_and_soft_delete_boundary(self) -> None:
        cursor = _CapturingCursor()
        fake_psycopg = types.SimpleNamespace(connect=lambda _dsn: _FakeConnection(cursor))
        old_psycopg = sys.modules.get("psycopg")
        sys.modules["psycopg"] = fake_psycopg
        try:
            retriever = PgVectorKnowledgeRetriever(layered_config(dsn="postgresql://unused", embedding_api_key="fake"))
            result = retriever._lexical_fallback(query="退款规则", merchant_code="MERCHANT_DEMO")
        finally:
            if old_psycopg is None:
                sys.modules.pop("psycopg", None)
            else:
                sys.modules["psycopg"] = old_psycopg

        self.assertEqual([], result["hits"])
        self.assert_degraded_contract(
            result,
            mode="lexical_fallback",
            filter_level="strict",
            failure_reason="LEXICAL_FALLBACK_ONLY",
        )
        search_sql, search_params = cursor.executions[0]
        self.assertIn("kd.merchant_code IN (%s, 'GLOBAL')", search_sql)
        self.assertIn("COALESCE(kd.metadata ->> 'deleted', 'false') <> 'true'", search_sql)
        self.assertIn("MERCHANT_DEMO", search_params)

    def test_dense_and_keyword_share_published_revision_merchant_and_validity_filters(self) -> None:
        as_of_time = datetime(2026, 7, 21, 12, 30)
        dense_cursor = _CapturingCursor()
        retriever = PgVectorKnowledgeRetriever(layered_config(dsn="postgresql://unused", embedding_api_key="fake"))
        retriever._vector_search(
            psycopg_module=types.SimpleNamespace(connect=lambda _dsn: _FakeConnection(dense_cursor)),
            embedding=[0.0],
            merchant_code="M1",
            product_category="headphone",
            scene="quality_issue",
            intent="refund",
            source_type="after_sales_policy",
            policy_version="v2",
            as_of_time=as_of_time,
            limit=5,
        )

        keyword_cursor = _CapturingCursor()
        fake_psycopg = types.SimpleNamespace(connect=lambda _dsn: _FakeConnection(keyword_cursor))
        old_psycopg = sys.modules.get("psycopg")
        sys.modules["psycopg"] = fake_psycopg
        try:
            retriever._lexical_fallback(
                query="refund policy",
                merchant_code="M1",
                product_category="headphone",
                scene="quality_issue",
                intent="refund",
                source_type="after_sales_policy",
                policy_version="v2",
                as_of_time=as_of_time,
                top_k=5,
            )
        finally:
            if old_psycopg is None:
                sys.modules.pop("psycopg", None)
            else:
                sys.modules["psycopg"] = old_psycopg

        dense_sql, dense_params = dense_cursor.executions[1]
        keyword_sql, keyword_params = keyword_cursor.executions[0]
        common_fragments = (
            "kd.status = 1",
            "COALESCE(kd.metadata ->> 'deleted', 'false') <> 'true'",
            "kd.published_revision IS NOT NULL",
            "kc.revision = kd.published_revision",
            "kd.merchant_code IN (%s, 'GLOBAL')",
            "kd.valid_from IS NULL OR kd.valid_from <= %s",
            "kd.valid_to IS NULL OR %s < kd.valid_to",
        )
        for fragment in common_fragments:
            self.assertIn(fragment, dense_sql)
            self.assertIn(fragment, keyword_sql)
        self.assertEqual(2, dense_params.count(as_of_time))
        self.assertEqual(2, keyword_params.count(as_of_time))
        self.assertIn("ts_rank_cd", keyword_sql)
        self.assertIn("to_tsquery", keyword_sql)
        self.assertIn("kc.search_vector @@", keyword_sql)

    def test_dense_and_keyword_hits_share_citation_rank_and_raw_score_shape(self) -> None:
        as_of_time = datetime(2026, 7, 21, 12, 30)
        row = (
            101,
            "after_sales_policy",
            "refund-1",
            "Refund policy chunk",
            {},
            "Refund policy",
            ["headphone"],
            ["quality_issue"],
            ["refund"],
            "v2",
            ["policy"],
            "M1",
            ["Refund", "Quality"],
            3,
            7,
            datetime(2026, 7, 1),
            datetime(2026, 8, 1),
            9001,
            0.91,
        )
        dense_cursor = _CapturingCursor(rows=[row])
        retriever = PgVectorKnowledgeRetriever(layered_config(dsn="postgresql://unused", embedding_api_key="fake"))
        dense = retriever._vector_search(
            psycopg_module=types.SimpleNamespace(connect=lambda _dsn: _FakeConnection(dense_cursor)),
            embedding=[0.0],
            merchant_code="M1",
            product_category="headphone",
            scene="quality_issue",
            intent="refund",
            source_type="after_sales_policy",
            policy_version="v2",
            as_of_time=as_of_time,
            limit=5,
        )

        keyword_cursor = _CapturingCursor(rows=[row])
        old_psycopg = sys.modules.get("psycopg")
        sys.modules["psycopg"] = types.SimpleNamespace(connect=lambda _dsn: _FakeConnection(keyword_cursor))
        try:
            keyword = retriever._lexical_fallback(
                query="refund policy",
                merchant_code="M1",
                product_category="headphone",
                scene="quality_issue",
                intent="refund",
                source_type="after_sales_policy",
                policy_version="v2",
                as_of_time=as_of_time,
                top_k=5,
            )["hits"]
        finally:
            if old_psycopg is None:
                sys.modules.pop("psycopg", None)
            else:
                sys.modules["psycopg"] = old_psycopg

        for hit in (dense[0], keyword[0]):
            self.assertEqual(101, hit["chunk_id"])
            self.assertEqual(1, hit["rank"])
            self.assertEqual(0.91, hit["raw_score"])
            self.assertEqual("refund-1", hit["citation"]["source_code"])
            self.assertEqual(9001, hit["citation"]["document_id"])
            self.assertEqual(["Refund", "Quality"], hit["citation"]["heading_path"])
            self.assertEqual(7, hit["citation"]["revision"])
        self.assertEqual(1, dense[0]["dense_rank"])
        self.assertEqual(["dense"], dense[0]["retrieval_channels"])
        self.assertFalse(dense[0]["trusted_policy_eligible"])
        self.assertEqual("strict", dense[0]["relaxation_level"])
        self.assertEqual(1, keyword[0]["keyword_rank"])
        self.assertEqual(["keyword"], keyword[0]["retrieval_channels"])
        self.assertFalse(keyword[0]["trusted_policy_eligible"])
        self.assertEqual("strict", keyword[0]["relaxation_level"])
        self.assertEqual(dense[0]["citation"], keyword[0]["citation"])

    def test_strict_hybrid_rerank_is_the_only_path_that_can_mark_policy_trusted(self) -> None:
        reranker = _FakeReranker(score=0.8)
        retriever = _PipelineRetriever(reranker=reranker, dense=True, keyword=True)

        result = _retrieve_with_fake_psycopg(
            retriever,
            source_type="after_sales_policy",
            product_category="headphone",
            scene="quality_issue",
        )

        self.assertEqual("hybrid_reranked", result["mode"])
        self.assertEqual("strict", result["filter_level"])
        self.assertTrue(result["reranker_succeeded"])
        self.assertEqual(0.35, result["threshold"])
        self.assertFalse(result["no_answer"])
        self.assertTrue(result["trusted_policy_eligible"])
        self.assertTrue(result["hits"][0]["trusted_policy_eligible"])
        self.assertEqual(4.25, result["trace"]["stage_latency_ms"]["reranker"])
        self.assertEqual(
            {
                "filter_level",
                "dense_candidate_count",
                "keyword_candidate_count",
                "rrf_candidate_count",
                "rerank_candidate_count",
                "retrieval_mode",
                "stage_latency_ms",
                "fallback_reason",
            },
            {
                "filter_level",
                "dense_candidate_count",
                "keyword_candidate_count",
                "rrf_candidate_count",
                "rerank_candidate_count",
                "retrieval_mode",
                "stage_latency_ms",
                "fallback_reason",
            }.intersection(result["trace"]),
        )
        self.assertEqual(1, result["trace"]["dense_candidate_count"])
        self.assertEqual(1, result["trace"]["keyword_candidate_count"])
        self.assertEqual(1, result["trace"]["rrf_candidate_count"])
        self.assertEqual(1, result["trace"]["rerank_candidate_count"])
        self.assertEqual("hybrid_reranked", result["trace"]["retrieval_mode"])
        self.assertIsNone(result["trace"]["fallback_reason"])
        self.assertEqual(1, len(reranker.calls))

    def test_reranker_receives_rrf_top_twenty_before_applying_top_n(self) -> None:
        reranker = _FakeReranker(score=0.8)
        retriever = _PipelineRetriever(reranker=reranker, dense=True, keyword=True, candidate_count=25)

        _retrieve_with_fake_psycopg(retriever, source_type="faq", top_k=5)

        self.assertEqual(20, len(reranker.calls[0][1]))
        self.assertEqual(5, reranker.calls[0][2])

    def test_evaluation_ablation_modes_stop_before_later_pipeline_stages(self) -> None:
        expected = {
            "dense": (1, 0, 0),
            "keyword": (0, 1, 0),
            "rrf": (1, 1, 1),
        }
        for retrieval_mode, counts in expected.items():
            with self.subTest(retrieval_mode=retrieval_mode):
                reranker = _FakeReranker(score=0.8)
                result = _retrieve_with_fake_psycopg(
                    _PipelineRetriever(reranker=reranker, dense=True, keyword=True),
                    source_type="faq",
                    retrieval_mode=retrieval_mode,
                )

                self.assertEqual(retrieval_mode, result["mode"])
                self.assertEqual(retrieval_mode, result["trace"]["retrieval_mode"])
                self.assertEqual(counts[0], result["trace"]["dense_candidate_count"])
                self.assertEqual(counts[1], result["trace"]["keyword_candidate_count"])
                self.assertEqual(counts[2], result["trace"]["rrf_candidate_count"])
                self.assertEqual(0, result["trace"]["rerank_candidate_count"])
                self.assertEqual([], reranker.calls)
                self.assertFalse(result["trusted_policy_eligible"])

    def test_dense_empty_strict_result_never_calls_keyword_rrf_or_reranker(self) -> None:
        class CountingPipelineRetriever(_PipelineRetriever):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.vector_calls = 0
                self.keyword_calls = 0

            def _vector_search(self, **kwargs):
                self.vector_calls += 1
                return super()._vector_search(**kwargs)

            def _lexical_fallback(self, **kwargs):
                self.keyword_calls += 1
                return super()._lexical_fallback(**kwargs)

        reranker = _FakeReranker(score=0.99)
        retriever = CountingPipelineRetriever(reranker=reranker, dense=False, keyword=True)

        result = _retrieve_with_fake_psycopg(
            retriever,
            source_type="faq",
            product_category="missing-category",
            retrieval_mode="dense",
        )

        self.assertEqual("dense", result["mode"])
        self.assertTrue(result["no_answer"])
        self.assertEqual(1, retriever.vector_calls)
        self.assertEqual(0, retriever.keyword_calls)
        self.assertEqual([], reranker.calls)
        self.assertEqual(0, result["trace"]["keyword_candidate_count"])
        self.assertEqual(0, result["trace"]["rrf_candidate_count"])
        self.assertEqual(0, result["trace"]["rerank_candidate_count"])

    def test_dense_embedding_failure_never_calls_keyword_local_or_reranker(self) -> None:
        class DenseEmbeddingFailureRetriever(PgVectorKnowledgeRetriever):
            def _get_query_embedding(self, _query):
                raise RuntimeError("embedding unavailable")

            def _local_knowledge_fallback(self, **_kwargs):
                raise AssertionError("dense mode must not call local fallback")

            def _lexical_fallback(self, **_kwargs):
                raise AssertionError("dense mode must not call keyword fallback")

        reranker = _FakeReranker(score=0.99)
        result = _retrieve_with_fake_psycopg(
            DenseEmbeddingFailureRetriever(
                layered_config(dsn="postgresql://unused", embedding_api_key="fake"),
                reranker=reranker,
            ),
            source_type="faq",
            retrieval_mode="dense",
        )

        self.assertEqual("dense", result["mode"])
        self.assertTrue(result["no_answer"])
        self.assertEqual("EMBEDDING_ERROR", result["failure_reason"])
        self.assertEqual("dense", result["trace"]["retrieval_mode"])
        self.assertEqual(0, result["trace"]["keyword_candidate_count"])
        self.assertEqual(0, result["trace"]["rrf_candidate_count"])
        self.assertEqual(0, result["trace"]["rerank_candidate_count"])
        self.assertEqual([], reranker.calls)

    def test_runtime_trace_drops_query_tokens_and_free_filter_values(self) -> None:
        class UnsafeCompatibilityRetriever(PgVectorKnowledgeRetriever):
            def _lexical_fallback(self, **kwargs):
                return {
                    "mode": "lexical_fallback",
                    "query": kwargs["query"],
                    "hits": [],
                    "trace": {
                        "tokens": ["secret-query-token"],
                        "filters": {"merchant_code": "secret-merchant"},
                        "strict_filters": {"policy_version": "secret-version"},
                        "fallback_attempts": [{"filters": {"merchant_code": "secret-merchant"}}],
                        "top_k": 5,
                    },
                }

        result = UnsafeCompatibilityRetriever(
            PgVectorConfig(
                dsn="postgresql://unused",
                layered_retrieval_enabled=False,
                embedding_api_key="unused",
            )
        ).retrieve(
            query="secret-query-token",
            merchant_code="secret-merchant",
            policy_version="secret-version",
        )

        serialized_trace = str(result["trace"])
        self.assertNotIn("secret-query-token", serialized_trace)
        self.assertNotIn("secret-merchant", serialized_trace)
        self.assertNotIn("secret-version", serialized_trace)
        self.assertNotIn("tokens", result["trace"])
        self.assertNotIn("filters", result["trace"])
        self.assertNotIn("fallback_attempts", result["trace"])

    def test_retrieval_rejects_unknown_ablation_mode_before_provider_access(self) -> None:
        retriever = _PipelineRetriever(
            reranker=_FakeReranker(score=0.8),
            dense=True,
            keyword=True,
        )

        with self.assertRaisesRegex(ValueError, "retrieval_mode"):
            _retrieve_with_fake_psycopg(retriever, retrieval_mode="magic")

    def test_rrf_ablation_preserves_mode_when_relaxed_filters_find_candidates(self) -> None:
        reranker = _FakeReranker(score=0.99)

        result = _retrieve_with_fake_psycopg(
            _RelaxedPipelineRetriever(reranker=reranker),
            source_type="faq",
            product_category="missing-category",
            retrieval_mode="rrf",
        )

        self.assertEqual("rrf", result["mode"])
        self.assertEqual("rrf", result["trace"]["retrieval_mode"])
        self.assertEqual([], reranker.calls)

    def test_unconfigured_or_failed_reranker_returns_rrf_and_never_trusts_policy(self) -> None:
        reranker = _FakeReranker(score=0.99, degraded=True, failure_reason="NOT_CONFIGURED")
        retriever = _PipelineRetriever(reranker=reranker, dense=True, keyword=True)

        result = _retrieve_with_fake_psycopg(retriever, source_type="after_sales_policy")

        self.assertEqual("hybrid_rrf_degraded", result["mode"])
        self.assertFalse(result["reranker_succeeded"])
        self.assertTrue(result["no_answer"])
        self.assertFalse(result["trusted_policy_eligible"])
        self.assertFalse(result["hits"][0]["trusted_policy_eligible"])
        self.assertEqual("NOT_CONFIGURED", result["trace"]["reranker_failure_reason"])

    def test_single_channel_policy_hit_is_trusted_after_successful_rerank(self) -> None:
        for dense, keyword in ((True, False), (False, True)):
            with self.subTest(dense=dense, keyword=keyword):
                reranker = _FakeReranker(score=0.99)
                retriever = _PipelineRetriever(reranker=reranker, dense=dense, keyword=keyword)

                result = _retrieve_with_fake_psycopg(retriever, source_type="after_sales_policy")

                self.assertTrue(result["reranker_succeeded"])
                self.assertTrue(result["trusted_policy_eligible"])
                self.assertTrue(result["hits"][0]["trusted_policy_eligible"])

    def test_keyword_only_policy_hit_is_trusted_when_other_dense_hit_exists(self) -> None:
        retriever = PgVectorKnowledgeRetriever(
            layered_config(dsn="postgresql://unused", embedding_api_key="fake"),
            reranker=_FakeReranker(score=0.99),
        )
        plan = retriever._strict_filter_plan(
            merchant_code="M1",
            product_category="headphone",
            scene="quality_issue",
            intent="refund",
            source_type=None,
            policy_version=None,
            as_of_time=datetime(2026, 7, 21, 12, 30),
        )

        result = retriever._finalize_reranked_result(
            query="refund policy",
            dense_hits=[
                {
                    "chunk_id": "FAQ-A",
                    "chunk_text": "faq",
                    "source_type": "faq",
                    "metadata": {"merchant_code": "M1"},
                }
            ],
            keyword_hits=[
                {
                    "chunk_id": "POLICY-B",
                    "chunk_text": "policy",
                    "source_type": "after_sales_policy",
                    "metadata": {"merchant_code": "M1"},
                }
            ],
            plan=plan,
            limit=5,
            trace={},
        )

        policy_hit = next(hit for hit in result["hits"] if hit["chunk_id"] == "POLICY-B")
        self.assertEqual(["keyword"], policy_hit["retrieval_channels"])
        self.assertTrue(policy_hit["trusted_policy_eligible"])
        self.assertTrue(result["trusted_policy_eligible"])

    def test_successful_rerank_applies_source_threshold_and_sets_no_answer(self) -> None:
        policy_result = _retrieve_with_fake_psycopg(
            _PipelineRetriever(reranker=_FakeReranker(score=0.34), dense=True, keyword=True),
            source_type="after_sales_policy",
        )
        faq_result = _retrieve_with_fake_psycopg(
            _PipelineRetriever(reranker=_FakeReranker(score=0.61), dense=True, keyword=True),
            source_type="faq",
        )

        self.assertEqual(0.35, policy_result["threshold"])
        self.assertTrue(policy_result["no_answer"])
        self.assertEqual([], policy_result["hits"])
        self.assertEqual(0.4, faq_result["threshold"])
        self.assertFalse(faq_result["no_answer"])
        self.assertEqual(1, len(faq_result["hits"]))

    def test_relaxed_filter_result_stays_untrusted_even_when_reranker_succeeds(self) -> None:
        reranker = _FakeReranker(score=0.99)
        retriever = _RelaxedPipelineRetriever(reranker=reranker)

        result = _retrieve_with_fake_psycopg(
            retriever,
            source_type="after_sales_policy",
            product_category="missing-category",
            scene="quality_issue",
        )

        self.assertTrue(result["reranker_succeeded"])
        self.assertEqual("category_relaxed", result["filter_level"])
        self.assertFalse(result["trusted_policy_eligible"])
        self.assertFalse(result["hits"][0]["trusted_policy_eligible"])

    def test_local_fallback_uses_scene_aliases_for_damage(self) -> None:
        retriever = PgVectorKnowledgeRetriever(layered_config(dsn="", embedding_api_key=""))

        result = retriever._local_knowledge_fallback(
            query="耳机外壳破裂 破损照片 售后证据",
            merchant_code="MERCHANT_DEMO",
            product_category="数码",
            scene="damage",
            top_k=5,
        )

        titles = [hit["title"] for hit in result["hits"]]
        self.assertIn("商品破损", titles)
        self.assert_degraded_contract(
            result,
            mode="local_json_fallback",
            filter_level="strict",
            failure_reason="LOCAL_FALLBACK_ONLY",
        )

    def test_local_fallback_finds_repo_knowledge_when_cwd_is_python_agent(self) -> None:
        retriever = PgVectorKnowledgeRetriever(layered_config(dsn="", embedding_api_key=""))
        old_cwd = pathlib.Path.cwd()
        try:
            os.chdir(RETRIEVER_PATH.parents[1])
            result = retriever._local_knowledge_fallback(
                query="耳机外壳破裂 破损照片 售后证据",
                merchant_code="MERCHANT_DEMO",
                product_category="数码",
                scene="damage",
                top_k=5,
            )
        finally:
            os.chdir(old_cwd)

        titles = [hit["title"] for hit in result["hits"]]
        self.assertIn("商品破损", titles)

    def test_retrieve_relaxes_category_and_scene_after_empty_strict_recall(self) -> None:
        class RelaxingRetriever(PgVectorKnowledgeRetriever):
            def __init__(self) -> None:
                super().__init__(layered_config(dsn="postgresql://unused", embedding_api_key="fake"))
                self.vector_calls: list[tuple[str | None, str | None]] = []

            def _embed(self, text: str) -> list[float]:
                return [0.0]

            def _vector_search(self, **kwargs):
                self.vector_calls.append((kwargs.get("product_category"), kwargs.get("scene")))
                if kwargs.get("product_category") is None and kwargs.get("scene") is None:
                    return [
                        {
                            "id": 1,
                            "source_type": "after_sales_policy",
                            "source_code": "damage_headphone_shell_refund_001",
                            "title": "耳机外壳破裂退款规则",
                            "snippet": "耳机外壳破裂可根据破损照片进入售后审核。",
                            "score": 0.91,
                            "metadata": {"product_category": "headphone", "scene": "damage"},
                        }
                    ]
                return []

            def _lexical_fallback(self, **kwargs):
                return {"mode": "lexical_fallback", "query": kwargs.get("query") or "", "hits": [], "trace": {}}

        old_psycopg = sys.modules.get("psycopg")
        sys.modules["psycopg"] = types.SimpleNamespace()
        try:
            retriever = RelaxingRetriever()
            result = retriever.retrieve(
                query="耳机外壳破裂",
                merchant_code="MERCHANT_DEMO",
                product_category="不存在的前端品类",
                scene="不存在的场景",
                top_k=5,
                retrieval_mode="rerank",
            )
        finally:
            if old_psycopg is None:
                sys.modules.pop("psycopg", None)
            else:
                sys.modules["psycopg"] = old_psycopg

        self.assertEqual("hybrid_rrf_degraded", result["mode"])
        self.assertEqual(
            [
                ("不存在的前端品类", "不存在的场景"),
                (None, "不存在的场景"),
                ("不存在的前端品类", None),
                (None, None),
            ],
            retriever.vector_calls,
        )
        self.assertEqual("category_and_scene_relaxed", result["trace"]["fallback_level"])
        self.assertEqual("category_and_scene_relaxed", result["relaxation_level"])
        self.assertFalse(result["trusted_policy_eligible"])
        self.assertFalse(result["trace"]["trusted_policy_eligible"])
        self.assertFalse(result["hits"][0]["trusted_policy_eligible"])
        self.assertEqual("耳机外壳破裂退款规则", result["hits"][0]["title"])

    def test_retrieve_preserves_scene_before_global_relaxation(self) -> None:
        class SceneFirstRetriever(PgVectorKnowledgeRetriever):
            def __init__(self) -> None:
                super().__init__(layered_config(dsn="postgresql://unused", embedding_api_key="fake"))
                self.vector_calls: list[tuple[str | None, str | None]] = []

            def _embed(self, text: str) -> list[float]:
                return [0.0]

            def _vector_search(self, **kwargs):
                current = (kwargs.get("product_category"), kwargs.get("scene"))
                self.vector_calls.append(current)
                if current == (None, "quality_issue"):
                    return [
                        {
                            "id": 2,
                            "source_type": "after_sales_policy",
                            "source_code": "general_quality_issue_001",
                            "title": "通用品质问题规则",
                            "snippet": "按品质问题场景补充问题描述。",
                            "score": 0.8,
                            "metadata": {"product_category": "general", "scene": "quality_issue"},
                        }
                    ]
                return []

            def _lexical_fallback(self, **kwargs):
                return {"mode": "lexical_fallback", "query": kwargs.get("query") or "", "hits": [], "trace": {}}

        old_psycopg = sys.modules.get("psycopg")
        sys.modules["psycopg"] = types.SimpleNamespace()
        try:
            retriever = SceneFirstRetriever()
            result = retriever.retrieve(
                query="衣服有质量问题",
                merchant_code="MERCHANT_DEMO",
                product_category="服装",
                scene="quality_issue",
                retrieval_mode="rerank",
            )
        finally:
            if old_psycopg is None:
                sys.modules.pop("psycopg", None)
            else:
                sys.modules["psycopg"] = old_psycopg

        self.assertEqual("hybrid_rrf_degraded", result["mode"])
        self.assertEqual("category_relaxed", result["trace"]["fallback_level"])
        self.assertEqual("category_relaxed", result["relaxation_level"])
        self.assertFalse(result["trusted_policy_eligible"])
        self.assertFalse(result["hits"][0]["trusted_policy_eligible"])
        self.assertEqual([("服装", "quality_issue"), (None, "quality_issue")], retriever.vector_calls)

    def test_keyword_relaxed_hit_carries_explicit_untrusted_filter_contract(self) -> None:
        class KeywordRelaxingRetriever(PgVectorKnowledgeRetriever):
            def _embed(self, text: str) -> list[float]:
                return [0.0]

            def _vector_search(self, **_kwargs):
                return []

            def _lexical_fallback(self, **kwargs):
                if kwargs.get("product_category") is None and kwargs.get("scene") == "quality_issue":
                    return {
                        "mode": "lexical_fallback",
                        "query": kwargs.get("query") or "",
                        "hits": [{"id": 9, "chunk_id": 9, "title": "general quality FAQ", "score": 2.4}],
                        "trace": {},
                    }
                return {"mode": "lexical_fallback", "query": kwargs.get("query") or "", "hits": [], "trace": {}}

        old_psycopg = sys.modules.get("psycopg")
        sys.modules["psycopg"] = types.SimpleNamespace()
        try:
            result = KeywordRelaxingRetriever(
                layered_config(dsn="postgresql://unused", embedding_api_key="fake")
            ).retrieve(
                query="quality question",
                merchant_code="M1",
                product_category="headphone",
                scene="quality_issue",
                source_type="faq",
                retrieval_mode="rerank",
            )
        finally:
            if old_psycopg is None:
                sys.modules.pop("psycopg", None)
            else:
                sys.modules["psycopg"] = old_psycopg

        self.assertEqual("hybrid_rrf_degraded", result["mode"])
        self.assertEqual("category_relaxed", result["relaxation_level"])
        self.assertFalse(result["trusted_policy_eligible"])
        self.assertFalse(result["trace"]["trusted_policy_eligible"])
        self.assertFalse(result["hits"][0]["trusted_policy_eligible"])


class _FakeReranker:
    def __init__(self, *, score: float, degraded: bool = False, failure_reason=None) -> None:
        self.score = score
        self.degraded = degraded
        self.failure_reason = failure_reason
        self.calls: list[tuple[str, list[dict[str, object]], int]] = []

    def rerank(self, query, candidates, top_n):
        self.calls.append((query, list(candidates), top_n))
        if self.degraded:
            return RerankResult(
                items=list(candidates[:top_n]),
                mode="hybrid_rrf_degraded",
                degraded=True,
                failure_reason=self.failure_reason,
                latency_ms=4.25,
            )
        items = []
        for index, candidate in enumerate(candidates[:top_n]):
            items.append({**candidate, "provider_index": index, "relevance_score": self.score, "rerank_score": self.score})
        return RerankResult(
            items=items,
            mode="hybrid_reranked",
            degraded=False,
            failure_reason=None,
            latency_ms=4.25,
        )


class _PipelineRetriever(PgVectorKnowledgeRetriever):
    def __init__(self, *, reranker, dense: bool, keyword: bool, candidate_count: int = 1) -> None:
        super().__init__(
            layered_config(dsn="postgresql://unused", embedding_api_key="fake"),
            reranker=reranker,
        )
        self.dense_enabled = dense
        self.keyword_enabled = keyword
        self.candidate_count = candidate_count

    def _embed(self, text: str) -> list[float]:
        return [0.0]

    def _hits(self, channel: str, source_type: str = "after_sales_policy") -> list[dict[str, object]]:
        return [
            {
                "id": index + 1,
                "chunk_id": index + 1,
                "chunk_text": f"policy-{index}",
                "snippet": f"policy-{index}",
                "source_type": source_type,
                "source_code": f"P-{index}",
                "raw_score": 0.9 - index / 100,
                "score": 0.9 - index / 100,
                f"{channel}_rank": index + 1,
                f"{channel}_score": 0.9 - index / 100,
                "retrieval_channels": [channel],
                "metadata": {"merchant_code": "M1", "source_type": source_type},
                "trusted_policy_eligible": False,
                "relaxation_level": "strict",
            }
            for index in range(self.candidate_count)
        ]

    def _vector_search(self, **kwargs):
        return self._hits("dense", kwargs.get("source_type") or "after_sales_policy") if self.dense_enabled else []

    def _lexical_fallback(self, **kwargs):
        return {
            "mode": "lexical_fallback",
            "query": kwargs.get("query") or "",
            "hits": self._hits("keyword", kwargs.get("source_type") or "after_sales_policy") if self.keyword_enabled else [],
            "trace": {},
        }


class _RelaxedPipelineRetriever(_PipelineRetriever):
    def __init__(self, *, reranker) -> None:
        super().__init__(reranker=reranker, dense=True, keyword=True)

    def _vector_search(self, **kwargs):
        return self._hits("dense", kwargs.get("source_type") or "after_sales_policy") if kwargs.get("product_category") is None else []

    def _lexical_fallback(self, **kwargs):
        hits = self._hits("keyword", kwargs.get("source_type") or "after_sales_policy") if kwargs.get("product_category") is None else []
        return {"mode": "lexical_fallback", "query": kwargs.get("query") or "", "hits": hits, "trace": {}}


def _retrieve_with_fake_psycopg(retriever, **overrides):
    old_psycopg = sys.modules.get("psycopg")
    sys.modules["psycopg"] = types.SimpleNamespace()
    arguments = {
        "query": "refund policy",
        "merchant_code": "M1",
        "product_category": "headphone",
        "scene": "quality_issue",
        "source_type": "after_sales_policy",
        "top_k": 5,
        "retrieval_mode": "rerank",
    }
    arguments.update(overrides)
    try:
        return retriever.retrieve(**arguments)
    finally:
        if old_psycopg is None:
            sys.modules.pop("psycopg", None)
        else:
            sys.modules["psycopg"] = old_psycopg


class _CapturingCursor:
    def __init__(self, rows=None) -> None:
        self.executions: list[tuple[str, list[object]]] = []
        self.rows = list(rows or [])

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None) -> None:
        self.executions.append((str(sql), list(params or [])))

    def fetchall(self):
        return self.rows


class _FakeConnection:
    def __init__(self, cursor: _CapturingCursor) -> None:
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self._cursor


class _RecordingMultiQueryReranker:
    def __init__(self) -> None:
        self.config = types.SimpleNamespace(configured=True)
        self.calls: list[tuple[str, list[dict[str, object]], int]] = []

    def rerank(self, query, candidates, top_n):
        copied = [dict(item) for item in candidates]
        self.calls.append((query, copied, top_n))
        items = []
        for item in copied[:top_n]:
            item["rerank_score"] = 0.9
            item["relevance_score"] = 0.9
            items.append(item)
        return RerankResult(
            items=items,
            mode="hybrid_reranked",
            degraded=False,
            failure_reason=None,
            latency_ms=3.0,
        )


class _StubMultiQueryRetriever(PgVectorKnowledgeRetriever):
    def __init__(self, responses):
        self.responses = dict(responses)
        self.candidate_calls: list[dict[str, object]] = []
        self.recording_reranker = _RecordingMultiQueryReranker()
        super().__init__(
            layered_config(dsn="postgresql://unused", embedding_api_key="unused"),
            reranker=self.recording_reranker,
        )

    def retrieve(self, **kwargs):
        self.candidate_calls.append(dict(kwargs))
        response = self.responses[str(kwargs["query"])]
        if isinstance(response, Exception):
            raise response
        return response


class PgVectorMultiQueryRetrievalTest(unittest.TestCase):
    @staticmethod
    def _hit(chunk_id: str) -> dict[str, object]:
        return {
            "chunk_id": chunk_id,
            "source_type": "faq",
            "source_code": f"SOURCE-{chunk_id}",
            "snippet": f"content-{chunk_id}",
            "retrieval_channels": ["dense", "keyword"],
            "metadata": {"merchant_code": "M1"},
        }

    def test_multi_query_preserves_filters_and_reranks_with_validated_candidates(self) -> None:
        retriever = _StubMultiQueryRetriever(
            {
                "query one": {"mode": "rrf", "hits": [self._hit("A"), self._hit("B")]},
                "query two": {"mode": "rrf", "hits": [self._hit("B"), self._hit("C")]},
            }
        )

        result = retriever.retrieve_multi(
            original_query="original user question",
            queries=["query one", "query two"],
            merchant_code="M1",
            product_category="headphone",
            scene="quality_issue",
            intent="refund",
            source_type="faq",
            policy_version="v2",
            as_of_time=datetime.fromisoformat("2026-07-20T09:00:00+08:00"),
            top_k=5,
        )

        self.assertEqual({"query one", "query two"}, {item["query"] for item in retriever.candidate_calls})
        for call in retriever.candidate_calls:
            self.assertEqual("rrf", call["retrieval_mode"])
            self.assertEqual("M1", call["merchant_code"])
            self.assertEqual("headphone", call["product_category"])
            self.assertEqual("quality_issue", call["scene"])
            self.assertEqual("refund", call["intent"])
            self.assertEqual("faq", call["source_type"])
            self.assertEqual("v2", call["policy_version"])
        self.assertEqual(
            {"query one", "query two"},
            {call[0] for call in retriever.recording_reranker.calls},
        )
        self.assertTrue(
            all(call[1][0]["chunk_id"] == "B" for call in retriever.recording_reranker.calls)
        )
        self.assertEqual("multi_query_reranked", result["mode"])
        self.assertEqual("validated_candidate_queries", result["trace"]["rerank_query_source"])
        self.assertEqual(2, result["trace"]["rerank_query_count"])
        self.assertEqual(2, result["trace"]["rerank_query_success_count"])
        self.assertEqual(3, result["trace"]["unique_candidate_count"])
        self.assertEqual(2, len(result["trace"]["candidate_traces"]))
        self.assertIn("multi_query", result["trace"]["stage_latency_ms"])
        self.assertIn("reranker", result["trace"]["stage_latency_ms"])
        self.assertIn("total", result["trace"]["stage_latency_ms"])

    def test_multi_query_keeps_successful_results_when_one_candidate_fails(self) -> None:
        retriever = _StubMultiQueryRetriever(
            {
                "query one": RuntimeError("candidate failed"),
                "query two": {"mode": "rrf", "hits": [self._hit("B")]},
            }
        )

        result = retriever.retrieve_multi(
            original_query="original",
            queries=["query one", "query two"],
            source_type="faq",
            top_k=5,
        )

        self.assertEqual(["B"], [item["chunk_id"] for item in result["hits"]])
        self.assertEqual(1, result["trace"]["candidate_failure_count"])
        self.assertEqual("RuntimeError", result["trace"]["candidate_traces"][0]["error_type"])
        self.assertFalse(result["no_answer"])

    def test_multi_query_all_failures_return_structured_failure(self) -> None:
        retriever = _StubMultiQueryRetriever(
            {
                "query one": RuntimeError("first failed"),
                "query two": RuntimeError("second failed"),
            }
        )

        result = retriever.retrieve_multi(
            original_query="original",
            queries=["query one", "query two"],
            source_type="faq",
            top_k=5,
        )

        self.assertEqual("multi_query_error", result["mode"])
        self.assertEqual("MULTI_QUERY_ERROR", result["failure_reason"])
        self.assertTrue(result["no_answer"])
        self.assertEqual([], result["hits"])


def test_rrf_uses_rank_not_incompatible_raw_scores() -> None:
    fused = rrf_fuse(
        [{"chunk_id": "A", "score": 0.99}, {"chunk_id": "B", "score": 0.98}],
        [{"chunk_id": "B", "score": 100.0}, {"chunk_id": "C", "score": 99.0}],
        k=60,
        limit=20,
    )

    assert fused[0]["chunk_id"] == "B"
    assert fused[0]["dense_rank"] == 2
    assert fused[0]["keyword_rank"] == 1


def test_rrf_order_is_unchanged_when_raw_scores_change() -> None:
    first = rrf_fuse(
        [{"chunk_id": "A", "score": 0.9}, {"chunk_id": "B", "score": 0.8}],
        [{"chunk_id": "B", "score": 5.0}, {"chunk_id": "C", "score": 4.0}],
    )
    second = rrf_fuse(
        [{"chunk_id": "A", "score": -1000.0}, {"chunk_id": "B", "score": 9999.0}],
        [{"chunk_id": "B", "score": -42.0}, {"chunk_id": "C", "score": 1_000_000.0}],
    )

    assert [hit["chunk_id"] for hit in first] == [hit["chunk_id"] for hit in second]
    assert [hit["rrf_score"] for hit in first] == [hit["rrf_score"] for hit in second]


def test_rrf_counts_duplicate_chunk_only_once_per_channel() -> None:
    fused = rrf_fuse(
        [
            {"chunk_id": "A", "score": 0.9},
            {"chunk_id": "A", "score": 0.8},
            {"chunk_id": "B", "score": 0.7},
        ],
        [{"chunk_id": "B", "score": 9.0}],
    )

    hit_a = next(hit for hit in fused if hit["chunk_id"] == "A")
    assert hit_a["rrf_score"] == 1.0 / 61
    assert hit_a["retrieval_channels"] == ["dense"]
    assert hit_a["dense_rank"] == 1


def test_rrf_fuse_rankings_rewards_hits_shared_across_queries() -> None:
    fused = rrf_fuse_rankings(
        [
            [
                {"chunk_id": "A", "snippet": "first"},
                {"chunk_id": "B", "snippet": "shared"},
            ],
            [
                {"chunk_id": "B", "snippet": "shared"},
                {"chunk_id": "C", "snippet": "third"},
            ],
        ],
        k=60,
        limit=20,
    )

    assert fused[0]["chunk_id"] == "B"
    assert fused[0]["query_channels"] == ["query_1", "query_2"]
    assert fused[0]["query_ranks"] == {"query_1": 2, "query_2": 1}
    assert fused[0]["rrf_score"] == (1.0 / 62) + (1.0 / 61)


def test_rrf_fuse_rankings_counts_duplicate_once_within_one_query() -> None:
    fused = rrf_fuse_rankings(
        [
            [
                {"chunk_id": "A"},
                {"chunk_id": "A"},
                {"chunk_id": "B"},
            ]
        ]
    )

    hit_a = next(item for item in fused if item["chunk_id"] == "A")
    assert hit_a["rrf_score"] == 1.0 / 61
    assert hit_a["query_ranks"] == {"query_1": 1}


class TestKeywordFTSSearch(unittest.TestCase):

    def setUp(self):
        self._old_psycopg = sys.modules.get("psycopg")

    def tearDown(self):
        if self._old_psycopg is None:
            sys.modules.pop("psycopg", None)
        else:
            sys.modules["psycopg"] = self._old_psycopg
        if hasattr(_CapturingCursor, '_call_count'):
            delattr(_CapturingCursor, '_call_count')

    def test_empty_query_returns_empty(self):
        from after_sales_agent.retrieval.search.keyword_search import lexical_fallback
        fake_psycopg, fts_cursor, _ = _make_fake_psycopg()
        sys.modules["psycopg"] = fake_psycopg
        result = lexical_fallback(
            psycopg_module=fake_psycopg,
            config=types.SimpleNamespace(dsn="postgresql://unused"),
            query="   ",
            merchant_code="M1",
            limit=10,
            **_common_kwargs(),
        )
        self.assertEqual([], result)
        self.assertEqual(0, len(fts_cursor.executions))

    def test_fts_hits_chinese_colloquial_query(self):
        from after_sales_agent.retrieval.search.keyword_search import lexical_fallback
        rows = [(_ROW_TEMPLATE[:18] + (0.35,))]
        fake_psycopg, fts_cursor, _ = _make_fake_psycopg(rows=rows)
        sys.modules["psycopg"] = fake_psycopg
        result = lexical_fallback(
            psycopg_module=fake_psycopg,
            config=types.SimpleNamespace(dsn="postgresql://unused"),
            query="刚拆箱发现商品裂开了退换要准备什么",
            merchant_code="MERCHANT_DEMO",
            limit=10,
            **_common_kwargs(),
        )
        self.assertEqual(1, len(result))
        self.assertEqual(1001, result[0]["chunk_id"])
        self.assertEqual("keyword", result[0]["channel"])
        sql = fts_cursor.executions[0][0]
        self.assertIn("ts_rank_cd", sql)
        self.assertIn("to_tsquery", sql)
        self.assertIn("kc.search_vector @@", sql)
        self.assertNotIn("ILIKE", sql)

    def test_fts_limit_expanded_to_50(self):
        from after_sales_agent.retrieval.search.keyword_search import lexical_fallback
        rows = [(_ROW_TEMPLATE[:18] + (0.35,))]
        fake_psycopg, fts_cursor, _ = _make_fake_psycopg(rows=rows)
        sys.modules["psycopg"] = fake_psycopg
        lexical_fallback(
            psycopg_module=fake_psycopg,
            config=types.SimpleNamespace(dsn="postgresql://unused"),
            query="退款",
            merchant_code="M1",
            limit=10,
            **_common_kwargs(),
        )
        sql = fts_cursor.executions[0][0]
        self.assertIn("LIMIT 50", sql)

    def test_trgm_fallback_triggered_when_fts_below_threshold(self):
        from after_sales_agent.retrieval.search.keyword_search import lexical_fallback
        fts_rows = [
            (1001,) + _ROW_TEMPLATE[1:18] + (0.35,),
            (1002,) + _ROW_TEMPLATE[1:18] + (0.20,),
        ]
        trgm_rows = [(9999,) + _ROW_TEMPLATE[1:18] + (0.40,)]
        fake_psycopg, fts_cursor, trgm_cursor = _make_fake_psycopg(
            rows=fts_rows, trgm_rows=trgm_rows
        )
        sys.modules["psycopg"] = fake_psycopg
        result = lexical_fallback(
            psycopg_module=fake_psycopg,
            config=types.SimpleNamespace(dsn="postgresql://unused"),
            query="退款",
            merchant_code="M1",
            limit=10,
            **_common_kwargs(),
        )
        self.assertEqual(3, len(result))
        chunk_ids = [h["chunk_id"] for h in result]
        self.assertIn(9999, chunk_ids)
        self.assertEqual(1, len(trgm_cursor.executions))
        trgm_sql = trgm_cursor.executions[0][0]
        self.assertIn("similarity", trgm_sql)

    def test_trgm_not_triggered_when_fts_above_threshold(self):
        from after_sales_agent.retrieval.search.keyword_search import lexical_fallback
        fts_rows = [
            (i,) + _ROW_TEMPLATE[1:18] + (float(i) * 0.1,)
            for i in range(1001, 1006)  # 5 hits
        ]
        fake_psycopg, _, _ = _make_fake_psycopg(rows=fts_rows)
        sys.modules["psycopg"] = fake_psycopg
        result = lexical_fallback(
            psycopg_module=fake_psycopg,
            config=types.SimpleNamespace(dsn="postgresql://unused"),
            query="退款",
            merchant_code="M1",
            limit=10,
            **_common_kwargs(),
        )
        self.assertEqual(5, len(result))
        self.assertEqual(1, fake_psycopg._call_count)

    def test_heading_path_boost_applied(self):
        from after_sales_agent.retrieval.search.keyword_search import row_to_hit
        row_with_heading = (
            2001, "after_sales_policy", "p-1", "chunk text", {},
            "Title", ["cat"], ["scene"], ["intent"], "v1",
            [], "M1", ["退款", "退货"], 1, 1,
            datetime(2026, 1, 1), None, 5001, 0.30,
        )
        hit = row_to_hit(row_with_heading, rank=1, channel="keyword", normalized_query="退款")
        self.assertAlmostEqual(0.90, hit["raw_score"], places=4)
        self.assertAlmostEqual(0.90, hit["score"], places=4)

    def test_row_to_hit_contract_compatible(self):
        from after_sales_agent.retrieval.search.keyword_search import row_to_hit
        row = (
            3001, "faq", "faq-1", "some chunk", {},
            "FAQ Title", ["headphone"], ["quality_issue"], ["refund"], "v2",
            [], "M1", ["Refund"], 2, 1,
            datetime(2026, 1, 1), datetime(2027, 1, 1), 5001, 0.55,
        )
        hit = row_to_hit(row, rank=1, channel="keyword")
        required_keys = {
            "id", "chunk_id", "source_type", "source_code", "title",
            "snippet", "score", "raw_score", "rank", "channel",
            "keyword_rank", "keyword_score", "retrieval_channels",
            "citation", "metadata",
        }
        self.assertTrue(required_keys.issubset(hit.keys()),
                        f"Missing keys: {required_keys - set(hit.keys())}")
        self.assertEqual(3001, hit["chunk_id"])
        self.assertEqual("keyword", hit["channel"])
        self.assertEqual(["keyword"], hit["retrieval_channels"])
        self.assertEqual("faq-1", hit["citation"]["source_code"])
        self.assertEqual(5001, hit["citation"]["document_id"])


def _make_fake_psycopg(rows=None, trgm_rows=None):
    fts_cursor = _CapturingCursor(rows=rows or [])
    trgm_cursor = _CapturingCursor(rows=trgm_rows or [])

    class FakePsycopg:
        def connect(self, dsn):
            if not hasattr(FakePsycopg, '_call_count'):
                FakePsycopg._call_count = 0
            FakePsycopg._call_count += 1
            if FakePsycopg._call_count == 1:
                return _FakeConnection(fts_cursor)
            return _FakeConnection(trgm_cursor)

    return FakePsycopg(), fts_cursor, trgm_cursor


_ROW_TEMPLATE = (
    1001, "after_sales_policy", "refund-policy-001",
    "签收后发现商品破损或裂纹，需要提供商品照片和订单信息",
    {}, "退款退货政策",
    ["headphone"], ["quality_issue"], ["refund"], "v2",
    ["policy"], "MERCHANT_DEMO",
    ["退款", "退货"], 3, 1,
    datetime(2026, 1, 1), None, 5001,
)


def _common_kwargs():
    return dict(
        product_category=None, scene=None, intent=None,
        source_type=None, policy_version=None,
    )


class TestTokenizeChunk(unittest.TestCase):

    def test_produces_space_separated_tokens(self):
        from after_sales_agent.retrieval.search.tokenize_ch import tokenize_chunk
        text = "签收后发现商品破损或裂纹"
        result = tokenize_chunk(text)
        tokens = result.split()
        self.assertGreater(len(tokens), 0)
        for token in tokens:
            self.assertIn(token, text)

    def test_empty_and_none(self):
        from after_sales_agent.retrieval.search.tokenize_ch import tokenize_chunk
        self.assertEqual("", tokenize_chunk(""))
        self.assertEqual("", tokenize_chunk(None))  # type: ignore[arg-type]

    def test_english_text(self):
        from after_sales_agent.retrieval.search.tokenize_ch import tokenize_chunk
        result = tokenize_chunk("refund policy")
        self.assertIn("refund", result)
        self.assertIn("policy", result)


def test_hard_filters_never_relax_merchant_revision_or_validity() -> None:
    as_of_time = datetime(2026, 7, 21)
    plans = build_filter_plans(
        FilterContext(
            merchant_code="M1",
            source_type="after_sales_policy",
            policy_version="v2",
            as_of_time=as_of_time,
            product_category="headphone",
            scene="quality_issue",
            intent="refund",
        )
    )

    assert all(plan.merchant_code == "M1" for plan in plans)
    assert all(plan.source_type == "after_sales_policy" for plan in plans)
    assert all(plan.policy_version == "v2" for plan in plans)
    assert all(plan.as_of_time == as_of_time for plan in plans)
    assert all(plan.intent == "refund" for plan in plans)


def test_non_policy_filter_plan_can_relax_intent_but_not_hard_dimensions() -> None:
    as_of_time = datetime(2026, 7, 21, 12, 30)
    plans = build_filter_plans(
        FilterContext(
            merchant_code="M1",
            source_type="faq",
            policy_version=None,
            as_of_time=as_of_time,
            product_category=None,
            scene=None,
            intent="refund",
        )
    )

    intent_relaxed = next(plan for plan in plans if plan.level == "intent_relaxed")
    assert intent_relaxed.intent is None
    assert intent_relaxed.merchant_code == "M1"
    assert intent_relaxed.source_type == "faq"
    assert intent_relaxed.as_of_time == as_of_time
    assert intent_relaxed.trusted_policy_eligible is False


def test_hard_filter_sql_enforces_published_revision_merchant_and_half_open_validity() -> None:
    as_of_time = datetime(2026, 7, 21, 12, 30)
    strict = build_filter_plans(
        FilterContext(
            merchant_code="M1",
            source_type="after_sales_policy",
            policy_version="v2",
            as_of_time=as_of_time,
            product_category="headphone",
            scene="quality_issue",
            intent="refund",
        )
    )[0]

    sql, params = build_hard_filter_sql(strict)

    assert "kd.status = 1" in sql
    assert "COALESCE(kd.metadata ->> 'deleted', 'false') <> 'true'" in sql
    assert "kd.published_revision IS NOT NULL" in sql
    assert "kc.revision = kd.published_revision" in sql
    assert "kd.merchant_code IN (%s, 'GLOBAL')" in sql
    assert "kd.valid_from IS NULL OR kd.valid_from <= %s" in sql
    assert "kd.valid_to IS NULL OR %s < kd.valid_to" in sql
    assert "COALESCE(kc.product_categories, ARRAY[]::text[])" in sql
    assert "COALESCE(kc.scenes, ARRAY[]::text[])" in sql
    assert "COALESCE(kc.intents, ARRAY[]::text[])" in sql
    assert sql.count("%s::text IS NULL") == 5
    assert params.count(as_of_time) == 2


def test_layered_rag_rollout_defaults_are_safe(monkeypatch) -> None:
    for name in (
        "RAG_LAYERED_RETRIEVAL_ENABLED",
        "RERANK_TIMEOUT_SECONDS",
        "RERANK_MAX_RETRIES",
        "RERANK_MAX_CANDIDATES",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(pgvector_retriever, "_read_local_env", lambda: {})
    monkeypatch.setattr(
        "after_sales_agent.providers.reranker_client._read_local_env", lambda: {}
    )

    retrieval = pgvector_retriever.PgVectorConfig.from_env()
    reranker = RerankerConfig.from_env()

    assert retrieval.layered_retrieval_enabled is False
    assert reranker.timeout_seconds == 3.0
    assert reranker.max_retries == 1
    assert reranker.max_candidates == 20


def test_direct_pgvector_config_construction_is_fail_closed() -> None:
    retrieval = pgvector_retriever.PgVectorConfig(dsn="postgresql://unused")

    assert retrieval.layered_retrieval_enabled is False


if __name__ == "__main__":
    unittest.main()
