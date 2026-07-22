from __future__ import annotations

from dataclasses import dataclass
from collections import OrderedDict
from datetime import datetime
import json
import os
from pathlib import Path
import logging
import time
import socket
import threading
import urllib.error
import urllib.request
from typing import Any

from after_sales_agent.retrieval.knowledge_filters import (
    POLICY_SOURCE_TYPES,
    FilterContext,
    FilterPlan,
    build_filter_plans,
    build_hard_filter_sql,
)
from after_sales_agent.retrieval.rrf import rrf_fuse

logger = logging.getLogger("after_sales_agent.rag")


@dataclass(frozen=True)
class PgVectorConfig:
    dsn: str
    dimensions: int = 1024
    top_k: int = 5
    embedding_model: str = "text-embedding-v3"
    embedding_api_key: str = ""
    embedding_provider: str = "dashscope"
    embedding_base_url: str = "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"
    embedding_timeout_seconds: int = 120
    embedding_max_retries: int = 3
    ivfflat_probes: int = 10
    embedding_cache_ttl_seconds: int = 300
    embedding_cache_max_entries: int = 256

    @classmethod
    def from_env(cls) -> "PgVectorConfig":
        file_values = _read_local_env()
        return cls(
            dsn=os.getenv("PGVECTOR_DSN") or file_values.get("PGVECTOR_DSN", ""),
            dimensions=int(os.getenv("PGVECTOR_DIMENSIONS") or file_values.get("PGVECTOR_DIMENSIONS", "1024")),
            top_k=int(os.getenv("PGVECTOR_TOP_K") or file_values.get("PGVECTOR_TOP_K", "5")),
            embedding_model=os.getenv("EMBEDDING_MODEL") or file_values.get("EMBEDDING_MODEL", "text-embedding-v3"),
            embedding_provider=os.getenv("EMBEDDING_PROVIDER") or file_values.get("EMBEDDING_PROVIDER", "dashscope"),
            embedding_api_key=(
                os.getenv("DASHSCOPE_API_KEY")
                or os.getenv("BAILIAN_API_KEY")
                or file_values.get("DASHSCOPE_API_KEY")
                or file_values.get("BAILIAN_API_KEY")
                or ""
            ),
            embedding_base_url=(
                os.getenv("EMBEDDING_BASE_URL")
                or file_values.get(
                    "EMBEDDING_BASE_URL",
                    "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding",
                )
            ),
            embedding_timeout_seconds=int(
                os.getenv("EMBEDDING_TIMEOUT_SECONDS") or file_values.get("EMBEDDING_TIMEOUT_SECONDS", "120")
            ),
            embedding_max_retries=int(
                os.getenv("EMBEDDING_MAX_RETRIES") or file_values.get("EMBEDDING_MAX_RETRIES", "3")
            ),
            ivfflat_probes=int(
                os.getenv("PGVECTOR_IVFFLAT_PROBES") or file_values.get("PGVECTOR_IVFFLAT_PROBES", "10")
            ),
            embedding_cache_ttl_seconds=int(
                os.getenv("EMBEDDING_CACHE_TTL_SECONDS") or file_values.get("EMBEDDING_CACHE_TTL_SECONDS", "300")
            ),
            embedding_cache_max_entries=int(
                os.getenv("EMBEDDING_CACHE_MAX_ENTRIES") or file_values.get("EMBEDDING_CACHE_MAX_ENTRIES", "256")
            ),
        )


def _read_local_env() -> dict[str, str]:
    repo_root = Path(__file__).resolve().parents[3]
    candidates = [
        Path.cwd() / "python_agent" / ".env",
        Path.cwd() / ".env",
        repo_root / "python_agent" / ".env",
    ]
    values: dict[str, str] = {}
    logger.debug("_read_local_env cwd=%s", Path.cwd())
    for path in candidates:
        logger.debug("_read_local_env try: %s (exists=%s)", path, path.exists())
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
        logger.debug("_read_local_env loaded from: %s", path)
        break
    return values


