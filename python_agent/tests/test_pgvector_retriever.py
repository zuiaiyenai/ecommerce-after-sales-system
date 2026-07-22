import importlib.util
from datetime import datetime
import os
import pathlib
import sys
import types
import unittest
from unittest.mock import patch

from after_sales_agent.providers.reranker_client import RerankResult


RETRIEVER_PATH = pathlib.Path(__file__).resolve().parents[1] / "after_sales_agent" / "retrieval" / "pgvector_retriever.py"


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
        self.assertIn("similarity(kc.search_text", keyword_sql)
        self.assertIn("array_to_string(kc.heading_path", keyword_sql)

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
        self.assertEqual(0.75, result["threshold"])
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

    def test_dense_only_and_keyword_only_remain_untrusted_after_successful_rerank(self) -> None:
        for dense, keyword in ((True, False), (False, True)):
            with self.subTest(dense=dense, keyword=keyword):
                reranker = _FakeReranker(score=0.99)
                retriever = _PipelineRetriever(reranker=reranker, dense=dense, keyword=keyword)

                result = _retrieve_with_fake_psycopg(retriever, source_type="after_sales_policy")

                self.assertTrue(result["reranker_succeeded"])
                self.assertFalse(result["trusted_policy_eligible"])
                self.assertFalse(result["hits"][0]["trusted_policy_eligible"])

    def test_keyword_only_policy_hit_stays_untrusted_when_other_dense_hit_exists(self) -> None:
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
        self.assertFalse(policy_hit["trusted_policy_eligible"])
        self.assertFalse(result["trusted_policy_eligible"])

    def test_successful_rerank_applies_source_threshold_and_sets_no_answer(self) -> None:
        policy_result = _retrieve_with_fake_psycopg(
            _PipelineRetriever(reranker=_FakeReranker(score=0.74), dense=True, keyword=True),
            source_type="after_sales_policy",
        )
        faq_result = _retrieve_with_fake_psycopg(
            _PipelineRetriever(reranker=_FakeReranker(score=0.61), dense=True, keyword=True),
            source_type="faq",
        )

        self.assertEqual(0.75, policy_result["threshold"])
        self.assertTrue(policy_result["no_answer"])
        self.assertEqual([], policy_result["hits"])
        self.assertEqual(0.6, faq_result["threshold"])
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


if __name__ == "__main__":
    unittest.main()
