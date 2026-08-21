from __future__ import annotations

from dataclasses import dataclass
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import logging
import time
import socket
import threading
import urllib.error
import urllib.request
from typing import Any

from after_sales_agent.providers.reranker_client import RERANKER_CLIENTS, RerankResult, RerankerClient

from after_sales_agent.retrieval.knowledge_filters import (
    POLICY_SOURCE_TYPES,
    FilterContext,
    FilterPlan,
    build_filter_plans,
    build_hard_filter_sql,
)
from after_sales_agent.retrieval.rrf import rrf_fuse, rrf_fuse_rankings

# Phase 1: Deferred imports — loaded lazily to avoid circular imports
# embedding_service import is used via TYPE_CHECKING below and deferred in __init__

logger = logging.getLogger("after_sales_agent.rag")

RERANK_THRESHOLDS = {
    # Retrieval support and automatic approval are separate gates. These
    # thresholds admit calibrated qwen3-rerank policy matches for answering;
    # the workflow still requires >= 0.65 plus strict business filters,
    # version/validity matching and traceable citations before a policy can
    # contribute to automatic approval.
    #
    # Lowered from 0.55 to 0.35 to avoid filtering out relevant chunks
    # that Reranker ranks lower but are still correct.
    "after_sales_policy": 0.35,
    "refund_policy": 0.35,
    "exchange_rule": 0.35,
    "evidence_requirement": 0.45,
    "faq": 0.40,
}


