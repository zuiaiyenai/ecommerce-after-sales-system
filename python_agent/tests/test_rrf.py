from __future__ import annotations

from after_sales_agent.retrieval.rrf import rrf_fuse


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
