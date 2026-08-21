"""Vector search strategy — Psycopg + PgVector.

Extracted from PgVectorKnowledgeRetriever._vector_search and _row_to_hit.
"""
from __future__ import annotations

import json
from typing import Any

from after_sales_agent.retrieval.knowledge_filters import FilterPlan, build_hard_filter_sql
from after_sales_agent.retrieval.retrieval_result import annotate_hits_with_filter_contract


def vector_search(
    *,
    psycopg_module: Any,
    config: Any,
    embedding: list[float],
    merchant_code: str | None,
    product_category: str | None,
    scene: str | None,
    intent: str | None,
    source_type: str | None,
    policy_version: str | None,
    as_of_time: Any | None = None,
    filter_plan: FilterPlan | None = None,
    limit: int,
) -> list[dict[str, Any]]:
    """Run a PgVector cosine similarity search."""
    from after_sales_agent.retrieval.knowledge_filters import build_filter_plans, FilterContext

    plan = filter_plan or _build_filter_plan(
        merchant_code=merchant_code,
        product_category=product_category,
        scene=scene,
        intent=intent,
        source_type=source_type,
        policy_version=policy_version,
        as_of_time=as_of_time,
        config=config,
    )
    filter_sql, filter_params = build_hard_filter_sql(plan)
    where_sql = "WHERE " + filter_sql
    params = [_vector_literal(embedding), *filter_params]
    safe_limit = max(1, min(int(limit), 20))
    sql = f"""
        SELECT kc.id, kc.document_type, kd.source_code, kc.chunk_text, kc.metadata,
               kd.title, kc.product_categories, kc.scenes, kc.intents, kd.policy_version,
               kd.tags, kd.merchant_code, kc.heading_path, kc.page_number, kc.revision,
               kd.valid_from, kd.valid_to, kc.document_id,
               1 - (kc.embedding <=> %s::vector) AS score
        FROM knowledge_chunk kc
        JOIN knowledge_document kd ON kd.id = kc.document_id
        {where_sql}
        ORDER BY kc.embedding <=> %s::vector
        LIMIT {safe_limit}
    """
    params.append(_vector_literal(embedding))
    with psycopg_module.connect(config.dsn) as conn:
        with conn.cursor() as cur:
            probes = max(1, min(int(config.ivfflat_probes), 1000))
            cur.execute(f"SET LOCAL ivfflat.probes = {probes}")
            cur.execute(sql, params)
            rows = cur.fetchall()
    hits = [row_to_hit(row, rank=rank, channel="dense") for rank, row in enumerate(rows, start=1)]
    return annotate_hits_with_filter_contract(hits, plan)


def row_to_hit(row: Any, *, rank: int = 1, channel: str = "dense") -> dict[str, Any]:
    """Convert a DB row to a hit dict."""
    metadata = row[4]
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {}
    metadata = {
        **(metadata or {}),
        "title": row[5],
        "product_categories": row[6] or [],
        "scenes": row[7] or [],
        "intents": row[8] or [],
        "product_category": (row[6] or [None])[0],
        "scene": (row[7] or [None])[0],
        "intent": (row[8] or [None])[0],
        "policy_version": row[9],
        "tags": row[10] or [],
        "merchant_code": row[11],
        "source_type": row[1],
        "source_code": str(row[2]),
        "heading_path": row[12] or [],
        "page_number": row[13],
        "revision": row[14],
        "valid_from": _serialize_time(row[15]),
        "valid_to": _serialize_time(row[16]),
        "document_id": row[17],
    }
    citation = {
        "chunk_id": row[0],
        "document_id": row[17],
        "source_type": row[1],
        "source_code": str(row[2]),
        "title": row[5],
        "merchant_code": row[11],
        "heading_path": row[12] or [],
        "page_number": row[13],
        "revision": row[14],
        "policy_version": row[9],
        "valid_from": _serialize_time(row[15]),
        "valid_to": _serialize_time(row[16]),
    }
    raw_score = float(row[18] or 0)
    return {
        "id": row[0],
        "chunk_id": row[0],
        "source_type": row[1],
        "source_code": str(row[2]),
        "title": metadata.get("title") or row[1],
        "snippet": row[3],
        "score": round(raw_score, 4),
        "raw_score": raw_score,
        "rank": rank,
        "channel": channel,
        f"{channel}_rank": rank,
        f"{channel}_score": raw_score,
        "retrieval_channels": [channel],
        "citation": citation,
        "metadata": metadata,
    }


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{item:.8f}" for item in vector) + "]"


def _serialize_time(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


def _build_filter_plan(
    *,
    merchant_code: str | None,
    product_category: str | None,
    scene: str | None,
    intent: str | None,
    source_type: str | None,
    policy_version: str | None,
    as_of_time: Any | None,
    config: Any,
) -> FilterPlan:
    from datetime import datetime
    from after_sales_agent.retrieval.knowledge_filters import build_filter_plans, FilterContext

    def _normalized_merchant_code(mc: str | None) -> str:
        normalized = str(mc or "").strip()
        return normalized or "GLOBAL"

    return build_filter_plans(
        FilterContext(
            merchant_code=_normalized_merchant_code(merchant_code),
            source_type=source_type,
            policy_version=policy_version,
            as_of_time=as_of_time or datetime.utcnow(),
            product_category=product_category,
            scene=scene,
            intent=intent,
        )
    )[0]
