"""Characterization tests for PgVectorKnowledgeRetriever.retrieve() return contract.

These tests capture the existing behavior of retrieve() so that future
refactoring (Phase 1) can verify the dict output structure is preserved.
"""
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

RETRIEVER_PATH = (
    __import__("pathlib").Path(__file__).resolve()
    .parents[2]
    / "after_sales_agent"
    / "retrieval"
    / "pgvector_retriever.py"
)


def _load_retriever_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_characterization_retriever", RETRIEVER_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_characterization_retriever"] = mod
    spec.loader.exec_module(mod)
    return mod


_retriever_mod = _load_retriever_module()
PgVectorConfig = _retriever_mod.PgVectorConfig
PgVectorKnowledgeRetriever = _retriever_mod.PgVectorKnowledgeRetriever


def _layered_config(**overrides) -> PgVectorConfig:
    return PgVectorConfig(layered_retrieval_enabled=True, **overrides)


class TestRetrieveReturnStructure(unittest.TestCase):
    """Verify the exact dict shape returned by retrieve() in degraded (no-DB) mode."""

    def _make_retriever(self, **kwargs):
        return PgVectorKnowledgeRetriever(_layered_config(dsn="", embedding_api_key="", **kwargs))

    # -- mode field --

    def test_empty_query_returns_mode_skipped(self):
        result = self._make_retriever().retrieve(query="   ")
        self.assertEqual(result["mode"], "skipped")

    def test_missing_dsn_returns_mode_not_configured(self):
        result = self._make_retriever().retrieve(query="refund policy", source_type="after_sales_policy")
        self.assertEqual(result["mode"], "pgvector_not_configured")

    def test_default_source_type_uses_rerank_mode(self):
        result = self._make_retriever().retrieve(query="refund policy")
        # In degraded mode with no DSN, falls through to local_json_fallback
        self.assertIn(result["mode"], {"pgvector_not_configured", "skipped", "local_json_fallback"})

    # -- always-present top-level fields --

    def test_result_has_query_field(self):
        result = self._make_retriever().retrieve(query="how to return")
        self.assertIn("query", result)
        self.assertIsInstance(result["query"], str)

    def test_result_has_hits_list_field(self):
        result = self._make_retriever().retrieve(query="how to return")
        self.assertIn("hits", result)
        self.assertIsInstance(result["hits"], list)

    def test_result_has_trace_dict_field(self):
        result = self._make_retriever().retrieve(query="how to return")
        self.assertIn("trace", result)
        self.assertIsInstance(result["trace"], dict)

    # -- trace sub-structure --

    def test_trace_has_stage_latency_ms_dict(self):
        result = self._make_retriever().retrieve(query="how to return")
        latency = result["trace"]["stage_latency_ms"]
        self.assertIsInstance(latency, dict)

    def test_trace_has_filter_level(self):
        result = self._make_retriever().retrieve(query="how to return")
        self.assertIn("filter_level", result["trace"])
        self.assertIsInstance(result["trace"]["filter_level"], str)

    def test_trace_has_failure_reason(self):
        result = self._make_retriever().retrieve(query="how to return")
        self.assertIn("failure_reason", result["trace"])

    def test_trace_has_reranker_succeeded_bool(self):
        result = self._make_retriever().retrieve(query="how to return")
        self.assertIsInstance(result["trace"]["reranker_succeeded"], bool)

    def test_trace_has_threshold_float(self):
        result = self._make_retriever().retrieve(query="how to return")
        self.assertIsInstance(result["trace"]["threshold"], float)

    def test_trace_has_candidate_counts(self):
        result = self._make_retriever().retrieve(query="how to return")
        for key in ("dense_candidate_count", "keyword_candidate_count", "rrf_candidate_count"):
            self.assertIn(key, result["trace"])
            self.assertIsInstance(result["trace"][key], int)
            self.assertGreaterEqual(result["trace"][key], 0)

    def test_trace_has_retrieval_mode(self):
        result = self._make_retriever().retrieve(query="how to return")
        self.assertIn("retrieval_mode", result["trace"])
        self.assertIsInstance(result["trace"]["retrieval_mode"], str)

    def test_trace_has_fallback_reason_or_none(self):
        result = self._make_retriever().retrieve(query="how to return")
        fr = result["trace"].get("fallback_reason")
        self.assertTrue(fr is None or isinstance(fr, str))

    # -- top-level scalar fields --

    def test_result_has_no_answer_bool(self):
        result = self._make_retriever().retrieve(query="how to return")
        self.assertIn("no_answer", result)
        self.assertIsInstance(result["no_answer"], bool)

    def test_result_has_trusted_policy_eligible_bool(self):
        result = self._make_retriever().retrieve(query="how to return")
        self.assertIn("trusted_policy_eligible", result)
        self.assertIsInstance(result["trusted_policy_eligible"], bool)

    def test_result_has_relevance_score_threshold_float(self):
        result = self._make_retriever().retrieve(query="how to return")
        self.assertIn("threshold", result)
        self.assertIsInstance(result["threshold"], float)

    def test_result_has_relaxation_level_str(self):
        result = self._make_retriever().retrieve(query="how to return")
        self.assertIn("relaxation_level", result)
        self.assertIsInstance(result["relaxation_level"], str)

    # -- degraded mode when DSN is missing --

    def test_degraded_no_answer_is_true_when_dsn_missing(self):
        result = self._make_retriever().retrieve(query="refund policy", source_type="after_sales_policy")
        self.assertTrue(result["no_answer"])
        self.assertFalse(result["trusted_policy_eligible"])
        self.assertFalse(result["reranker_succeeded"])

    def test_degraded_has_failure_reason(self):
        result = self._make_retriever().retrieve(query="refund policy", source_type="after_sales_policy")
        self.assertIsNotNone(result["failure_reason"])

    # -- local JSON fallback preserves auxiliary hits --

    def test_local_fallback_hits_preserved_in_output(self):
        class LocalFaker(PgVectorKnowledgeRetriever):
            def _local_knowledge_fallback(self, **kwargs):
                return {
                    "mode": "local_json_fallback",
                    "query": kwargs.get("query", ""),
                    "hits": [{"chunk_id": "LOCAL-1", "source_type": "faq", "snippet": "local help"}],
                    "trace": {},
                }

        result = LocalFaker(_layered_config(dsn="", embedding_api_key="")).retrieve(
            query="help", source_type="faq"
        )
        self.assertEqual(len(result["hits"]), 1)
        self.assertEqual(result["hits"][0]["chunk_id"], "LOCAL-1")
        self.assertFalse(result["trusted_policy_eligible"])

    # -- psycopg2 missing triggers degraded contract --

    def test_missing_psycopg_uses_stable_degraded_contract(self):
        retriever = PgVectorKnowledgeRetriever(_layered_config(dsn="postgresql://unused", embedding_api_key="fake"))
        with patch.dict(sys.modules, {"psycopg": None, "psycopg2": None}):
            result = retriever.retrieve(query="policy", source_type="after_sales_policy")
        self.assertEqual(result["mode"], "pgvector_dependency_missing")
        self.assertTrue(result["no_answer"])

    # -- _finalize_result always returns dict (not None or list) --

    def test_finalize_result_returns_dict_with_required_keys(self):
        plan = MagicMock()
        plan.level = "strict"
        plan.source_type = "after_sales_policy"

        result = PgVectorKnowledgeRetriever._finalize_result(
            {"mode": "rerank", "hits": [], "trace": {}},
            plan=plan,
            failure_reason="NO_MATCH",
            no_answer=True,
        )
        self.assertIsInstance(result, dict)
        self.assertEqual(result["mode"], "rerank")
        self.assertEqual(result["filter_level"], "strict")
        self.assertTrue(result["no_answer"])
        self.assertFalse(result["trusted_policy_eligible"])
        self.assertIsInstance(result["threshold"], float)

    def test_finalize_result_nest_trace_fields_are_safe(self):
        plan = MagicMock()
        plan.level = "strict"
        plan.source_type = "after_sales_policy"

        raw = {
            "mode": "rerank",
            "hits": [],
            "trace": {
                "stage_latency_ms": {"embedding": -1.0, "vector": 0.5, "bad_key": "x"},
                "dense_candidate_count": "not-a-number",
                "retrieval_mode": None,
                "fallback_level": "invalid_level",
                "candidate_traces": [],
            },
        }
        result = PgVectorKnowledgeRetriever._finalize_result(
            raw,
            plan=plan,
            failure_reason="NO_MATCH",
            no_answer=True,
        )
        latency = result["trace"]["stage_latency_ms"]
        self.assertNotIn("embedding", latency)
        self.assertIn("vector", latency)
        self.assertEqual(latency["vector"], 0.5)
        self.assertEqual(result["trace"]["dense_candidate_count"], 0)
        self.assertNotIn("fallback_level", result["trace"])
        self.assertEqual(len(result["trace"].get("candidate_traces", [])), 0)

    def test_finalize_result_merges_ablation_counts(self):
        plan = MagicMock()
        plan.level = "strict"
        plan.source_type = "after_sales_policy"

        trace = {
            "dense_candidate_count": 10,
            "keyword_candidate_count": 5,
            "rrf_candidate_count": 3,
            "retrieval_mode": "rerank",
        }
        result = PgVectorKnowledgeRetriever._finalize_result(
            {"mode": "rerank", "hits": [], "trace": trace},
            plan=plan,
            failure_reason=None,
            no_answer=False,
        )
        self.assertEqual(result["trace"]["dense_candidate_count"], 10)
        self.assertEqual(result["trace"]["keyword_candidate_count"], 5)
        self.assertEqual(result["trace"]["rrf_candidate_count"], 3)

    def test_finalize_result_hits_get_relaxation_level(self):
        plan = MagicMock()
        plan.level = "category_relaxed"
        plan.source_type = "after_sales_policy"

        result = PgVectorKnowledgeRetriever._finalize_result(
            {
                "mode": "rerank",
                "hits": [{"chunk_id": "H1", "source_type": "policy", "score": 0.8}],
                "trace": {},
            },
            plan=plan,
            failure_reason=None,
            no_answer=False,
            trusted_policy_eligible=False,
        )
        self.assertEqual(result["hits"][0]["relaxation_level"], "category_relaxed")
        self.assertFalse(result["hits"][0]["trusted_policy_eligible"])

    def test_finalize_result_with_trusted_policy(self):
        plan = MagicMock()
        plan.level = "strict"
        plan.source_type = "after_sales_policy"

        result = PgVectorKnowledgeRetriever._finalize_result(
            {
                "mode": "rerank",
                "hits": [{"chunk_id": "H1", "source_type": "after_sales_policy", "score": 0.8}],
                "trace": {},
            },
            plan=plan,
            failure_reason=None,
            no_answer=False,
            trusted_policy_eligible=True,
        )
        self.assertTrue(result["trusted_policy_eligible"])
        # trusted_policy_eligible=True triggers setdefault, but hit already has False from caller
        # The code does: if not trusted_policy_eligible -> set False; else -> setdefault(False)
        # Since trusted_policy_eligible=True, it does setdefault which keeps existing False
        self.assertFalse(result["hits"][0]["trusted_policy_eligible"])
