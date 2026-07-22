import importlib.util
from datetime import datetime
import os
import pathlib
import sys
import types
import unittest


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


class PgVectorRetrievalTest(unittest.TestCase):
    def test_query_embedding_cache_reuses_vector_until_ttl_expiry(self) -> None:
        class CachedEmbeddingRetriever(PgVectorKnowledgeRetriever):
            def __init__(self) -> None:
                super().__init__(
                    PgVectorConfig(
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
        retriever = PgVectorKnowledgeRetriever(PgVectorConfig(dsn="postgresql://unused", embedding_api_key="fake"))

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
            retriever = PgVectorKnowledgeRetriever(PgVectorConfig(dsn="postgresql://unused", embedding_api_key="fake"))
            result = retriever._lexical_fallback(query="退款规则", merchant_code="MERCHANT_DEMO")
        finally:
            if old_psycopg is None:
                sys.modules.pop("psycopg", None)
            else:
                sys.modules["psycopg"] = old_psycopg

        self.assertEqual([], result["hits"])
        search_sql, search_params = cursor.executions[0]
        self.assertIn("kd.merchant_code IN (%s, 'GLOBAL')", search_sql)
        self.assertIn("COALESCE(kd.metadata ->> 'deleted', 'false') <> 'true'", search_sql)
        self.assertIn("MERCHANT_DEMO", search_params)

    def test_dense_and_keyword_share_published_revision_merchant_and_validity_filters(self) -> None:
        as_of_time = datetime(2026, 7, 21, 12, 30)
        dense_cursor = _CapturingCursor()
        retriever = PgVectorKnowledgeRetriever(PgVectorConfig(dsn="postgresql://unused", embedding_api_key="fake"))
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
        retriever = PgVectorKnowledgeRetriever(PgVectorConfig(dsn="postgresql://unused", embedding_api_key="fake"))
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
        self.assertEqual(1, keyword[0]["keyword_rank"])
        self.assertEqual(["keyword"], keyword[0]["retrieval_channels"])
        self.assertEqual(dense[0]["citation"], keyword[0]["citation"])

    def test_local_fallback_uses_scene_aliases_for_damage(self) -> None:
        retriever = PgVectorKnowledgeRetriever(PgVectorConfig(dsn="", embedding_api_key=""))

        result = retriever._local_knowledge_fallback(
            query="耳机外壳破裂 破损照片 售后证据",
            merchant_code="MERCHANT_DEMO",
            product_category="数码",
            scene="damage",
            top_k=5,
        )

        titles = [hit["title"] for hit in result["hits"]]
        self.assertIn("商品破损", titles)

    def test_local_fallback_finds_repo_knowledge_when_cwd_is_python_agent(self) -> None:
        retriever = PgVectorKnowledgeRetriever(PgVectorConfig(dsn="", embedding_api_key=""))
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
                super().__init__(PgVectorConfig(dsn="postgresql://unused", embedding_api_key="fake"))
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

        self.assertEqual("pgvector_relaxed_filters", result["mode"])
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
        self.assertEqual("耳机外壳破裂退款规则", result["hits"][0]["title"])

    def test_retrieve_preserves_scene_before_global_relaxation(self) -> None:
        class SceneFirstRetriever(PgVectorKnowledgeRetriever):
            def __init__(self) -> None:
                super().__init__(PgVectorConfig(dsn="postgresql://unused", embedding_api_key="fake"))
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

        self.assertEqual("pgvector_relaxed_filters", result["mode"])
        self.assertEqual("category_relaxed", result["trace"]["fallback_level"])
        self.assertEqual([("服装", "quality_issue"), (None, "quality_issue")], retriever.vector_calls)


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
