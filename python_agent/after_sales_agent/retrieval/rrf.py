from __future__ import annotations

from typing import Any


def rrf_fuse(
    dense_hits: list[dict[str, Any]],
    keyword_hits: list[dict[str, Any]],
    *,
    k: int = 60,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Fuse channel rankings without comparing their incompatible raw scores."""
    if k < 0:
        raise ValueError("k must be non-negative")
    if limit <= 0:
        return []

    merged: dict[str, dict[str, Any]] = {}
    for channel, hits in (("dense", dense_hits), ("keyword", keyword_hits)):
        seen_chunk_ids: set[str] = set()
        rank = 0
        for hit in hits:
            raw_chunk_id = hit.get("chunk_id", hit.get("id"))
            if raw_chunk_id is None:
                raise ValueError(f"{channel} hit is missing chunk_id")
            chunk_id = str(raw_chunk_id)
            if chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(chunk_id)
            rank += 1
            item = merged.setdefault(
                chunk_id,
                {
                    **hit,
                    "chunk_id": raw_chunk_id,
                    "rrf_score": 0.0,
                    "retrieval_channels": [],
                },
            )
            item["rrf_score"] += 1.0 / (k + rank)
            item[f"{channel}_rank"] = rank
            item[f"{channel}_score"] = hit.get("raw_score", hit.get("score"))
            item["retrieval_channels"].append(channel)

    ranked = sorted(merged.values(), key=lambda item: (-item["rrf_score"], str(item["chunk_id"])))[:limit]
    for rank, item in enumerate(ranked, start=1):
        item["rank"] = rank
    return ranked