@dataclass(frozen=True)
class PgVectorConfig:
    dsn: str
    layered_retrieval_enabled: bool = False
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
            layered_retrieval_enabled=_read_bool("RAG_LAYERED_RETRIEVAL_ENABLED", file_values, default=False),
            dimensions=int(os.getenv("PGVECTOR_DIMENSIONS") or file_values.get("PGVECTOR_DIMENSIONS", "1024")),
            top_k=int(os.getenv("PGVECTOR_TOP_K") or file_values.get("PGVECTOR_TOP_K", "5")),
            embedding_model=os.getenv("EMBEDDING_MODEL") or file_values.get("EMBEDDING_MODEL", "text-embedding-v3"),
            embedding_provider=os.getenv("EMBEDDING_PROVIDER") or file_values.get("EMBEDDING_PROVIDER", "dashscope"),
            embedding_api_key=(
                os.getenv("EMBEDDING_API_KEY")
                or file_values.get("EMBEDDING_API_KEY")
                or os.getenv("DASHSCOPE_API_KEY")
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


def _read_bool(name: str, file_values: dict[str, str], *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        raw = file_values.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


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

    def __init__(
        self,
        config: PgVectorConfig | None = None,
        *,
        reranker: Any | None = None,
    ) -> None:
        from after_sales_agent.infrastructure.embedding_service import EmbeddingService
        self.config = config or PgVectorConfig.from_env()
        self.reranker = reranker if reranker is not None else RERANKER_CLIENTS.get()
        self._embedding_cache: OrderedDict[str, tuple[float, list[float]]] = OrderedDict()
        self._embedding_cache_lock = threading.Lock()
        self._embedding_service = EmbeddingService(self.config)

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
        retrieval_mode: str = "rrf",
        query_id: str | None = None,
    ) -> dict[str, Any]:
        normalized_query = str(query or "").strip()
        selected_mode = str(retrieval_mode or "rrf").strip().lower()
        if selected_mode not in {"dense", "keyword", "rrf", "rerank"}:
            raise ValueError("retrieval_mode must be one of: dense, keyword, rrf, rerank")
        resolved_as_of_time = as_of_time or datetime.utcnow()
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
        if not normalized_query:
            return self._finalize_result(
                {"mode": "skipped", "hits": [], "query": normalized_query, "trace": {}},
                plan=strict_plan,
                failure_reason="EMPTY_QUERY",
            )
        safe_query_id = self._safe_query_id(query_id, normalized_query)
        logger.info(
            "rag retrieve start query_id=%s mode=%s dsn_configured=%s",
            safe_query_id,
            selected_mode,
            bool(self.config.dsn),
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
                return self._finalize_result(
                    local,
                    plan=strict_plan,
                    failure_reason="PGVECTOR_NOT_CONFIGURED",
                )
        if not self.config.dsn:
            logger.warning("rag pgvector dsn missing and local json fallback has no hits")
            return self._finalize_result(
                {
                    "mode": "pgvector_not_configured",
                    "hits": [],
                    "query": normalized_query,
                    "trace": {"reason": "PGVECTOR_DSN is empty"},
                },
                plan=strict_plan,
                failure_reason="PGVECTOR_NOT_CONFIGURED",
            )

        try:
            import psycopg  # type: ignore
        except Exception as exc:
            return self._finalize_result(
                {
                    "mode": "pgvector_dependency_missing",
                    "hits": [],
                    "query": normalized_query,
                    "trace": {"error": exc.__class__.__name__},
                },
                plan=strict_plan,
                failure_reason="PGVECTOR_DEPENDENCY_MISSING",
            )

        limit = max(1, min(int(top_k or self.config.top_k), 10))
        candidate_limit = 50
        if selected_mode == "keyword":
            keyword_started_at = time.perf_counter()
            keyword = self._lexical_fallback(
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
            keyword_latency_ms = round((time.perf_counter() - keyword_started_at) * 1000, 2)
            keyword = self._apply_filter_contract(keyword, strict_plan)
            keyword_hits = keyword.get("hits") or []
            no_answer = not keyword_hits
            trace_update = {
                "dense_candidate_count": 0,
                "keyword_candidate_count": len(keyword_hits),
                "rrf_candidate_count": 0,
                "rerank_candidate_count": 0,
                "retrieval_mode": "keyword",
                "fallback_reason": "NO_MATCH" if no_answer else None,
            }
            combined_trace = {"stage_latency_ms": {"keyword": keyword_latency_ms}}
            combined_trace.update(trace_update)
            return self._finalize_result(
                {"mode": "keyword", "hits": keyword_hits[:limit], "trace": combined_trace},
                plan=strict_plan,
                failure_reason="NO_MATCH" if no_answer else None,
                no_answer=no_answer,
            )

        try:
            embedding, embedding_cache_hit = self._get_query_embedding(normalized_query)
        except Exception as exc:
            error_info = self._embedding_error_info(exc)
            logger.error(
                "rag embedding failed query_id=%s type=%s error=%s",
                safe_query_id,
                error_info.get("type"),
                error_info.get("error"),
            )
            if selected_mode == "dense":
                return self._finalize_result(
                    {
                        "mode": "dense",
                        "hits": [],
                        "query": normalized_query,
                        "trace": {
                            "dense_candidate_count": 0,
                            "keyword_candidate_count": 0,
                            "rrf_candidate_count": 0,
                            "rerank_candidate_count": 0,
                            "retrieval_mode": "dense",
                            "fallback_reason": "EMBEDDING_ERROR",
                        },
                    },
                    plan=strict_plan,
                    failure_reason="EMBEDDING_ERROR",
                )
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
            if local["hits"]:
                local["mode"] = "local_json_fallback_after_embedding_error"
                local["trace"]["embedding_error"] = error_info
                logger.warning("rag fallback to local json after embedding error hits=%s", len(local["hits"]))
                return self._finalize_result(
                    local,
                    plan=strict_plan,
                    failure_reason="EMBEDDING_ERROR",
                )
            if lexical["hits"]:
                lexical["mode"] = "lexical_fallback_after_embedding_error"
                lexical["trace"]["embedding_error"] = error_info
                logger.warning("rag fallback to lexical after embedding error hits=%s", len(lexical["hits"]))
                return self._finalize_result(
                    lexical,
                    plan=strict_plan,
                    failure_reason="EMBEDDING_ERROR",
                )
            return self._finalize_result(
                {
                    "mode": "embedding_error",
                    "hits": [],
                    "query": normalized_query,
                    "trace": error_info,
                },
                plan=strict_plan,
                failure_reason="EMBEDDING_ERROR",
            )
        metadata_filters = {
            "merchant_code": merchant_code,
            "product_category": product_category,
            "scene": scene,
            "intent": intent,
            "source_type": source_type,
            "policy_version": policy_version,
            "as_of_time": resolved_as_of_time.isoformat(),
        }
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
            return self._finalize_result(
                {
                    "mode": "pgvector_error",
                    "hits": [],
                    "query": normalized_query,
                    "trace": {"error": exc.__class__.__name__, "message": str(exc)},
                },
                plan=strict_plan,
                failure_reason="PGVECTOR_ERROR",
            )
        vector_latency_ms = round((time.perf_counter() - vector_started_at) * 1000, 2)
        hits = self._annotate_hits_with_filter_contract(hits, strict_plan)
        if selected_mode == "dense":
            no_answer = not hits
            trace_update = {
                "dense_candidate_count": len(hits),
                "keyword_candidate_count": 0,
                "rrf_candidate_count": 0,
                "rerank_candidate_count": 0,
                "retrieval_mode": "dense",
                "fallback_reason": "NO_MATCH" if no_answer else None,
            }
            combined_trace = {
                "stage_latency_ms": {"vector": vector_latency_ms},
                "embedding_cache_hit": embedding_cache_hit,
            }
            combined_trace.update(trace_update)
            return self._finalize_result(
                {"mode": "dense", "hits": hits[:limit], "trace": combined_trace},
                plan=strict_plan,
                failure_reason="NO_MATCH" if no_answer else None,
                no_answer=no_answer,
            )
        keyword_started_at = time.perf_counter()
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
        keyword_latency_ms = round((time.perf_counter() - keyword_started_at) * 1000, 2)
        lexical = self._apply_filter_contract(lexical, strict_plan)
        lexical_hits = lexical.get("hits") or []
        if hits or lexical_hits:
            if selected_mode == "rrf":
                fused = rrf_fuse(hits, lexical_hits, limit=limit)
                self._annotate_hits_with_filter_contract(fused, strict_plan)
                no_answer = not fused
                trace_update = {
                    "dense_candidate_count": len(hits),
                    "keyword_candidate_count": len(lexical_hits),
                    "rrf_candidate_count": len(fused),
                    "rerank_candidate_count": 0,
                    "retrieval_mode": "rrf",
                    "fallback_reason": "NO_MATCH" if no_answer else None,
                }
                combined_trace = {
                    "stage_latency_ms": {
                        "vector": vector_latency_ms,
                        "keyword": keyword_latency_ms,
                    },
                    "embedding_cache_hit": embedding_cache_hit,
                }
                combined_trace.update(trace_update)
                return self._finalize_result(
                    {"mode": "rrf", "hits": fused, "trace": combined_trace},
                    plan=strict_plan,
                    failure_reason="NO_MATCH" if no_answer else None,
                    no_answer=no_answer,
                )
            return self._finalize_reranked_result(
                query=normalized_query,
                dense_hits=hits,
                keyword_hits=lexical_hits,
                plan=strict_plan,
                limit=limit,
                trace={
                    "filters": metadata_filters,
                    "top_k": limit,
                    "ivfflat_probes": self.config.ivfflat_probes,
                    "vector_latency_ms": vector_latency_ms,
                    "stage_latency_ms": {
                        "vector": vector_latency_ms,
                        "keyword": keyword_latency_ms,
                    },
                    "embedding_cache_hit": embedding_cache_hit,
                },
            )
        else:
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
                retrieval_mode=selected_mode,
            )
            return relaxed

    def retrieve_multi(
        self,
        *,
        original_query: str,
        queries: list[str],
        merchant_code: str | None = None,
        product_category: str | None = None,
        scene: str | None = None,
        intent: str | None = None,
        source_type: str | None = None,
        policy_version: str | None = None,
        as_of_time: datetime | None = None,
        top_k: int | None = None,
    ) -> dict[str, Any]:
        normalized_original = str(original_query or "").strip()
        normalized_queries: list[str] = []
        seen: set[str] = set()
        for raw_query in queries:
            query = " ".join(str(raw_query or "").split())
            key = query.casefold()
            if not query or key in seen:
                continue
            seen.add(key)
            normalized_queries.append(query)
            if len(normalized_queries) >= 3:
                break
        if not normalized_original or not normalized_queries:
            raise ValueError("original_query and at least one candidate query are required")

        resolved_as_of_time = as_of_time or datetime.utcnow()
        plan = build_filter_plans(
            FilterContext(
                merchant_code=self._normalized_merchant_code(merchant_code),
                source_type=source_type,
                policy_version=policy_version,
                as_of_time=resolved_as_of_time,
                product_category=product_category,
                scene=scene,
                intent=intent,
            )
        )[0]
        limit = max(1, min(int(top_k or self.config.top_k), 10))
        started_at = time.perf_counter()
        results: dict[int, dict[str, Any]] = {}
        candidate_traces: list[dict[str, Any]] = []

        def retrieve_candidate(
            index: int,
            query: str,
        ) -> tuple[int, dict[str, Any] | None, dict[str, Any]]:
            candidate_started_at = time.perf_counter()
            try:
                result = self.retrieve(
                    query=query,
                    merchant_code=merchant_code,
                    product_category=product_category,
                    scene=scene,
                    intent=intent,
                    source_type=source_type,
                    policy_version=policy_version,
                    as_of_time=resolved_as_of_time,
                    top_k=50,
                    retrieval_mode="rrf",
                    query_id=f"{self._safe_query_id(None, normalized_original)}-{index + 1}",
                )
                hits = result.get("hits") if isinstance(result.get("hits"), list) else []
                return index, result, {
                    "query_index": index,
                    "latency_ms": round((time.perf_counter() - candidate_started_at) * 1000, 2),
                    "hit_count": len(hits),
                    "mode": str(result.get("mode") or "unknown"),
                }
            except Exception as exc:
                return index, None, {
                    "query_index": index,
                    "latency_ms": round((time.perf_counter() - candidate_started_at) * 1000, 2),
                    "hit_count": 0,
                    "error_type": exc.__class__.__name__,
                }

        with ThreadPoolExecutor(
            max_workers=min(3, len(normalized_queries)),
            thread_name_prefix="rag-multi-query",
        ) as executor:
            futures = {
                executor.submit(retrieve_candidate, index, query): (index, query)
                for index, query in enumerate(normalized_queries)
            }
            for future in as_completed(futures):
                index, _query = futures[future]
                try:
                    result_index, result, candidate_trace = future.result()
                    candidate_traces.append(candidate_trace)
                    if result is not None:
                        results[result_index] = result
                except Exception as exc:
                    candidate_traces.append(
                        {
                            "query_index": index,
                            "latency_ms": 0.0,
                            "hit_count": 0,
                            "error_type": exc.__class__.__name__,
                        }
                    )

        rankings: list[list[dict[str, Any]]] = []
        for index in range(len(normalized_queries)):
            result = results.get(index)
            hits = result.get("hits") if isinstance(result, dict) else None
            rankings.append(
                [dict(hit) for hit in hits if isinstance(hit, dict)]
                if isinstance(hits, list)
                else []
            )
        fused = rrf_fuse_rankings(rankings, limit=20)
        self._annotate_hits_with_filter_contract(fused, plan)
        candidate_traces.sort(key=lambda item: int(item.get("query_index") or 0))
        failure_count = sum(1 for item in candidate_traces if item.get("error_type"))
        base_trace = {
            "candidate_query_count": len(normalized_queries),
            "candidate_success_count": len(results),
            "candidate_failure_count": failure_count,
            "candidate_traces": candidate_traces,
            "candidate_hit_count": sum(len(ranking) for ranking in rankings),
            "unique_candidate_count": len(fused),
            "stage_latency_ms": {
                "multi_query": round((time.perf_counter() - started_at) * 1000, 2)
            },
            "filter_level": plan.level,
            "relaxation_level": plan.level,
        }
        if not fused:
            all_failed = bool(failure_count) and not results
            return self._finalize_result(
                {
                    "mode": "multi_query_error" if all_failed else "multi_query_empty",
                    "query": normalized_original,
                    "hits": [],
                    "trace": base_trace,
                },
                plan=plan,
                failure_reason="MULTI_QUERY_ERROR" if all_failed else "NO_MATCH",
                reranker_succeeded=False,
                no_answer=True,
                trusted_policy_eligible=False,
            )

        reranked, rerank_success_count = self._rerank_across_queries(
            queries=normalized_queries,
            candidates=fused,
            top_n=limit,
        )
        reranker_enabled = bool(getattr(self.reranker.config, "configured", False))
        output_hits: list[dict[str, Any]] = []
        for raw_hit in reranked.items:
            hit = dict(raw_hit)
            source = self._hit_source_type(hit)
            threshold = self._threshold_for_source(source)
            hit["threshold"] = threshold
            hit["relaxation_level"] = plan.level
            hit["trusted_policy_eligible"] = False
            if reranked.degraded:
                output_hits.append(hit)
                continue
            if (
                not reranker_enabled
                and plan.level == "strict"
                and source in POLICY_SOURCE_TYPES
            ):
                # RRF is the configured ranking authority when the optional
                # reranker is disabled. Hard filters, citations, and policy
                # version checks are still enforced by PolicyEvaluator.
                hit["trusted_policy_eligible"] = True
                output_hits.append(hit)
                continue
            if self._rerank_score(hit) < threshold:
                continue
            if (
                plan.level == "strict"
                and source in POLICY_SOURCE_TYPES
            ):
                hit["trusted_policy_eligible"] = True
            output_hits.append(hit)

        reranker_succeeded = reranker_enabled and not reranked.degraded
        trusted_policy_eligible = bool(
            plan.level == "strict"
            and any(hit.get("trusted_policy_eligible") is True for hit in output_hits)
        )
        no_answer = bool(reranked.degraded or not output_hits)
        stage_latency_ms = dict(base_trace["stage_latency_ms"])
        stage_latency_ms["reranker"] = reranked.latency_ms
        stage_latency_ms["total"] = round((time.perf_counter() - started_at) * 1000, 2)
        base_trace.update(
            {
                "reranker_succeeded": reranker_succeeded,
                "reranker_failure_reason": reranked.failure_reason,
                "rerank_candidate_count": len(reranked.items),
                "rerank_query_source": "validated_candidate_queries",
                "rerank_query_count": len(normalized_queries),
                "rerank_query_success_count": rerank_success_count,
                "stage_latency_ms": stage_latency_ms,
                "trusted_policy_eligible": trusted_policy_eligible,
            }
        )
        return self._finalize_result(
            {
                "mode": (
                    "multi_query_reranked"
                    if reranker_enabled and reranker_succeeded
                    else "multi_query_rrf"
                    if not reranker_enabled and not reranked.degraded
                    else "multi_query_rrf_degraded"
                ),
                "query": normalized_original,
                "hits": output_hits,
                "trace": base_trace,
            },
            plan=plan,
            failure_reason=(
                reranked.failure_reason
                if reranked.degraded
                else ("NO_MATCH" if no_answer else None)
            ),
            reranker_succeeded=reranker_succeeded,
            no_answer=no_answer,
            trusted_policy_eligible=trusted_policy_eligible,
        )

    def _rerank_across_queries(
        self,
        *,
        queries: list[str],
        candidates: list[dict[str, Any]],
        top_n: int,
    ) -> tuple[RerankResult, int]:
        """Rerank each validated rewrite independently and keep each hit's best score."""
        started_at = time.perf_counter()
        bounded_top_n = max(1, min(len(candidates), 20))
        if not bool(getattr(self.reranker.config, "configured", False)):
            return (
                RerankResult(
                    items=list(candidates[:bounded_top_n]),
                    mode="multi_query_rrf",
                    degraded=False,
                    failure_reason=None,
                    latency_ms=round((time.perf_counter() - started_at) * 1000, 3),
                ),
                len(queries),
            )
        results: list[RerankResult] = []

        def rerank_one(query: str) -> RerankResult:
            try:
                return self.reranker.rerank(query, candidates, top_n=bounded_top_n)
            except Exception:
                return RerankResult(
                    items=[],
                    mode="hybrid_rrf_degraded",
                    degraded=True,
                    failure_reason="UNEXPECTED_ERROR",
                    latency_ms=0.0,
                )

        with ThreadPoolExecutor(
            max_workers=min(3, len(queries)),
            thread_name_prefix="rag-multi-query-rerank",
        ) as executor:
            futures = [executor.submit(rerank_one, query) for query in queries]
            for future in as_completed(futures):
                results.append(future.result())

        successful = [result for result in results if not result.degraded]
        latency_ms = round((time.perf_counter() - started_at) * 1000, 3)
        if not successful:
            failure_reason = next(
                (result.failure_reason for result in results if result.failure_reason),
                "UNEXPECTED_ERROR",
            )
            return (
                RerankResult(
                    items=list(candidates[:top_n]),
                    mode="hybrid_rrf_degraded",
                    degraded=True,
                    failure_reason=failure_reason,
                    latency_ms=latency_ms,
                ),
                0,
            )

        best_by_hit: dict[str, dict[str, Any]] = {}
        for result in successful:
            for item in result.items:
                key = str(
                    item.get("chunk_id")
                    or item.get("id")
                    or item.get("source_code")
                    or item.get("title")
                    or ""
                )
                current = best_by_hit.get(key)
                if current is None or self._rerank_score(item) > self._rerank_score(current):
                    best_by_hit[key] = dict(item)
        ranked = sorted(
            best_by_hit.values(),
            key=self._rerank_score,
            reverse=True,
        )[: max(1, top_n)]
        return (
            RerankResult(
                items=ranked,
                mode="hybrid_reranked",
                degraded=False,
                failure_reason=None,
                latency_ms=latency_ms,
            ),
            len(successful),
        )

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
        retrieval_mode: str = "rerank",
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
                "rag strict filters empty, retry fallback_level=%s",
                plan.level,
            )
            vector_started_at = time.perf_counter()
            try:
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
            except Exception as exc:
                vector_latency_ms = round((time.perf_counter() - vector_started_at) * 1000, 2)
                return self._finalize_result(
                    {
                        "mode": "pgvector_error",
                        "query": query,
                        "hits": [],
                        "trace": {
                            "error": exc.__class__.__name__,
                            "message": str(exc),
                            "strict_filters": strict_filters,
                            "filters": relaxed_filters,
                            "fallback_level": plan.level,
                            "fallback_attempts": attempts,
                            "vector_latency_ms": vector_latency_ms,
                        },
                    },
                    plan=plan,
                    failure_reason="PGVECTOR_ERROR",
                )
            vector_hits = self._annotate_hits_with_filter_contract(vector_hits, plan)
            vector_latency_ms = round((time.perf_counter() - vector_started_at) * 1000, 2)
            try:
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
                    top_k=50,
                )
            except Exception as exc:
                return self._finalize_result(
                    {
                        "mode": "lexical_error",
                        "query": query,
                        "hits": [],
                        "trace": {
                            "error": exc.__class__.__name__,
                            "message": str(exc),
                            "strict_filters": strict_filters,
                            "filters": relaxed_filters,
                            "fallback_level": plan.level,
                            "fallback_attempts": attempts,
                            "vector_latency_ms": vector_latency_ms,
                        },
                    },
                    plan=plan,
                    failure_reason="LEXICAL_ERROR",
                )
            lexical = self._apply_filter_contract(lexical, plan)
            if lexical.get("failure_reason") == "LEXICAL_ERROR":
                lexical_trace = lexical.setdefault("trace", {})
                lexical_trace.update(
                    {
                        "strict_filters": strict_filters,
                        "filters": relaxed_filters,
                        "fallback_level": plan.level,
                        "fallback_attempts": attempts,
                        "vector_latency_ms": vector_latency_ms,
                    }
                )
                return self._finalize_result(
                    lexical,
                    plan=plan,
                    failure_reason="LEXICAL_ERROR",
                )
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
            lexical_hits = lexical.get("hits") or []
            if vector_hits or lexical_hits:
                logger.warning(
                    "rag relaxed filters hit level=%s vector=%s keyword=%s",
                    plan.level,
                    len(vector_hits),
                    len(lexical_hits),
                )
                if retrieval_mode == "rrf":
                    fused = rrf_fuse(vector_hits, lexical_hits, limit=limit)
                    self._annotate_hits_with_filter_contract(fused, plan)
                    no_answer = not fused
                    trace_update = {
                        "dense_candidate_count": len(vector_hits),
                        "keyword_candidate_count": len(lexical_hits),
                        "rrf_candidate_count": len(fused),
                        "rerank_candidate_count": 0,
                        "retrieval_mode": "rrf",
                        "fallback_reason": "NO_MATCH" if no_answer else None,
                    }
                    updated_trace = dict(trace) if trace else {}
                    updated_trace.update(trace_update)
                    return self._finalize_result(
                        {"mode": "rrf", "hits": fused, "trace": updated_trace},
                        plan=plan,
                        failure_reason="NO_MATCH" if no_answer else None,
                        no_answer=no_answer,
                    )
                return self._finalize_reranked_result(
                    query=query,
                    dense_hits=vector_hits,
                    keyword_hits=lexical_hits,
                    plan=plan,
                    limit=limit,
                    trace=trace,
                )
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
        return self._finalize_result(
            {
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
            },
            plan=exhausted_plan,
            failure_reason="NO_MATCH",
        )

    @staticmethod
    def _normalized_merchant_code(merchant_code: str | None) -> str:
        from after_sales_agent.retrieval.retrieval_result import normalized_merchant_code
        return normalized_merchant_code(merchant_code)

    @staticmethod
    def _safe_query_id(query_id: str | None, query: str) -> str:
        from after_sales_agent.retrieval.retrieval_result import safe_query_id
        return safe_query_id(query_id, query)

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
                as_of_time=as_of_time or datetime.utcnow(),
                product_category=product_category,
                scene=scene,
                intent=intent,
            )
        )[0]

    @staticmethod
    def _serialize_time(value: Any) -> str | None:
        from after_sales_agent.retrieval.retrieval_result import serialize_time
        return serialize_time(value)

    @staticmethod
    def _annotate_hits_with_filter_contract(
        hits: list[dict[str, Any]],
        plan: FilterPlan,
    ) -> list[dict[str, Any]]:
        from after_sales_agent.retrieval.retrieval_result import (
            annotate_hits_with_filter_contract,
        )
        return annotate_hits_with_filter_contract(hits, plan)

    @classmethod
    def _apply_filter_contract(
        cls,
        result: dict[str, Any],
        plan: FilterPlan,
    ) -> dict[str, Any]:
        from after_sales_agent.retrieval.retrieval_result import apply_filter_contract
        return apply_filter_contract(result, plan)

    @classmethod
    def _finalize_result(
        cls,
        result: dict[str, Any],
        *,
        plan: FilterPlan,
        failure_reason: str | None,
        reranker_succeeded: bool = False,
        no_answer: bool = True,
        trusted_policy_eligible: bool = False,
        threshold: float | None = None,
    ) -> dict[str, Any]:
        finalized = dict(result)
        hits = finalized.get("hits")
        if not isinstance(hits, list):
            hits = []
        finalized["hits"] = hits
        resolved_threshold = float(
            threshold if threshold is not None else cls._threshold_for_source(plan.source_type)
        )
        finalized["filter_level"] = plan.level
        finalized["relaxation_level"] = plan.level
        finalized["reranker_succeeded"] = bool(reranker_succeeded)
        finalized["threshold"] = resolved_threshold
        finalized["no_answer"] = bool(no_answer)
        finalized["trusted_policy_eligible"] = bool(trusted_policy_eligible)
        finalized["failure_reason"] = failure_reason

        raw_trace = finalized.get("trace")
        if not isinstance(raw_trace, dict):
            raw_trace = {}
        stage_latency = raw_trace.get("stage_latency_ms")
        if not isinstance(stage_latency, dict):
            stage_latency = {}
        safe_stage_latency = {
            str(stage): float(duration)
            for stage, duration in stage_latency.items()
            if stage in {"embedding", "vector", "keyword", "rrf", "reranker", "multi_query", "total"}
            and isinstance(duration, (int, float))
            and math.isfinite(float(duration))
            and float(duration) >= 0
        }
        if (
            "vector_latency_ms" in raw_trace
            and "vector" not in safe_stage_latency
            and isinstance(raw_trace["vector_latency_ms"], (int, float))
        ):
            safe_stage_latency["vector"] = max(0.0, float(raw_trace["vector_latency_ms"]))
        trace = {
            "stage_latency_ms": safe_stage_latency,
            "filter_level": plan.level,
            "reranker_succeeded": bool(reranker_succeeded),
            "threshold": resolved_threshold,
            "failure_reason": failure_reason,
            "dense_candidate_count": cls._safe_trace_count(raw_trace.get("dense_candidate_count")),
            "keyword_candidate_count": cls._safe_trace_count(raw_trace.get("keyword_candidate_count")),
            "rrf_candidate_count": cls._safe_trace_count(raw_trace.get("rrf_candidate_count")),
            "rerank_candidate_count": cls._safe_trace_count(raw_trace.get("rerank_candidate_count")),
            "candidate_query_count": cls._safe_trace_count(raw_trace.get("candidate_query_count")),
            "candidate_success_count": cls._safe_trace_count(raw_trace.get("candidate_success_count")),
            "candidate_failure_count": cls._safe_trace_count(raw_trace.get("candidate_failure_count")),
            "candidate_hit_count": cls._safe_trace_count(raw_trace.get("candidate_hit_count")),
            "unique_candidate_count": cls._safe_trace_count(raw_trace.get("unique_candidate_count")),
            "rerank_query_count": cls._safe_trace_count(raw_trace.get("rerank_query_count")),
            "rerank_query_success_count": cls._safe_trace_count(
                raw_trace.get("rerank_query_success_count")
            ),
            "retrieval_mode": cls._safe_trace_name(
                raw_trace.get("retrieval_mode"), str(finalized.get("mode") or "unknown")
            ),
            "rerank_query_source": cls._safe_trace_name(
                raw_trace.get("rerank_query_source"), None
            ),
            "fallback_reason": cls._safe_trace_name(raw_trace.get("fallback_reason"), failure_reason),
            "trusted_policy_eligible": bool(trusted_policy_eligible),
        }
        raw_candidate_traces = raw_trace.get("candidate_traces")
        if isinstance(raw_candidate_traces, list):
            safe_candidate_traces: list[dict[str, Any]] = []
            for item in raw_candidate_traces[:3]:
                if not isinstance(item, dict):
                    continue
                candidate_trace = {
                    "query_index": cls._safe_trace_count(item.get("query_index")),
                    "latency_ms": max(0.0, float(item.get("latency_ms") or 0.0)),
                    "hit_count": cls._safe_trace_count(item.get("hit_count")),
                }
                mode = cls._safe_trace_name(item.get("mode"), None)
                error_type = cls._safe_trace_name(item.get("error_type"), None)
                if mode is not None:
                    candidate_trace["mode"] = mode
                if error_type is not None:
                    candidate_trace["error_type"] = error_type
                safe_candidate_traces.append(candidate_trace)
            trace["candidate_traces"] = safe_candidate_traces
        fallback_level = raw_trace.get("fallback_level")
        if fallback_level in {"strict", "category_relaxed", "scene_relaxed", "category_and_scene_relaxed", "intent_relaxed"}:
            trace["fallback_level"] = fallback_level
        reranker_failure = cls._safe_trace_name(raw_trace.get("reranker_failure_reason"), None)
        if reranker_failure is not None:
            trace["reranker_failure_reason"] = reranker_failure
        finalized["trace"] = trace

        for hit in hits:
            if not isinstance(hit, dict):
                continue
            hit["relaxation_level"] = plan.level
            if not trusted_policy_eligible:
                hit["trusted_policy_eligible"] = False
            else:
                hit.setdefault("trusted_policy_eligible", False)
        return finalized

    @staticmethod
    def _safe_trace_count(value: Any) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _safe_trace_name(value: Any, default: str | None) -> str | None:
        candidate = str(value).strip() if value is not None else ""
        if candidate and len(candidate) <= 64 and all(char.isalnum() or char == "_" for char in candidate):
            return candidate
        return default

    def _vector_search(
        merchant_code: str | None,
        product_category: str | None,
        scene: str | None,
        intent: str | None,
        source_type: str | None,
        policy_version: str | None,
        as_of_time: datetime,
        top_k: int | None,
        plan: FilterPlan,
    ) -> dict[str, Any]:
        """Keep the pre-rollout path free of embedding, RRF, and reranker calls."""
        if not self.config.dsn and source_type not in POLICY_SOURCE_TYPES:
            local = self._local_knowledge_fallback(
                query=query,
                merchant_code=merchant_code,
                product_category=product_category,
                scene=scene,
                intent=intent,
                source_type=source_type,
                policy_version=policy_version,
                top_k=top_k,
            )
            local_hits = local.get("hits") or []
            if local_hits:
                return self._finalize_result(
                    {
                        "mode": "local_json_compatibility",
                        "query": query,
                        "hits": local_hits,
                        "trace": {
                            **(local.get("trace") or {}),
                            "retrieval_mode": "compatibility",
                            "fallback_reason": "RAG_LAYERED_RETRIEVAL_DISABLED",
                        },
                    },
                    plan=plan,
                    failure_reason=None,
                    no_answer=False,
                )

        lexical = self._lexical_fallback(
            query=query,
            merchant_code=merchant_code,
            product_category=product_category,
            scene=scene,
            intent=intent,
            source_type=source_type,
            policy_version=policy_version,
            as_of_time=as_of_time,
            filter_plan=plan,
            top_k=top_k,
        )
        lexical = self._apply_filter_contract(lexical, plan)
        hits = lexical.get("hits") or []
        failure_reason = None if hits else str(lexical.get("failure_reason") or "NO_MATCH")
        return self._finalize_result(
            {
                "mode": "lexical_compatibility",
                "query": query,
                "hits": hits,
                "trace": {
                    **(lexical.get("trace") or {}),
                    "retrieval_mode": "compatibility",
                    "fallback_reason": "RAG_LAYERED_RETRIEVAL_DISABLED",
                },
            },
            plan=plan,
            failure_reason=failure_reason,
            no_answer=not hits,
        )

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
        from after_sales_agent.retrieval.search.vector_search import vector_search
        return vector_search(
            psycopg_module=psycopg_module,
            config=self.config,
            embedding=embedding,
            merchant_code=merchant_code,
            product_category=product_category,
            scene=scene,
            intent=intent,
            source_type=source_type,
            policy_version=policy_version,
            as_of_time=as_of_time,
            filter_plan=filter_plan,
            limit=limit,
        )

    @staticmethod
    def _row_to_hit(row: Any, *, rank: int = 1, channel: str = "dense") -> dict[str, Any]:
        from after_sales_agent.retrieval.search.vector_search import row_to_hit
        return row_to_hit(row, rank=rank, channel=channel)

    def _merge_and_rerank_hits(
        self,
        vector_hits: list[dict[str, Any]],
        lexical_hits: list[dict[str, Any]],
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        del query
        return rrf_fuse(vector_hits, lexical_hits, limit=limit)

    def _finalize_reranked_result(
        self,
        *,
        query: str,
        dense_hits: list[dict[str, Any]],
        keyword_hits: list[dict[str, Any]],
        plan: FilterPlan,
        limit: int,
        trace: dict[str, Any],
    ) -> dict[str, Any]:
        from after_sales_agent.retrieval.ranking.reranker import _finalize_reranked_result
        return _finalize_reranked_result(
            query=query,
            dense_hits=dense_hits,
            keyword_hits=keyword_hits,
            plan=plan,
            limit=limit,
            trace=trace,
            reranker_client=self.reranker,
        )

    @staticmethod
    def _hit_source_type(hit: dict[str, Any]) -> str:
        from after_sales_agent.retrieval.retrieval_result import hit_source_type
        return hit_source_type(hit)

    @staticmethod
    def _threshold_for_source(source_type: str | None) -> float:
        from after_sales_agent.retrieval.retrieval_result import threshold_for_source
        return threshold_for_source(source_type)

    @staticmethod
    def _rerank_score(hit: dict[str, Any]) -> float:
        from after_sales_agent.retrieval.retrieval_result import rerank_score
        return rerank_score(hit)

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
        from after_sales_agent.retrieval.search.keyword_search import _keyword_search
        return _keyword_search(
            psycopg_module=psycopg_module,
            config=self.config,
            query=query,
            merchant_code=merchant_code,
            product_category=product_category,
            scene=scene,
            intent=intent,
            source_type=source_type,
            policy_version=policy_version,
            as_of_time=as_of_time,
            filter_plan=filter_plan,
            limit=limit,
        )

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
        from after_sales_agent.retrieval.search.keyword_search import lexical_fallback

        plan = filter_plan or self._strict_filter_plan(
            merchant_code=merchant_code,
            product_category=product_category,
            scene=scene,
            intent=intent,
            source_type=source_type,
            policy_version=policy_version,
            as_of_time=as_of_time,
        )
        if not self.config.dsn:
            return self._finalize_result(
                {"mode": "lexical_not_configured", "query": query, "hits": [], "trace": {"reason": "PGVECTOR_DSN is empty"}},
                plan=plan,
                failure_reason="LEXICAL_NOT_CONFIGURED",
            )
        try:
            import psycopg  # type: ignore
        except Exception as exc:
            return self._finalize_result(
                {"mode": "lexical_dependency_missing", "query": query, "hits": [], "trace": {"error": exc.__class__.__name__}},
                plan=plan,
                failure_reason="LEXICAL_DEPENDENCY_MISSING",
            )

        metadata_filters = {
            "merchant_code": merchant_code,
            "product_category": product_category,
            "scene": scene,
            "intent": intent,
            "source_type": source_type,
            "policy_version": policy_version,
            "as_of_time": (as_of_time or datetime.utcnow()).isoformat(),
        }
        try:
            hits = lexical_fallback(
                psycopg_module=psycopg,
                config=self.config,
                query=query,
                merchant_code=merchant_code,
                product_category=product_category,
                scene=scene,
                intent=intent,
                source_type=source_type,
                policy_version=policy_version,
                as_of_time=as_of_time,
                filter_plan=filter_plan,
                limit=max(1, min(int(top_k or self.config.top_k), 50)),
            )
        except Exception as exc:
            return self._finalize_result(
                {"mode": "lexical_error", "query": query, "hits": [], "trace": {"error": exc.__class__.__name__, "message": str(exc)}},
                plan=plan,
                failure_reason="LEXICAL_ERROR",
            )
        result = {
            "mode": "lexical_fallback",
            "query": query,
            "hits": hits,
            "trace": {"filters": metadata_filters, "top_k": len(hits)} ,
        }
        return self._finalize_result(
            result,
            plan=plan,
            failure_reason="LEXICAL_FALLBACK_ONLY",
        )

    @staticmethod

    @staticmethod

    @staticmethod
    def _scene_aliases(scene: str | None) -> list[str]:
        from after_sales_agent.retrieval.alias_mapping import scene_aliases
        return scene_aliases(scene)

    @staticmethod
    def _product_category_aliases(product_category: str | None) -> list[str]:
        from after_sales_agent.retrieval.alias_mapping import product_category_aliases
        return product_category_aliases(product_category)

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
        from after_sales_agent.retrieval.search.local_fallback import (
            local_knowledge_hits,
        )

        knowledge = self._load_local_policy_knowledge()
        plan = self._strict_filter_plan(
            merchant_code=merchant_code,
            product_category=product_category,
            scene=scene,
            intent=intent,
            source_type=source_type,
            policy_version=policy_version,
            as_of_time=None,
        )
        try:
            hits, trace_info = local_knowledge_hits(
                query=query,
                merchant_code=merchant_code,
                product_category=product_category,
                scene=scene,
                intent=intent,
                source_type=source_type,
                policy_version=policy_version,
                top_k=top_k,
                config=self.config,
                _policy_knowledge_index=knowledge,
            )
        except Exception as exc:
            return self._finalize_result(
                {"mode": "local_error", "query": query, "hits": [], "trace": {"error": exc.__class__.__name__, "message": str(exc)}},
                plan=plan,
                failure_reason="LOCAL_ERROR",
            )

        if not hits:
            return self._finalize_result(
                {"mode": "local_json_missing", "query": query, "hits": [], "trace": {"reason": "no matching local knowledge"}},
                plan=plan,
                failure_reason="LOCAL_JSON_MISSING",
            )

        result = {
            "mode": "local_json_fallback",
            "query": query,
            "hits": hits,
            "trace": trace_info,
        }
        return self._finalize_result(
            result,
            plan=plan,
            failure_reason="LOCAL_FALLBACK_ONLY",
        )

    @staticmethod
    def _local_text_match_score(query: str, text: str) -> float:
        from after_sales_agent.retrieval.search.keyword_search import _local_text_match_score as _ltms
        return _ltms(query, text)

    @staticmethod
    def _load_local_policy_knowledge() -> dict[str, Any]:
        from after_sales_agent.retrieval.search.local_fallback import (
            load_local_policy_knowledge,
        )
        result = load_local_policy_knowledge()
        if result is not None:
            return result
        # Fallback to original path resolution
        candidates = [
            Path.cwd() / "src" / "main" / "resources" / "agent-knowledge-base" / "policy-knowledge-base.json",
            Path(__file__).resolve().parents[3] / "src" / "main" / "resources" / "agent-knowledge-base" / "policy-knowledge-base.json",
        ]
        for path in candidates:
            if not path.exists():
                continue
            try:
                import json
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    @staticmethod
    def _embedding_error_info(exc: Exception) -> dict[str, Any]:
        from after_sales_agent.infrastructure.embedding_service import embedding_error_info
        return embedding_error_info(exc)

    def _embed(self, text: str) -> list[float]:
        return self._embedding_service.get_embedding(text)

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
        return self._embedding_service.embed_many(texts)

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
        from after_sales_agent.retrieval.search.vector_search import _vector_literal
        return _vector_literal(vector)