class PgVectorKnowledgeRetriever:
    """Primary Python-side RAG retriever.

    Retrieval and ingestion must use the same Bailian/DashScope embedding model.
    When the embedding service is unavailable or vector recall is empty, keyword
    fallback still reads the PostgreSQL knowledge base instead of returning to
    legacy MySQL/JSON retrieval.
    """

    def __init__(self, config: PgVectorConfig | None = None) -> None:
        self.config = config or PgVectorConfig.from_env()
        self._embedding_cache: OrderedDict[str, tuple[float, list[float]]] = OrderedDict()
        self._embedding_cache_lock = threading.Lock()

    def retrieve(
        self,
        *,
        query: str,
        merchant_code: str | None = None,
        product_category: str | None = None,
        scene: str | None = None,
        intent: str | None = None,
        source_type: str | None = None,
        policy_version: str | None = None,
        as_of_time: datetime | None = None,
        top_k: int | None = None,
    ) -> dict[str, Any]:
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return {"mode": "skipped", "hits": [], "query": normalized_query}
        resolved_as_of_time = as_of_time or datetime.now()
        filter_plans = build_filter_plans(
            FilterContext(
                merchant_code=self._normalized_merchant_code(merchant_code),
                source_type=source_type,
                policy_version=policy_version,
                as_of_time=resolved_as_of_time,
                product_category=product_category,
                scene=scene,
                intent=intent,
            )
        )
        strict_plan = filter_plans[0]
        logger.info(
            "rag retrieve start query=%s merchant=%s category=%s scene=%s intent=%s dsn=%s",
            normalized_query[:160],
            merchant_code,
            product_category,
            scene,
            intent,
            "SET" if self.config.dsn else "EMPTY",
        )
        if not self.config.dsn and source_type not in POLICY_SOURCE_TYPES:
            local = self._local_knowledge_fallback(
                query=normalized_query,
                merchant_code=merchant_code,
                product_category=product_category,
                scene=scene,
                intent=intent,
                source_type=source_type,
                policy_version=policy_version,
                top_k=top_k,
            )
            if local["hits"]:
                local["mode"] = "local_json_fallback"
                local["trace"]["reason"] = "PGVECTOR_DSN is empty"
                logger.warning("rag pgvector dsn missing, fallback to local json hits=%s", len(local["hits"]))
                return self._apply_filter_contract(local, strict_plan)
        if not self.config.dsn:
            logger.warning("rag pgvector dsn missing and local json fallback has no hits")
            return {
                "mode": "pgvector_not_configured",
                "hits": [],
                "query": normalized_query,
                "trace": {"reason": "PGVECTOR_DSN is empty"},
            }

        try:
            import psycopg  # type: ignore
        except Exception as exc:
            return {
                "mode": "pgvector_dependency_missing",
                "hits": [],
                "query": normalized_query,
                "trace": {"error": exc.__class__.__name__},
            }

        try:
            embedding, embedding_cache_hit = self._get_query_embedding(normalized_query)
        except Exception as exc:
            local = (
                self._local_knowledge_fallback(
                    query=normalized_query,
                    merchant_code=merchant_code,
                    product_category=product_category,
                    scene=scene,
                    intent=intent,
                    source_type=source_type,
                    policy_version=policy_version,
                    top_k=top_k,
                )
                if source_type not in POLICY_SOURCE_TYPES
                else {"hits": [], "trace": {}}
            )
            lexical = self._lexical_fallback(
                query=normalized_query,
                merchant_code=merchant_code,
                product_category=product_category,
                scene=scene,
                intent=intent,
                source_type=source_type,
                policy_version=policy_version,
                as_of_time=resolved_as_of_time,
                top_k=top_k,
            )
            lexical = self._apply_filter_contract(lexical, strict_plan)
            error_info = self._embedding_error_info(exc)
            logger.error("rag embedding failed mode=%s detail=%s", error_info.get("type"), error_info)
            if local["hits"]:
                local["mode"] = "local_json_fallback_after_embedding_error"
                local["trace"]["embedding_error"] = error_info
                logger.warning("rag fallback to local json after embedding error hits=%s", len(local["hits"]))
                return self._apply_filter_contract(local, strict_plan)
            if lexical["hits"]:
                lexical["mode"] = "lexical_fallback_after_embedding_error"
                lexical["trace"]["embedding_error"] = error_info
                logger.warning("rag fallback to lexical after embedding error hits=%s", len(lexical["hits"]))
                return lexical
            return {
                "mode": "embedding_error",
                "hits": [],
                "query": normalized_query,
                "trace": error_info,
            }
        metadata_filters = {
            "merchant_code": merchant_code,
            "product_category": product_category,
            "scene": scene,
            "intent": intent,
            "source_type": source_type,
            "policy_version": policy_version,
            "as_of_time": resolved_as_of_time.isoformat(),
        }
        limit = max(1, min(int(top_k or self.config.top_k), 10))
        candidate_limit = 20
        vector_started_at = time.perf_counter()
        try:
            hits = self._vector_search(
                psycopg_module=psycopg,
                embedding=embedding,
                merchant_code=merchant_code,
                product_category=product_category,
                scene=scene,
                intent=intent,
                source_type=source_type,
                policy_version=policy_version,
                as_of_time=resolved_as_of_time,
                filter_plan=strict_plan,
                limit=candidate_limit,
            )
        except Exception as exc:
            return {
                "mode": "pgvector_error",
                "hits": [],
                "query": normalized_query,
                "trace": {"error": exc.__class__.__name__, "message": str(exc)},
            }
        vector_latency_ms = round((time.perf_counter() - vector_started_at) * 1000, 2)
        lexical = self._lexical_fallback(
            query=normalized_query,
            merchant_code=merchant_code,
            product_category=product_category,
            scene=scene,
            intent=intent,
            source_type=source_type,
            policy_version=policy_version,
            as_of_time=resolved_as_of_time,
            filter_plan=strict_plan,
            top_k=candidate_limit,
        )
        hits = self._annotate_hits_with_filter_contract(hits, strict_plan)
        lexical = self._apply_filter_contract(lexical, strict_plan)
        if hits:
            hits = self._merge_and_rerank_hits(hits, lexical.get("hits") or [], normalized_query, limit)
        else:
            if lexical["hits"]:
                lexical["mode"] = "lexical_fallback_after_empty_vector"
                lexical["trace"]["vector_filters"] = metadata_filters
                logger.warning("rag vector returned empty, fallback to lexical hits=%s", len(lexical["hits"]))
                return lexical
            relaxed = self._relaxed_retrieve_after_empty_vector(
                psycopg_module=psycopg,
                embedding=embedding,
                query=normalized_query,
                merchant_code=merchant_code,
                intent=intent,
                source_type=source_type,
                policy_version=policy_version,
                limit=limit,
                strict_filters=metadata_filters,
                top_k=top_k,
                embedding_cache_hit=embedding_cache_hit,
                as_of_time=resolved_as_of_time,
            )
            if relaxed["hits"]:
                return relaxed
        logger.info("rag retrieve success mode=pgvector hits=%s", len(hits))
        return self._apply_filter_contract({
            "mode": "pgvector",
            "query": normalized_query,
            "hits": hits,
            "trace": {
                "filters": metadata_filters,
                "top_k": limit,
                "ivfflat_probes": self.config.ivfflat_probes,
                "vector_latency_ms": vector_latency_ms,
                "embedding_cache_hit": embedding_cache_hit,
            },
        }, strict_plan)

    def _relaxed_retrieve_after_empty_vector(
        self,
        *,
        psycopg_module: Any,
        embedding: list[float],
        query: str,
        merchant_code: str | None,
        intent: str | None,
        source_type: str | None,
        policy_version: str | None,
        limit: int,
        strict_filters: dict[str, Any],
        top_k: int | None,
        embedding_cache_hit: bool,
        as_of_time: datetime,
    ) -> dict[str, Any]:
        plans = build_filter_plans(
            FilterContext(
                merchant_code=self._normalized_merchant_code(merchant_code),
                source_type=source_type,
                policy_version=policy_version,
                as_of_time=as_of_time,
                product_category=strict_filters.get("product_category"),
                scene=strict_filters.get("scene"),
                intent=intent,
            )
        )[1:]

        attempts: list[dict[str, Any]] = []
        for plan in plans:
            relaxed_filters = {
                "merchant_code": plan.merchant_code,
                "product_category": plan.product_category,
                "scene": plan.scene,
                "intent": plan.intent,
                "source_type": plan.source_type,
                "policy_version": plan.policy_version,
                "as_of_time": plan.as_of_time.isoformat(),
            }
            logger.warning(
                "rag strict filters empty, retry fallback_level=%s strict=%s relaxed=%s",
                plan.level,
                strict_filters,
                relaxed_filters,
            )
            vector_started_at = time.perf_counter()
            vector_hits = self._vector_search(
                psycopg_module=psycopg_module,
                embedding=embedding,
                merchant_code=plan.merchant_code,
                product_category=plan.product_category,
                scene=plan.scene,
                intent=plan.intent,
                source_type=plan.source_type,
                policy_version=plan.policy_version,
                as_of_time=plan.as_of_time,
                filter_plan=plan,
                limit=20,
            )
            vector_hits = self._annotate_hits_with_filter_contract(vector_hits, plan)
            vector_latency_ms = round((time.perf_counter() - vector_started_at) * 1000, 2)
            lexical = self._lexical_fallback(
                query=query,
                merchant_code=plan.merchant_code,
                product_category=plan.product_category,
                scene=plan.scene,
                intent=plan.intent,
                source_type=plan.source_type,
                policy_version=plan.policy_version,
                as_of_time=plan.as_of_time,
                filter_plan=plan,
                top_k=20,
            )
            lexical = self._apply_filter_contract(lexical, plan)
            attempts.append(
                {
                    "level": plan.level,
                    "filters": relaxed_filters,
                    "vector_latency_ms": vector_latency_ms,
                    "vector_hit_count": len(vector_hits),
                    "lexical_hit_count": len(lexical.get("hits") or []),
                }
            )
            trace = {
                "strict_filters": strict_filters,
                "filters": relaxed_filters,
                "fallback_level": plan.level,
                "fallback_attempts": attempts,
                "top_k": limit,
                "embedding_cache_hit": embedding_cache_hit,
                "vector_latency_ms": vector_latency_ms,
            }
            if vector_hits:
                hits = self._merge_and_rerank_hits(vector_hits, lexical.get("hits") or [], query, limit)
                logger.warning("rag fallback vector hit level=%s hits=%s", plan.level, len(hits))
                return self._apply_filter_contract(
                    {"mode": "pgvector_relaxed_filters", "query": query, "hits": hits, "trace": trace},
                    plan,
                )
            if lexical["hits"]:
                lexical["mode"] = "lexical_fallback_after_relaxed_filters"
                lexical["trace"].update(trace)
                logger.warning("rag fallback lexical hit level=%s hits=%s", plan.level, len(lexical["hits"]))
                return self._apply_filter_contract(lexical, plan)
        exhausted_plan = plans[-1] if plans else build_filter_plans(
            FilterContext(
                merchant_code=self._normalized_merchant_code(merchant_code),
                source_type=source_type,
                policy_version=policy_version,
                as_of_time=as_of_time,
                product_category=strict_filters.get("product_category"),
                scene=strict_filters.get("scene"),
                intent=intent,
            )
        )[0]
        return self._apply_filter_contract({
            "mode": "pgvector_relaxed_filters",
            "query": query,
            "hits": [],
            "trace": {
                "strict_filters": strict_filters,
                "filters": strict_filters,
                "fallback_attempts": attempts,
                "top_k": limit,
                "embedding_cache_hit": embedding_cache_hit,
            },
        }, exhausted_plan)

    @staticmethod
    def _normalized_merchant_code(merchant_code: str | None) -> str:
        normalized = str(merchant_code or "").strip()
        return normalized or "GLOBAL"

    def _strict_filter_plan(
        self,
        *,
        merchant_code: str | None,
        product_category: str | None,
        scene: str | None,
        intent: str | None,
        source_type: str | None,
        policy_version: str | None,
        as_of_time: datetime | None,
    ) -> FilterPlan:
        return build_filter_plans(
            FilterContext(
                merchant_code=self._normalized_merchant_code(merchant_code),
                source_type=source_type,
                policy_version=policy_version,
                as_of_time=as_of_time or datetime.now(),
                product_category=product_category,
                scene=scene,
                intent=intent,
            )
        )[0]

    @staticmethod
    def _serialize_time(value: Any) -> str | None:
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return str(value.isoformat())
        return str(value)

    @staticmethod
    def _annotate_hits_with_filter_contract(
        hits: list[dict[str, Any]],
        plan: FilterPlan,
    ) -> list[dict[str, Any]]:
        for hit in hits:
            hit["trusted_policy_eligible"] = plan.trusted_policy_eligible
            hit["relaxation_level"] = plan.level
        return hits

    @classmethod
    def _apply_filter_contract(
        cls,
        result: dict[str, Any],
        plan: FilterPlan,
    ) -> dict[str, Any]:
        result["trusted_policy_eligible"] = plan.trusted_policy_eligible
        result["relaxation_level"] = plan.level
        trace = result.setdefault("trace", {})
        trace["trusted_policy_eligible"] = plan.trusted_policy_eligible
        trace["relaxation_level"] = plan.level
        hits = result.get("hits")
        if isinstance(hits, list):
            cls._annotate_hits_with_filter_contract(hits, plan)
        return result

    def _vector_search(
        self,
        *,
        psycopg_module: Any,
        embedding: list[float],
        merchant_code: str | None,
        product_category: str | None,
        scene: str | None,
        intent: str | None,
        source_type: str | None,
        policy_version: str | None,
        as_of_time: datetime | None = None,
        filter_plan: FilterPlan | None = None,
        limit: int,
    ) -> list[dict[str, Any]]:
        plan = filter_plan or self._strict_filter_plan(
            merchant_code=merchant_code,
            product_category=product_category,
            scene=scene,
            intent=intent,
            source_type=source_type,
            policy_version=policy_version,
            as_of_time=as_of_time,
        )
        filter_sql, filter_params = build_hard_filter_sql(plan)
        where_sql = "WHERE " + filter_sql
        params = [self._vector_literal(embedding), *filter_params]
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
        params.append(self._vector_literal(embedding))
        with psycopg_module.connect(self.config.dsn) as conn:
            with conn.cursor() as cur:
                # IVFFlat trades recall for speed. Keep this per transaction so
                # the setting cannot leak to pooled connections.
                probes = max(1, min(int(self.config.ivfflat_probes), 1000))
                cur.execute(f"SET LOCAL ivfflat.probes = {probes}")
                cur.execute(sql, params)
                rows = cur.fetchall()
        hits = [self._row_to_hit(row, rank=rank, channel="dense") for rank, row in enumerate(rows, start=1)]
        return self._annotate_hits_with_filter_contract(hits, plan)

    @staticmethod
    def _row_to_hit(row: Any, *, rank: int = 1, channel: str = "dense") -> dict[str, Any]:
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
            "valid_from": PgVectorKnowledgeRetriever._serialize_time(row[15]),
            "valid_to": PgVectorKnowledgeRetriever._serialize_time(row[16]),
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
            "valid_from": PgVectorKnowledgeRetriever._serialize_time(row[15]),
            "valid_to": PgVectorKnowledgeRetriever._serialize_time(row[16]),
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

    def _merge_and_rerank_hits(
        self,
        vector_hits: list[dict[str, Any]],
        lexical_hits: list[dict[str, Any]],
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        del query
        return rrf_fuse(vector_hits, lexical_hits, limit=limit)

    def _keyword_search(
        self,
        *,
        psycopg_module: Any,
        query: str,
        merchant_code: str | None,
        product_category: str | None,
        scene: str | None,
        intent: str | None,
        source_type: str | None,
        policy_version: str | None,
        as_of_time: datetime | None,
        filter_plan: FilterPlan | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        plan = filter_plan or self._strict_filter_plan(
            merchant_code=merchant_code,
            product_category=product_category,
            scene=scene,
            intent=intent,
            source_type=source_type,
            policy_version=policy_version,
            as_of_time=as_of_time,
        )
        filter_sql, filter_params = build_hard_filter_sql(plan)
        phrase = f"%{query}%"
        safe_limit = max(1, min(int(limit), 20))
        sql = f"""
            SELECT kc.id, kc.document_type, kd.source_code, kc.chunk_text, kc.metadata,
                   kd.title, kc.product_categories, kc.scenes, kc.intents, kd.policy_version,
                   kd.tags, kd.merchant_code, kc.heading_path, kc.page_number, kc.revision,
                   kd.valid_from, kd.valid_to, kc.document_id,
                   (similarity(kc.search_text, %s)
                    + CASE WHEN kc.search_text ILIKE %s THEN 1.0 ELSE 0 END
                    + CASE WHEN array_to_string(kc.heading_path, ' ') ILIKE %s THEN 0.6 ELSE 0 END) AS score
            FROM knowledge_chunk kc
            JOIN knowledge_document kd ON kd.id = kc.document_id
            WHERE {filter_sql}
              AND (kc.search_text %% %s OR kc.search_text ILIKE %s)
            ORDER BY score DESC, kc.id
            LIMIT {safe_limit}
        """
        params = [query, phrase, phrase, *filter_params, query, phrase]
        with psycopg_module.connect(self.config.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        hits = [self._row_to_hit(row, rank=rank, channel="keyword") for rank, row in enumerate(rows, start=1)]
        return self._annotate_hits_with_filter_contract(hits, plan)

    def _lexical_fallback(
        self,
        *,
        query: str,
        merchant_code: str | None = None,
        product_category: str | None = None,
        scene: str | None = None,
        intent: str | None = None,
        source_type: str | None = None,
        policy_version: str | None = None,
        as_of_time: datetime | None = None,
        filter_plan: FilterPlan | None = None,
        top_k: int | None = None,
    ) -> dict[str, Any]:
        if not self.config.dsn:
            return {"mode": "lexical_not_configured", "query": query, "hits": [], "trace": {"reason": "PGVECTOR_DSN is empty"}}
        try:
            import psycopg  # type: ignore
        except Exception as exc:
            return {"mode": "lexical_dependency_missing", "query": query, "hits": [], "trace": {"error": exc.__class__.__name__}}

        metadata_filters = {
            "merchant_code": merchant_code,
            "product_category": product_category,
            "scene": scene,
            "intent": intent,
            "source_type": source_type,
            "policy_version": policy_version,
            "as_of_time": (as_of_time or datetime.now()).isoformat(),
        }
        try:
            hits = self._keyword_search(
                psycopg_module=psycopg,
                query=query,
                merchant_code=merchant_code,
                product_category=product_category,
                scene=scene,
                intent=intent,
                source_type=source_type,
                policy_version=policy_version,
                as_of_time=as_of_time,
                filter_plan=filter_plan,
                limit=max(1, min(int(top_k or self.config.top_k), 20)),
            )
        except Exception as exc:
            return {"mode": "lexical_error", "query": query, "hits": [], "trace": {"error": exc.__class__.__name__, "message": str(exc)}}
        result = {
            "mode": "lexical_fallback",
            "query": query,
            "hits": hits,
            "trace": {"filters": metadata_filters, "top_k": len(hits), "tokens": self._lexical_tokens(query)},
        }
        plan = filter_plan or self._strict_filter_plan(
            merchant_code=merchant_code,
            product_category=product_category,
            scene=scene,
            intent=intent,
            source_type=source_type,
            policy_version=policy_version,
            as_of_time=as_of_time,
        )
        return self._apply_filter_contract(result, plan)

    @staticmethod
    def _lexical_tokens(query: str) -> list[str]:
        """通用中文分词 — 不区分领域特定术语，按自然词边界切分。"""
        import re as _re
        text = str(query or "")
        # 中文按字切 bigram + trigram，英文/数字保持原样
        tokens: list[str] = []
        # 提取中文连续片段做 n-gram
        for segment in _re.split(r"[^一-鿿]+", text):
            segment = segment.strip()
            if len(segment) >= 2:
                # bigram
                for i in range(len(segment) - 1):
                    tokens.append(segment[i:i + 2])
                # trigram for longer segments
                if len(segment) >= 3:
                    for i in range(len(segment) - 2):
                        tokens.append(segment[i:i + 3])
        # 保留英文/数字 tokens（按空格分）
        for raw in text.replace("_", " ").replace("/", " ").split():
            value = raw.strip()
            if len(value) >= 2 and not _re.fullmatch(r"[一-鿿]+", value):
                tokens.append(value)
        # 去重，限制数量
        seen: set[str] = set()
        result: list[str] = []
        for t in tokens:
            if t not in seen:
                seen.add(t)
                result.append(t)
        return result[:16]

    @staticmethod
    def _lexical_token_weight(token: str) -> float:
        """按 token 长度自适应权重 — 长词更可能是关键信息。"""
        length = len(token)
        if length >= 6:
            return 2.0
        if length >= 4:
            return 1.5
        return 1.0

    @staticmethod
    def _scene_aliases(scene: str | None) -> list[str]:
        value = str(scene or "").strip()
        if not value:
            return []
        alias_map = {
            "damage": ["damage", "product_damage"],
            "product_damage": ["product_damage", "damage"],
            "quality_issue": ["quality_issue"],
            "package_damage": ["package_damage"],
            "wrong_or_missing_items": ["wrong_or_missing_items"],
            "logistics_issue": ["logistics_issue", "logistics_damage"],
            "logistics_damage": ["logistics_damage", "logistics_issue"],
        }
        aliases = alias_map.get(value, [value])
        return list(dict.fromkeys(aliases))

    @staticmethod
    def _product_category_aliases(product_category: str | None) -> list[str]:
        value = str(product_category or "").strip()
        if not value:
            return []
        lowered = value.lower()
        alias_map = {
            "数码": ["数码", "digital", "headphone", "phone"],
            "digital": ["digital", "数码", "headphone", "phone"],
            "耳机": ["耳机", "headphone", "digital", "数码"],
            "蓝牙耳机": ["蓝牙耳机", "耳机", "headphone", "digital", "数码"],
            "蓝牙降噪耳机": ["蓝牙降噪耳机", "蓝牙耳机", "耳机", "headphone", "digital", "数码"],
            "headphone": ["headphone", "耳机", "digital", "数码"],
            "手机": ["手机", "phone", "digital", "数码"],
            "phone": ["phone", "手机", "digital", "数码"],
            "服装": ["服装", "apparel"],
            "apparel": ["apparel", "服装"],
            "日用": ["日用", "daily"],
            "daily": ["daily", "日用"],
            "鞋靴": ["鞋靴", "shoes"],
            "shoes": ["shoes", "鞋靴"],
            "食品": ["食品", "food"],
            "food": ["food", "食品"],
            "家居": ["家居", "home"],
            "home": ["home", "家居"],
            "其他": ["其他", "other"],
            "other": ["other", "其他"],
            "综合": ["综合", "general", "通用"],
            "通用": ["通用", "general"],
            "general": ["general", "通用"],
        }
        aliases = alias_map.get(value) or alias_map.get(lowered) or [value]
        return list(dict.fromkeys([str(item).strip() for item in aliases if str(item).strip()]))

    def _local_knowledge_fallback(
        self,
        *,
        query: str,
        merchant_code: str | None = None,
        product_category: str | None = None,
        scene: str | None = None,
        intent: str | None = None,
        source_type: str | None = None,
        policy_version: str | None = None,
        top_k: int | None = None,
    ) -> dict[str, Any]:
        knowledge = self._load_local_policy_knowledge()
        if not knowledge:
            return {"mode": "local_json_missing", "query": query, "hits": [], "trace": {"reason": "policy-knowledge-base.json missing"}}

        hits: list[dict[str, Any]] = []
        scene_aliases = set(self._scene_aliases(scene))
        limit = max(1, min(int(top_k or self.config.top_k), 10))

        for item in knowledge.get("scene_evidence_knowledge") or []:
            if not isinstance(item, dict):
                continue
            item_scene = str(item.get("scene") or "").strip()
            if scene_aliases and item_scene not in scene_aliases:
                continue
            default_evidence = item.get("default_evidence")
            snippet = str(item.get("description") or "")
            hits.append(
                {
                    "id": f"local-scene-{item_scene}",
                    "source_type": "scene_evidence",
                    "source_code": item_scene,
                    "title": str(item.get("label") or item_scene),
                    "snippet": snippet,
                    "score": 0.99,
                    "metadata": {
                        "scene": item_scene,
                        "default_evidence": default_evidence if isinstance(default_evidence, list) else [],
                        "merchant_code": merchant_code,
                        "product_category": product_category,
                        "intent": intent,
                        "policy_version": policy_version,
                    },
                }
            )

        query_lower = query.lower()
        for section_name, source_name in (
            ("after_sales_policy_knowledge", "after_sales_policy"),
            ("faq_knowledge", "faq"),
            ("product_knowledge", "product_knowledge"),
            ("review_interpretation_knowledge", "review_interpretation"),
            ("reply_template_knowledge", "reply_template"),
        ):
            for item in knowledge.get(section_name) or []:
                if not isinstance(item, dict):
                    continue
                text = " ".join(str(item.get(key) or "") for key in ("title", "question", "summary", "content", "template", "meaning", "description"))
                if not text.strip():
                    continue
                score = self._local_text_match_score(query_lower, text.lower())
                if score <= 0:
                    continue
                item_scene = str(item.get("scene") or "").strip()
                if scene_aliases and item_scene and item_scene not in scene_aliases:
                    continue
                item_category = str(item.get("product_category") or item.get("product_name") or "").strip()
                category_aliases = {alias.lower() for alias in self._product_category_aliases(product_category)}
                if (
                    product_category
                    and item_category
                    and item_category.lower() not in category_aliases
                    and item_category not in {"general", "通用"}
                ):
                    continue
                hits.append(
                    {
                        "id": f"local-{section_name}-{item.get('code') or item.get('policy_code') or item.get('product_id') or len(hits)}",
                        "source_type": source_name,
                        "source_code": str(item.get("code") or item.get("policy_code") or item.get("question") or item.get("title") or len(hits)),
                        "title": str(item.get("title") or item.get("question") or item.get("policy_name") or section_name),
                        "snippet": text[:700],
                        "score": round(score, 4),
                        "metadata": item,
                    }
                )

        hits.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
        return {
            "mode": "local_json_fallback",
            "query": query,
            "hits": hits[:limit],
            "trace": {
                "scene": scene,
                "product_category": product_category,
                "merchant_code": merchant_code,
            },
        }

    @staticmethod
    def _local_text_match_score(query: str, text: str) -> float:
        tokens = [token for token in PgVectorKnowledgeRetriever._lexical_tokens(query) if token]
        if not tokens:
            return 0.0
        matched = sum(1 for token in tokens if token.lower() in text)
        if matched == 0:
            return 0.0
        return min(0.55 + matched * 0.08, 0.95)

    @staticmethod
    def _load_local_policy_knowledge() -> dict[str, Any]:
        candidates = [
            Path.cwd() / "src" / "main" / "resources" / "agent-knowledge-base" / "policy-knowledge-base.json",
            Path(__file__).resolve().parents[3] / "src" / "main" / "resources" / "agent-knowledge-base" / "policy-knowledge-base.json",
        ]
        for path in candidates:
            if not path.exists():
                continue
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    @staticmethod
    def _embedding_error_info(exc: Exception) -> dict[str, Any]:
        message = str(exc)
        lowered = message.lower()
        info = {
            "error": exc.__class__.__name__,
            "message": message,
            "type": "embedding_error",
        }
        if "10013" in message or "permission" in lowered or "访问套接字" in message:
            info["type"] = "network_blocked"
            info["hint"] = "Outbound connection to embedding service is blocked by local OS/network policy."
        elif "timed out" in lowered or "timeout" in lowered:
            info["type"] = "network_timeout"
            info["hint"] = "Embedding service request timed out."
        elif "name or service not known" in lowered or "nodename nor servname provided" in lowered:
            info["type"] = "dns_error"
            info["hint"] = "Embedding host DNS resolution failed."
        return info

    def _embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    def _get_query_embedding(self, text: str) -> tuple[list[float], bool]:
        """Cache query vectors only; documents remain live after knowledge updates."""
        cache_key = str(text or "").strip()
        ttl = max(0, self.config.embedding_cache_ttl_seconds)
        now = time.monotonic()
        if ttl and cache_key:
            with self._embedding_cache_lock:
                cached = self._embedding_cache.get(cache_key)
                if cached and now - cached[0] <= ttl:
                    self._embedding_cache.move_to_end(cache_key)
                    return list(cached[1]), True
                if cached:
                    self._embedding_cache.pop(cache_key, None)
        embedding = self._embed(cache_key)
        if ttl and cache_key:
            with self._embedding_cache_lock:
                self._embedding_cache[cache_key] = (now, list(embedding))
                self._embedding_cache.move_to_end(cache_key)
                while len(self._embedding_cache) > max(1, self.config.embedding_cache_max_entries):
                    self._embedding_cache.popitem(last=False)
        return embedding, False

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not self.config.embedding_api_key:
            raise RuntimeError("DASHSCOPE_API_KEY or BAILIAN_API_KEY is required for text-embedding-v3")
        normalized_texts = [str(text or "").strip() for text in texts]
        if not normalized_texts:
            return []
        if any(not text for text in normalized_texts):
            raise RuntimeError("embedding input contains empty text")

        payload = self._embedding_payload(normalized_texts)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self._embedding_url(),
            data=body,
            headers={
                "Authorization": f"Bearer {self.config.embedding_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        response_body = self._post_embedding(request)

        data = json.loads(response_body)
        vectors = self._parse_embedding_response(data)
        if len(vectors) != len(normalized_texts):
            raise RuntimeError(f"embedding count mismatch: expected {len(normalized_texts)}, got {len(vectors)}")
        for vector in vectors:
            if len(vector) != self.config.dimensions:
                raise RuntimeError(
                    f"embedding dimension mismatch: expected {self.config.dimensions}, got {len(vector)}"
                )
        return vectors

    def _embedding_url(self) -> str:
        base_url = self.config.embedding_base_url.rstrip("/")
        if self.config.embedding_provider == "openai_compatible" and not base_url.endswith("/embeddings"):
            return f"{base_url}/embeddings"
        if base_url:
            return base_url
        raise RuntimeError("EMBEDDING_BASE_URL is required")

    def _embedding_payload(self, texts: list[str]) -> dict[str, Any]:
        if self.config.embedding_provider == "openai_compatible":
            return {
                "model": self.config.embedding_model,
                "input": texts,
                "dimensions": self.config.dimensions,
            }
        return {
            "model": self.config.embedding_model,
            "input": {"texts": texts},
            "parameters": {
                "dimension": self.config.dimensions,
                "output_type": "dense",
            },
        }

    def _parse_embedding_response(self, data: dict[str, Any]) -> list[list[float]]:
        if self.config.embedding_provider == "openai_compatible":
            items = data.get("data") or []
            if not items or any("embedding" not in item for item in items):
                raise RuntimeError("embedding response missing data[].embedding")
            return [[float(value) for value in item["embedding"]] for item in items]

        output = data.get("output") or {}
        embeddings = output.get("embeddings") or []
        if not embeddings or any("embedding" not in item for item in embeddings):
            raise RuntimeError("embedding response missing output.embeddings[].embedding")
        return [[float(value) for value in item["embedding"]] for item in embeddings]

    def _post_embedding(self, request: urllib.request.Request) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self.config.embedding_max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.config.embedding_timeout_seconds) as response:
                    return response.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"embedding request failed with HTTP {exc.code}: {error_body}") from exc
            except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
                last_error = exc
                if attempt >= self.config.embedding_max_retries:
                    break
                time.sleep(min(2 ** (attempt - 1), 5))

        raise RuntimeError(
            "embedding request timed out or failed after "
            f"{self.config.embedding_max_retries} attempts; "
            f"url={self._embedding_url()}, timeout={self.config.embedding_timeout_seconds}s, "
            f"last_error={last_error}"
        )

    @staticmethod
    def _vector_literal(vector: list[float]) -> str:
        return "[" + ",".join(f"{item:.8f}" for item in vector) + "]"
