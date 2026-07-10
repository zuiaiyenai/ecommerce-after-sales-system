import importlib.util
import os
import pathlib
import sys
import types
import unittest


RETRIEVER_PATH = pathlib.Path(__file__).resolve().parents[1] / "after_sales_agent" / "services" / "pgvector_retrieval.py"


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
    def test_chinese_digital_category_matches_seeded_db_aliases(self) -> None:
        aliases = PgVectorKnowledgeRetriever._product_category_aliases("数码")

        self.assertIn("digital", aliases)
        self.assertIn("headphone", aliases)
        self.assertIn("phone", aliases)

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
            [("不存在的前端品类", "不存在的场景"), (None, None)],
            retriever.vector_calls,
        )
        self.assertEqual("耳机外壳破裂退款规则", result["hits"][0]["title"])


if __name__ == "__main__":
    unittest.main()
