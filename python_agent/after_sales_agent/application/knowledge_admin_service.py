from __future__ import annotations

import base64
import binascii
from typing import Any

from after_sales_agent.application.knowledge_ingestion import (
    KnowledgeIngestionService,
    KnowledgeParseError,
)
from after_sales_agent.tools import AgentToolRegistry
from after_sales_agent.tools.registry import normalize_knowledge_result
from after_sales_agent.infrastructure import KnowledgeRepository, PsycopgKnowledgeRepository
from after_sales_agent.retrieval.pgvector_retriever import PgVectorConfig, PgVectorKnowledgeRetriever


class KnowledgeAdminService:
    """Application service for knowledge-base admin and smoke-test endpoints."""

    def __init__(
        self,
        ingestion: KnowledgeIngestionService | None = None,
        retriever: PgVectorKnowledgeRetriever | None = None,
        knowledge_repository: KnowledgeRepository | None = None,
    ) -> None:
        self.ingestion = ingestion or KnowledgeIngestionService()
        self.retriever = retriever if retriever is not None else PgVectorKnowledgeRetriever(PgVectorConfig.from_env())
        self._knowledge_repository = knowledge_repository or PsycopgKnowledgeRepository()

    def parse_document(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create an unpersisted, Java-controlled knowledge draft from an uploaded document."""
        try:
            raw = base64.b64decode(str(data["content_base64"]), validate=True)
            file_name = str(data["file_name"])
            knowledge_type = str(data["knowledge_type"])
            allowed_metadata = dict(data.get("allowed_metadata") or {})
        except (KeyError, TypeError, ValueError, binascii.Error) as exc:
            raise KnowledgeParseError("FILE_DECODE_FAILED") from exc

        result = self.ingestion.parse(
            file_name=file_name,
            content=raw,
            knowledge_type=knowledge_type,
            allowed_metadata=allowed_metadata,
        )
        return result.to_dict()

    def retrieve(self, data: dict[str, Any]) -> dict[str, Any]:
        sources = data.get("sources") if isinstance(data.get("sources"), list) else []
        source_type = sources[0] if len(sources) == 1 else data.get("source_type")
        result = normalize_knowledge_result(self.retriever.retrieve(
            query=str(data.get("query") or ""),
            merchant_code=data.get("merchant_code"),
            product_category=data.get("product_category"),
            scene=data.get("scene"),
            intent=data.get("intent"),
            source_type=source_type,
            policy_version=data.get("policy_version"),
            as_of_time=AgentToolRegistry._parse_as_of_time(data.get("as_of_time")),
            top_k=data.get("top_k"),
            retrieval_mode=str(data.get("retrieval_mode") or "rerank"),
        ))
        hits = [
            {
                **hit,
                "source_type": hit.get("metadata", {}).get("source_type") or hit.get("source_type"),
                "source_code": hit.get("source_code"),
                "title": hit.get("title"),
                "summary": hit.get("snippet"),
                "snippet": hit.get("snippet"),
                "score": hit.get("score"),
                "tags": hit.get("metadata", {}).get("tags") or [],
                "metadata": hit.get("metadata") or {},
            }
            for hit in result.get("hits", [])
        ]
        return {
            "query": result.get("query") or data.get("query") or "",
            "retrieval_mode": result.get("mode") or "pgvector",
            "total_hits": len(hits),
            "hits": hits,
            "filter_level": result.get("filter_level"),
            "reranker_succeeded": result.get("reranker_succeeded") is True,
            "trusted_policy_eligible": result.get("trusted_policy_eligible") is True,
            "threshold": result.get("threshold"),
            "no_answer": result.get("no_answer") is True,
            "failure_reason": result.get("failure_reason"),
            "trace": result.get("trace") or {},
        }

    def reindex(self) -> dict[str, Any]:
        import os
        dsn = os.getenv("PGVECTOR_DSN", "")
        if not dsn:
            raise RuntimeError("PGVECTOR_DSN is required")

        rows = self._knowledge_repository.list_active_documents(dsn)
        batch_size = max(1, min(int(os.getenv("EMBEDDING_BATCH_SIZE", "10")), 25))
        chunk_records: list[dict[str, Any]] = []

        for row in rows:
            for index, chunk_text in enumerate(self._chunks(row.text)):
                metadata = dict(row.metadata)
                metadata["title"] = row.title
                chunk_records.append(
                    {
                        "document_id": row.document_id,
                        "document_type": row.document_type,
                        "chunk_index": index,
                        "chunk_text": chunk_text,
                        "metadata": metadata,
                        "revision": row.revision,
                        "product_categories": row.product_categories,
                        "scenes": row.scenes,
                        "intents": row.intents,
                        "search_text": row.text.strip(),
                    }
                )

        try:
            embedded_records: list[tuple[dict[str, Any], list[float]]] = []
            for start in range(0, len(chunk_records), batch_size):
                batch = chunk_records[start : start + batch_size]
                vectors = self.retriever.embed_many([record["chunk_text"] for record in batch])
                if not isinstance(vectors, list) or len(vectors) != len(batch):
                    raise RuntimeError("EMBEDDING_COUNT_MISMATCH")
                embedded_records.extend(zip(batch, vectors))

            document_ids = [row.document_id for row in rows]
            if document_ids:
                locked = self._knowledge_repository.lock_and_delete_chunks(dsn, document_ids)
                expected = {
                    row.document_id: (row.revision, row.updated_at)
                    for row in rows
                }
                if locked != expected:
                    raise RuntimeError("REINDEX_SOURCE_CHANGED")
                for record, vector in embedded_records:
                    record["vector"] = vector
                self._knowledge_repository.insert_chunks(
                    dsn,
                    document_ids,
                    [record for record, _ in embedded_records],
                    vector_literal_fn=self.retriever._vector_literal,
                    jsonb_type=self._jsonb_type(),
                )
                self._knowledge_repository.set_published_revision(dsn, document_ids)
        except Exception as exc:
            raise RuntimeError(f"pgvector_error: {exc}") from exc

        return {"ok": True, "documents": len(rows), "chunks": len(chunk_records)}

    def generate_embeddings(self, chunks: list[Any]) -> dict[str, Any]:
        if not isinstance(chunks, list) or not chunks:
            raise ValueError("chunks must be a non-empty list")

        embeddings = self.retriever.embed_many([str(chunk) for chunk in chunks])
        return {
            "ok": True,
            "embeddings": embeddings,
            "count": len(embeddings),
            "dimensions": len(embeddings[0]) if embeddings and embeddings[0] else 0,
        }

    def list_documents(self, *, limit: int = 50) -> dict[str, Any]:
        import os
        safe_limit = max(1, min(int(limit), 200))
        config = PgVectorConfig.from_env()
        try:
            import psycopg
        except Exception as exc:
            raise RuntimeError(f"pg_dependency_missing: {exc}") from exc

        try:
            with psycopg.connect(config.dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, source_type, source_code, merchant_code, title, product_category,
                               scene, intent, policy_version, tags, metadata, status, updated_at
                        FROM knowledge_document
                        ORDER BY id
                        LIMIT %s
                        """,
                        (safe_limit,),
                    )
                    rows = cur.fetchall()
        except Exception as exc:
            raise RuntimeError(f"pgvector_error: {exc}") from exc

        return {
            "items": [
                {
                    "id": row[0],
                    "source_type": row[1],
                    "source_code": row[2],
                    "merchant_code": row[3],
                    "title": row[4],
                    "product_category": row[5],
                    "scene": row[6],
                    "intent": row[7],
                    "policy_version": row[8],
                    "tags": row[9] or [],
                    "metadata": row[10] or {},
                    "status": row[11],
                    "updated_at": row[12].isoformat() if row[12] else None,
                }
                for row in rows
            ]
        }

    @staticmethod
    def _chunks(text: str, limit: int = 700) -> list[str]:
        normalized = "\n".join(line.strip() for line in str(text or "").splitlines() if line.strip())
        if len(normalized) <= limit:
            return [normalized] if normalized else []
        result = []
        start = 0
        while start < len(normalized):
            result.append(normalized[start : start + limit])
            start += int(limit * 0.8)
        return result

    @staticmethod
    def _jsonb_type() -> Any:
        try:
            from psycopg.types.json import Jsonb
            return Jsonb
        except Exception:
            return dict
