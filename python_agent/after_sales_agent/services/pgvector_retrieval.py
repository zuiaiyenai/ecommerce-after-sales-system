from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
import socket
import urllib.error
import urllib.request
from typing import Any


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
        )


def _read_local_env() -> dict[str, str]:
    candidates = [
        Path.cwd() / "db.local.env",
        Path.cwd() / "python_agent" / "db.local.env",
        Path(__file__).resolve().parents[2] / "db.local.env",
    ]
    values: dict[str, str] = {}
    for path in candidates:
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
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
        top_k: int | None = None,
    ) -> dict[str, Any]:
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return {"mode": "skipped", "hits": [], "query": normalized_query}
        if not self.config.dsn:
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
            embedding = self._embed(normalized_query)
        except Exception as exc:
            lexical = self._lexical_fallback(
                query=normalized_query,
                merchant_code=merchant_code,
                product_category=product_category,
                scene=scene,
                intent=intent,
                source_type=source_type,
                policy_version=policy_version,
                top_k=top_k,
            )
            if lexical["hits"]:
                lexical["mode"] = "lexical_fallback_after_embedding_error"
                lexical["trace"]["embedding_error"] = {"error": exc.__class__.__name__, "message": str(exc)}
                return lexical
            return {
                "mode": "embedding_error",
                "hits": [],
                "query": normalized_query,
                "trace": {"error": exc.__class__.__name__, "message": str(exc)},
            }
        filters: list[str] = []
        params: list[Any] = [self._vector_literal(embedding)]
        metadata_filters = {
            "merchant_code": merchant_code,
            "product_category": product_category,
            "scene": scene,
            "intent": intent,
            "source_type": source_type,
            "policy_version": policy_version,
        }
        for key, value in metadata_filters.items():
            if value:
                filters.append(f"kc.metadata ->> '{key}' = %s")
                params.append(str(value))

        where_sql = ("WHERE " + " AND ".join(filters)) if filters else ""
        limit = max(1, min(int(top_k or self.config.top_k), 10))
        sql = f"""
            SELECT kc.id, kc.document_type, kd.source_code, kc.chunk_text, kc.metadata,
                   1 - (kc.embedding <=> %s::vector) AS score
            FROM knowledge_chunk kc
            JOIN knowledge_document kd ON kd.id = kc.document_id
            {where_sql}
            ORDER BY kc.embedding <=> %s::vector
            LIMIT {limit}
        """
        params.append(self._vector_literal(embedding))
        try:
            with psycopg.connect(self.config.dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    rows = cur.fetchall()
        except Exception as exc:
            return {
                "mode": "pgvector_error",
                "hits": [],
                "query": normalized_query,
                "trace": {"error": exc.__class__.__name__, "message": str(exc)},
            }

        hits = []
        for row in rows:
            metadata = row[4]
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except json.JSONDecodeError:
                    metadata = {}
            hits.append(
                {
                    "id": row[0],
                    "source_type": row[1],
                    "source_code": str(row[2]),
                    "title": (metadata or {}).get("title") or row[1],
                    "snippet": row[3],
                    "score": round(float(row[5] or 0), 4),
                    "metadata": metadata or {},
                }
            )
        lexical = self._lexical_fallback(
            query=normalized_query,
            merchant_code=merchant_code,
            product_category=product_category,
            scene=scene,
            intent=intent,
            source_type=source_type,
            policy_version=policy_version,
            top_k=top_k,
        )
        if hits:
            hits = self._merge_and_rerank_hits(hits, lexical.get("hits") or [], normalized_query, limit)
        else:
            if lexical["hits"]:
                lexical["mode"] = "lexical_fallback_after_empty_vector"
                lexical["trace"]["vector_filters"] = metadata_filters
                return lexical
        return {
            "mode": "pgvector",
            "query": normalized_query,
            "hits": hits,
            "trace": {"filters": metadata_filters, "top_k": limit},
        }

    def _merge_and_rerank_hits(
        self,
        vector_hits: list[dict[str, Any]],
        lexical_hits: list[dict[str, Any]],
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        tokens = self._lexical_tokens(query)
        merged: dict[tuple[str, str], dict[str, Any]] = {}
        for hit in vector_hits:
            key = (str(hit.get("source_type") or ""), str(hit.get("source_code") or hit.get("id") or ""))
            merged[key] = {**hit, "retrieval_modes": ["vector"]}
        for hit in lexical_hits:
            key = (str(hit.get("source_type") or ""), str(hit.get("source_code") or hit.get("id") or ""))
            if key in merged:
                existing = merged[key]
                existing["retrieval_modes"] = sorted(set(existing.get("retrieval_modes") or []) | {"vector", "lexical"})
                existing["lexical_score"] = hit.get("score")
                if len(str(hit.get("snippet") or "")) > len(str(existing.get("snippet") or "")):
                    existing["snippet"] = hit.get("snippet")
                existing["metadata"] = {**(hit.get("metadata") or {}), **(existing.get("metadata") or {})}
            else:
                merged[key] = {**hit, "retrieval_modes": ["lexical"], "lexical_score": hit.get("score")}

        def rank(hit: dict[str, Any]) -> float:
            text = f"{hit.get('title') or ''} {hit.get('snippet') or ''}".lower()
            token_bonus = 0.0
            for token in tokens:
                value = token.lower()
                if value and value in text:
                    token_bonus += 0.06 * self._lexical_token_weight(token)
            token_bonus = min(token_bonus, 0.5)
            source_bonus = 0.04 if hit.get("source_type") == "after_sales_policy" else 0.0
            lexical_bonus = 0.08 if "lexical" in (hit.get("retrieval_modes") or []) else 0.0
            return float(hit.get("score") or 0) + token_bonus + source_bonus + lexical_bonus

        ranked = sorted(merged.values(), key=rank, reverse=True)[:limit]
        for hit in ranked:
            hit["rerank_score"] = round(rank(hit), 4)
        return ranked

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
        top_k: int | None = None,
    ) -> dict[str, Any]:
        if not self.config.dsn:
            return {"mode": "lexical_not_configured", "query": query, "hits": [], "trace": {"reason": "PGVECTOR_DSN is empty"}}
        try:
            import psycopg  # type: ignore
        except Exception as exc:
            return {"mode": "lexical_dependency_missing", "query": query, "hits": [], "trace": {"error": exc.__class__.__name__}}

        tokens = self._lexical_tokens(query)
        if not tokens:
            return {"mode": "lexical_skipped", "query": query, "hits": [], "trace": {"reason": "no tokens"}}
        filters: list[str] = ["kd.status = 1"]
        filter_params: list[Any] = []
        metadata_filters = {
            "merchant_code": merchant_code,
            "product_category": product_category,
            "scene": scene,
            "intent": intent,
            "source_type": source_type,
            "policy_version": policy_version,
        }
        if merchant_code:
            filters.append("kd.merchant_code = %s")
            filter_params.append(str(merchant_code))
        if product_category:
            filters.append("(kd.product_category = %s OR kd.product_category IS NULL OR kd.product_category IN ('general', '通用'))")
            filter_params.append(str(product_category))
        if scene:
            filters.append("(kd.scene = %s OR kd.scene IS NULL)")
            filter_params.append(str(scene))
        if intent:
            filters.append("(kd.intent = %s OR kd.intent IS NULL)")
            filter_params.append(str(intent))
        if source_type:
            filters.append("kd.source_type = %s")
            filter_params.append(str(source_type))
        if policy_version:
            filters.append("(kd.policy_version = %s OR kd.policy_version IS NULL)")
            filter_params.append(str(policy_version))

        score_terms = []
        score_params: list[Any] = []
        max_score = 0.0
        for token in tokens:
            weight = self._lexical_token_weight(token)
            max_score += weight * 4
            score_terms.append("(CASE WHEN kd.title LIKE %s THEN %s ELSE 0 END)")
            score_params.append(f"%{token}%")
            score_params.append(weight * 3)
            score_terms.append("(CASE WHEN kd.content LIKE %s THEN %s ELSE 0 END)")
            score_params.append(f"%{token}%")
            score_params.append(weight)
        score_sql = " + ".join(score_terms)
        limit = max(1, min(int(top_k or self.config.top_k), 10))
        sql = f"""
            SELECT kd.id, kd.source_type, kd.source_code, kd.title, kd.content,
                   kd.product_category, kd.scene, kd.intent, kd.policy_version,
                   kd.tags, kd.metadata,
                   ({score_sql}) AS lexical_score
            FROM knowledge_document kd
            WHERE {" AND ".join(filters)}
            ORDER BY lexical_score DESC, kd.updated_at DESC
            LIMIT {limit}
        """
        try:
            with psycopg.connect(self.config.dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, score_params + filter_params)
                    rows = cur.fetchall()
        except Exception as exc:
            return {"mode": "lexical_error", "query": query, "hits": [], "trace": {"error": exc.__class__.__name__, "message": str(exc)}}

        hits = []
        for row in rows:
            score = float(row[11] or 0)
            if score <= 0:
                continue
            metadata = row[10] or {}
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except json.JSONDecodeError:
                    metadata = {}
            metadata = {
                **(metadata or {}),
                "source_type": row[1],
                "source_code": row[2],
                "title": row[3],
                "product_category": row[5],
                "scene": row[6],
                "intent": row[7],
                "policy_version": row[8],
                "tags": row[9] or [],
            }
            hits.append(
                {
                    "id": row[0],
                    "source_type": row[1],
                    "source_code": str(row[2]),
                    "title": row[3],
                    "snippet": str(row[4] or "")[:700],
                    "score": round(min(score / max(max_score, 1), 1.0), 4),
                    "metadata": metadata,
                }
            )
        return {
            "mode": "lexical_fallback",
            "query": query,
            "hits": hits,
            "trace": {"filters": metadata_filters, "top_k": limit, "tokens": tokens},
        }

    @staticmethod
    def _lexical_tokens(query: str) -> list[str]:
        candidates = [
            "外壳破裂", "外壳破损", "商品破损", "破损", "破裂", "裂纹", "碎裂",
            "质量问题", "功能故障", "电流声", "异响", "杂音", "无法正常使用",
            "退款", "退货退款", "退货", "换货", "凭证", "证据", "照片", "外包装", "物流面单",
            "耳机", "手机", "数码",
        ]
        text = str(query or "")
        tokens = [token for token in candidates if token in text]
        for raw in text.replace("_", " ").replace("/", " ").split():
            value = raw.strip()
            if len(value) >= 3 and value not in tokens:
                tokens.append(value)
        return tokens[:16]

    @staticmethod
    def _lexical_token_weight(token: str) -> float:
        strong_problem_terms = {
            "外壳破裂", "外壳破损", "商品破损", "破损", "破裂", "裂纹", "碎裂",
            "质量问题", "功能故障", "电流声", "异响", "杂音", "无法正常使用",
        }
        weak_context_terms = {"退款", "退货退款", "退货", "换货", "凭证", "证据", "照片", "耳机", "手机", "数码"}
        if token in strong_problem_terms:
            return 2.2
        if token in weak_context_terms:
            return 0.7
        if len(token) >= 6:
            return 1.4
        return 1.0

    def _embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

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
