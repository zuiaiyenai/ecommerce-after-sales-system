"""Characterization tests for RRF ranking behavior.

These tests capture the exact scoring and ordering semantics of the
reciprocal rank fusion implementation.
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

_RRF_PATH = (
    Path(__file__).resolve().parents[2]
    / "after_sales_agent"
    / "retrieval"
    / "rrf.py"
)


def _load_rrf_module() -> types.ModuleType:
    spec = __import__("importlib.util").util.spec_from_file_location(
        "_characterization_rrf", _RRF_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = __import__("importlib.util").util.module_from_spec(spec)
    sys.modules["_characterization_rrf"] = mod
    spec.loader.exec_module(mod)
    return mod


_mod = _load_rrf_module()
rrf_fuse = _mod.rrf_fuse
rrf_fuse_rankings = _mod.rrf_fuse_rankings


class TestRrfFuse(unittest.TestCase):
    """Characterize rrf_fuse output structure and ordering."""

    def test_basic_two_channel_merge(self):
        dense = [{"chunk_id": "A", "score": 0.9}, {"chunk_id": "B", "score": 0.8}]
        lexical = [{"chunk_id": "B", "score": 0.7}, {"chunk_id": "C", "score": 0.6}]
        result = rrf_fuse(dense, lexical, limit=10)
        # B appears in both channels → highest RRF score → first
        self.assertEqual(result[0]["chunk_id"], "B")
        self.assertEqual(len(result), 3)

    def test_rrf_score_is_rank_based_not_score_based(self):
        """Changing raw scores should not change order — only ranks matter."""
        first = rrf_fuse(
            [{"chunk_id": "X", "score": 0.99}, {"chunk_id": "Y", "score": 0.01}],
            [{"chunk_id": "Y", "score": 100.0}, {"chunk_id": "Z", "score": 99.0}],
            limit=10,
        )
        second = rrf_fuse(
            [{"chunk_id": "X", "score": 0.5}, {"chunk_id": "Y", "score": 0.5}],
            [{"chunk_id": "Y", "score": 50.0}, {"chunk_id": "Z", "score": 50.0}],
            limit=10,
        )
        self.assertEqual(first[0]["chunk_id"], second[0]["chunk_id"])
        self.assertEqual(first[1]["chunk_id"], second[1]["chunk_id"])

    def test_single_channel_input(self):
        dense = [{"chunk_id": "A", "score": 0.5}, {"chunk_id": "B", "score": 0.3}]
        result = rrf_fuse(dense, [], limit=10)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["chunk_id"], "A")
        self.assertEqual(result[1]["chunk_id"], "B")

    def test_empty_inputs(self):
        result = rrf_fuse([], [], limit=10)
        self.assertEqual(result, [])

    def test_limit_truncates_output(self):
        dense = [
            {"chunk_id": f"D{i}", "score": 0.9 - i * 0.01}
            for i in range(10)
        ]
        lexical = [
            {"chunk_id": f"L{i}", "score": 0.9 - i * 0.01}
            for i in range(10)
        ]
        result = rrf_fuse(dense, lexical, limit=3)
        self.assertLessEqual(len(result), 3)

    def test_duplicate_chunk_ids_are_merged(self):
        """Same chunk_id across channels should be merged, not duplicated."""
        dense = [{"chunk_id": "A", "score": 0.9}]
        lexical = [{"chunk_id": "A", "score": 0.7}]
        result = rrf_fuse(dense, lexical, limit=10)
        ids = [h["chunk_id"] for h in result]
        self.assertEqual(ids.count("A"), 1)

    def test_output_hits_have_dense_rank_and_keyword_rank(self):
        dense = [{"chunk_id": "A", "score": 0.9}]
        lexical = [{"chunk_id": "A", "score": 0.8}]
        result = rrf_fuse(dense, lexical, limit=10)
        hit = result[0]
        self.assertIn("dense_rank", hit)
        self.assertIn("keyword_rank", hit)
        self.assertEqual(hit["dense_rank"], 1)
        self.assertEqual(hit["keyword_rank"], 1)

    def test_output_hits_have_dense_score_and_keyword_score(self):
        dense = [{"chunk_id": "A", "score": 0.9}]
        lexical = [{"chunk_id": "A", "score": 0.8}]
        result = rrf_fuse(dense, lexical, limit=10)
        hit = result[0]
        self.assertIn("dense_score", hit)
        self.assertIn("keyword_score", hit)
        self.assertAlmostEqual(hit["dense_score"], 0.9, places=4)
        self.assertAlmostEqual(hit["keyword_score"], 0.8, places=4)

    def test_output_hits_have_retrieval_channels_list(self):
        dense = [{"chunk_id": "A", "score": 0.9}]
        lexical = [{"chunk_id": "B", "score": 0.8}]
        result = rrf_fuse(dense, lexical, limit=10)
        a_hit = next(h for h in result if h["chunk_id"] == "A")
        b_hit = next(h for h in result if h["chunk_id"] == "B")
        self.assertEqual(a_hit["retrieval_channels"], ["dense"])
        self.assertEqual(b_hit["retrieval_channels"], ["keyword"])

    def test_shared_chunk_has_both_channels(self):
        dense = [{"chunk_id": "A", "score": 0.9}]
        lexical = [{"chunk_id": "A", "score": 0.8}]
        result = rrf_fuse(dense, lexical, limit=10)
        hit = result[0]
        self.assertEqual(hit["retrieval_channels"], ["dense", "keyword"])


class TestRrfFuseRankings(unittest.TestCase):
    """Characterize rrf_fuse_rankings (rank-only input path)."""

    def test_rankings_input_only_needs_ranks(self):
        """Provide only ranks, no scores needed."""
        result = rrf_fuse_rankings(
            [[{"chunk_id": "A", "rank": 1}, {"chunk_id": "B", "rank": 2}],
             [{"chunk_id": "B", "rank": 1}, {"chunk_id": "C", "rank": 2}]],
            limit=10,
        )
        self.assertEqual(result[0]["chunk_id"], "B")
        self.assertEqual(len(result), 3)

    def test_rankings_order_same_as_scores(self):
        """Ranks should produce same ordering regardless of original scores."""
        first = rrf_fuse_rankings(
            [[{"chunk_id": "A", "rank": 1}, {"chunk_id": "B", "rank": 2}],
             [{"chunk_id": "B", "rank": 1}, {"chunk_id": "C", "rank": 2}]],
            limit=10,
        )
        second = rrf_fuse_rankings(
            [[{"chunk_id": "A", "rank": 5}, {"chunk_id": "B", "rank": 10}],
             [{"chunk_id": "B", "rank": 3}, {"chunk_id": "C", "rank": 7}]],
            limit=10,
        )
        self.assertEqual(first[0]["chunk_id"], second[0]["chunk_id"])
        self.assertEqual(first[1]["chunk_id"], second[1]["chunk_id"])


if __name__ == "__main__":
    unittest.main()
