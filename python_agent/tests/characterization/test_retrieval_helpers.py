"""Characterization tests for pgvector_retriever internal helpers.

These tests lock down behavior of private/protected methods that will be
extracted into the new retrieval module during Phase 1.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

RETRIEVER_PATH = (
    Path(__file__).resolve().parents[2]
    / "after_sales_agent"
    / "retrieval"
    / "pgvector_retriever.py"
)


def _load_retriever_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_characterization_retriever_helpers", RETRIEVER_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_characterization_retriever_helpers"] = mod
    spec.loader.exec_module(mod)
    return mod


_retriever_mod = _load_retriever_module()
PgVectorConfig = _retriever_mod.PgVectorConfig
PgVectorKnowledgeRetriever = _retriever_mod.PgVectorKnowledgeRetriever


def _make_retriever(**overrides) -> PgVectorKnowledgeRetriever:
    config = PgVectorConfig(
        layered_retrieval_enabled=True,
        dsn="",
        embedding_api_key="",
        **overrides
    )
    return PgVectorKnowledgeRetriever(config)


class TestRowToHit(unittest.TestCase):
    """Characterize _row_to_hit conversion from DB row to hit dict."""

    def _make_row(
        self,
        chunk_id="c1",
        source_type="after_sales_policy",
        source_code="POL-001",
        snippet="help text",
        metadata_json=None,
        title="Policy Title",
        product_categories=None,
        scenes=None,
        intents=None,
        policy_version="v1",
        tags=None,
        merchant_code="M001",
        heading_path=None,
        page_number=None,
        revision=None,
        valid_from=None,
        valid_to=None,
        document_id="doc-1",
        similarity=0.85,
    ):
        return (
            chunk_id, source_type, source_code, snippet,
            metadata_json or "{}",
            title,
            product_categories or [],
            scenes or [],
            intents or [],
            policy_version,
            tags or [],
            merchant_code,
            heading_path or [],
            page_number,
            revision,
            valid_from,
            valid_to,
            document_id,
            similarity,
        )

    def test_basic_row_conversion(self):
        row = self._make_row()
        hit = PgVectorKnowledgeRetriever._row_to_hit(row, rank=1, channel="dense")
        self.assertEqual(hit["id"], "c1")
        self.assertEqual(hit["chunk_id"], "c1")
        self.assertEqual(hit["source_type"], "after_sales_policy")
        self.assertEqual(hit["source_code"], "POL-001")
        self.assertEqual(hit["title"], "Policy Title")
        self.assertEqual(hit["snippet"], "help text")
        self.assertEqual(hit["channel"], "dense")
        self.assertEqual(hit["rank"], 1)
        self.assertEqual(hit["dense_rank"], 1)
        self.assertAlmostEqual(hit["dense_score"], 0.85, places=4)
        self.assertAlmostEqual(hit["score"], 0.85, places=4)
        self.assertEqual(hit["retrieval_channels"], ["dense"])

    def test_metadata_string_is_parsed(self):
        row = self._make_row(
            metadata_json=json.dumps({"extra": "field", "nested": {"a": 1}})
        )
        hit = PgVectorKnowledgeRetriever._row_to_hit(row)
        self.assertEqual(hit["metadata"]["extra"], "field")
        self.assertEqual(hit["metadata"]["nested"], {"a": 1})

    def test_metadata_from_row_fields_overrides_parsed(self):
        """Row fields (title, product_categories, etc.) override parsed metadata."""
        row = self._make_row(
            metadata_json=json.dumps({"title": "meta-title", "product_categories": ["meta-cat"]}),
            title="row-title",
            product_categories=["row-cat"],
        )
        hit = PgVectorKnowledgeRetriever._row_to_hit(row)
        self.assertEqual(hit["metadata"]["title"], "row-title")
        self.assertEqual(hit["metadata"]["product_categories"], ["row-cat"])

    def test_keyword_channel_fields(self):
        row = self._make_row()
        hit = PgVectorKnowledgeRetriever._row_to_hit(row, rank=3, channel="keyword")
        self.assertEqual(hit["channel"], "keyword")
        self.assertEqual(hit["keyword_rank"], 3)
        # dense_rank is only set when channel == "dense"
        self.assertNotIn("dense_rank", hit)

    def test_citation_contains_required_fields(self):
        row = self._make_row()
        hit = PgVectorKnowledgeRetriever._row_to_hit(row)
        citation = hit["citation"]
        self.assertEqual(citation["chunk_id"], "c1")
        self.assertEqual(citation["document_id"], "doc-1")
        self.assertEqual(citation["source_type"], "after_sales_policy")
        self.assertEqual(citation["source_code"], "POL-001")
        self.assertEqual(citation["title"], "Policy Title")
        self.assertEqual(citation["merchant_code"], "M001")

    def test_valid_time_serialization(self):
        row = self._make_row(
            valid_from=datetime(2025, 1, 1),
            valid_to=datetime(2026, 1, 1),
        )
        hit = PgVectorKnowledgeRetriever._row_to_hit(row)
        self.assertEqual(hit["metadata"]["valid_from"], "2025-01-01T00:00:00")
        self.assertEqual(hit["metadata"]["valid_to"], "2026-01-01T00:00:00")
        self.assertEqual(hit["citation"]["valid_from"], "2025-01-01T00:00:00")
        self.assertEqual(hit["citation"]["valid_to"], "2026-01-01T00:00:00")

    def test_invalid_metadata_fallback_to_empty_dict(self):
        row = self._make_row(metadata_json="not json{{{")
        hit = PgVectorKnowledgeRetriever._row_to_hit(row)
        # metadata is never truly empty — row fields always override
        self.assertEqual(hit["metadata"]["title"], "Policy Title")
        self.assertEqual(hit["metadata"]["source_type"], "after_sales_policy")

    def test_null_score_treated_as_zero(self):
        row = self._make_row(similarity=None)
        hit = PgVectorKnowledgeRetriever._row_to_hit(row)
        self.assertEqual(hit["score"], 0.0)
        self.assertEqual(hit["raw_score"], 0.0)

    def test_product_categories_extracts_first_category(self):
        row = self._make_row(product_categories=["electronics", "phones"])
        hit = PgVectorKnowledgeRetriever._row_to_hit(row)
        self.assertEqual(hit["metadata"]["product_category"], "electronics")

    def test_scenes_extracts_first_scene(self):
        row = self._make_row(scenes=["returns", "refunds"])
        hit = PgVectorKnowledgeRetriever._row_to_hit(row)
        self.assertEqual(hit["metadata"]["scene"], "returns")

    def test_intents_extracts_first_intent(self):
        row = self._make_row(intents=["complaint", "inquiry"])
        hit = PgVectorKnowledgeRetriever._row_to_hit(row)
        self.assertEqual(hit["metadata"]["intent"], "complaint")


class TestMergeAndRerankHits(unittest.TestCase):
    """Characterize _merge_and_rerank_hits (delegates to rrf_fuse)."""

    def test_delegates_to_rrf_with_limit(self):
        retriever = _make_retriever()
        vector_hits = [{"chunk_id": "A", "score": 0.9, "dense_rank": 1}]
        keyword_hits = [{"chunk_id": "A", "score": 0.7, "keyword_rank": 1}]
        result = retriever._merge_and_rerank_hits(vector_hits, keyword_hits, query="test", limit=5)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["chunk_id"], "A")
        self.assertEqual(result[0]["retrieval_channels"], ["dense", "keyword"])


class TestSafetyHelpers(unittest.TestCase):
    """Characterize static safety helpers used by _finalize_result."""

    def test_safe_trace_count_valid_int(self):
        self.assertEqual(PgVectorKnowledgeRetriever._safe_trace_count(42), 42)

    def test_safe_trace_count_none(self):
        self.assertEqual(PgVectorKnowledgeRetriever._safe_trace_count(None), 0)

    def test_safe_trace_count_string_number(self):
        self.assertEqual(PgVectorKnowledgeRetriever._safe_trace_count("10"), 10)

    def test_safe_trace_count_negative_becomes_zero(self):
        self.assertEqual(PgVectorKnowledgeRetriever._safe_trace_count(-5), 0)

    def test_safe_trace_count_invalid_string(self):
        self.assertEqual(PgVectorKnowledgeRetriever._safe_trace_count("abc"), 0)

    def test_safe_trace_name_valid(self):
        self.assertEqual(PgVectorKnowledgeRetriever._safe_trace_name("rerank", "default"), "rerank")

    def test_safe_trace_name_empty_string(self):
        self.assertEqual(PgVectorKnowledgeRetriever._safe_trace_name("", "default"), "default")

    def test_safe_trace_name_none(self):
        self.assertEqual(PgVectorKnowledgeRetriever._safe_trace_name(None, "default"), "default")

    def test_safe_trace_name_too_long(self):
        long_name = "a" * 100
        self.assertEqual(PgVectorKnowledgeRetriever._safe_trace_name(long_name, "default"), "default")

    def test_safe_trace_name_special_chars(self):
        self.assertEqual(
            PgVectorKnowledgeRetriever._safe_trace_name("retrieval_mode!", "default"),
            "default",
        )

    def test_safe_trace_name_alphanumeric_underscore_only(self):
        self.assertEqual(
            PgVectorKnowledgeRetriever._safe_trace_name("rerank_mode_2", "default"),
            "rerank_mode_2",
        )


class TestThresholdForSource(unittest.TestCase):
    """Characterize threshold lookup by source_type."""

    def test_after_sales_policy_threshold(self):
        threshold = PgVectorKnowledgeRetriever._threshold_for_source("after_sales_policy")
        self.assertEqual(threshold, 0.35)

    def test_refund_policy_threshold(self):
        threshold = PgVectorKnowledgeRetriever._threshold_for_source("refund_policy")
        self.assertEqual(threshold, 0.35)

    def test_exchange_rule_threshold(self):
        threshold = PgVectorKnowledgeRetriever._threshold_for_source("exchange_rule")
        self.assertEqual(threshold, 0.35)

    def test_evidence_requirement_threshold(self):
        threshold = PgVectorKnowledgeRetriever._threshold_for_source("evidence_requirement")
        self.assertEqual(threshold, 0.45)

    def test_faq_threshold(self):
        threshold = PgVectorKnowledgeRetriever._threshold_for_source("faq")
        self.assertEqual(threshold, 0.40)

    def test_unknown_source_type_returns_default(self):
        # Unknown source types should return the first threshold or a default
        threshold = PgVectorKnowledgeRetriever._threshold_for_source("unknown_type")
        self.assertIsInstance(threshold, float)
        self.assertGreaterEqual(threshold, 0.0)


class TestHitSourceType(unittest.TestCase):
    """Characterize _hit_source_type helper."""

    def test_from_hit_dict_with_source_type(self):
        retriever = _make_retriever()
        source = retriever._hit_source_type({"source_type": "after_sales_policy"})
        self.assertEqual(source, "after_sales_policy")

    def test_from_hit_dict_missing_source_type(self):
        retriever = _make_retriever()
        source = retriever._hit_source_type({})
        self.assertEqual(source, "")

    def test_from_hit_dict_with_id(self):
        retriever = _make_retriever()
        # _hit_source_type only looks at source_type and metadata.source_type, not id
        source = retriever._hit_source_type({"id": "POL-001"})
        self.assertEqual(source, "")


if __name__ == "__main__":
    unittest.main()
