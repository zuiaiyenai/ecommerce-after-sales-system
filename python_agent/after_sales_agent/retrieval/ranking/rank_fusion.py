"""RRF (Reciprocal Rank Fusion) ranking.

Wrapper around the existing rrf.py functions for the new architecture.
"""
from __future__ import annotations

from typing import Any

from after_sales_agent.retrieval.rrf import rrf_fuse, rrf_fuse_rankings


def fuse_rankings(
    vector_hits: list[dict[str, Any]],
    keyword_hits: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    """Fuse vector and keyword hits via RRF.

    Compatibility wrapper around rrf_fuse().
    """
    return rrf_fuse(vector_hits, keyword_hits, limit)


def fuse_rankings_v2(
    rankings: list[list[dict[str, Any]]],
    *,
    k: int = 60,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Multi-query RRF fusion.

    Compatibility wrapper around rrf_fuse_rankings().
    """
    return rrf_fuse_rankings(rankings, k=k, limit=limit)
