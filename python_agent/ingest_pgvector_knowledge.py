from __future__ import annotations

import os
from typing import Any

from after_sales_agent.services.pgvector_retrieval import PgVectorKnowledgeRetriever, PgVectorConfig


def pg_rows(dsn: str) -> list[dict[str, Any]]:
    import psycopg

    rows: list[dict[str, Any]] = []
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    source_type,
                    source_code,
                    title,
                    content,
                    product_category,
                    scene,
                    intent,
                    policy_version,
                    tags,
                    metadata,
                    merchant_code
                FROM knowledge_document
                WHERE status = 1
                ORDER BY id
                """
            )
            for row in cur.fetchall():
                metadata = row[10] or {}
                if isinstance(metadata, str):
                    import json

                    metadata = json.loads(metadata)
                tags = row[9] or []
                metadata = {
                    **metadata,
                    "source_type": row[1],
                    "source_code": row[2],
                    "title": row[3],
                    "merchant_code": row[11],
                    "product_category": row[5],
                    "scene": row[6],
                    "intent": row[7],
                    "policy_version": row[8],
                    "tags": tags,
                }
                rows.append(
                    {
                        "document_id": row[0],
                        "document_type": row[1],
                        "title": row[3],
                        "text": f"{row[3]}\n{row[4]}",
                        "metadata": metadata,
                    }
                )
    return rows


def chunks(text: str, limit: int = 700) -> list[str]:
    normalized = "\n".join(line.strip() for line in str(text or "").splitlines() if line.strip())
    if len(normalized) <= limit:
        return [normalized] if normalized else []
    result = []
    start = 0
    while start < len(normalized):
        result.append(normalized[start : start + limit])
        start += int(limit * 0.8)
    return result


def reindex() -> dict[str, int]:
    import psycopg
    from psycopg.types.json import Jsonb

    dsn = os.getenv("PGVECTOR_DSN", "")
    if not dsn:
        raise SystemExit("PGVECTOR_DSN is required")
    retriever = PgVectorKnowledgeRetriever(PgVectorConfig.from_env())
    rows = pg_rows(dsn)
    batch_size = max(1, min(int(os.getenv("EMBEDDING_BATCH_SIZE", "10")), 25))
    chunk_records: list[dict[str, Any]] = []
    for row in rows:
        for index, chunk_text in enumerate(chunks(row["text"])):
            metadata = dict(row["metadata"])
            metadata["title"] = row["title"]
            chunk_records.append(
                {
                    "document_id": row["document_id"],
                    "document_type": row["document_type"],
                    "chunk_index": index,
                    "chunk_text": chunk_text,
                    "metadata": metadata,
                }
            )

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM knowledge_chunk")
            for start in range(0, len(chunk_records), batch_size):
                batch = chunk_records[start : start + batch_size]
                vectors = retriever.embed_many([record["chunk_text"] for record in batch])
                for record, vector in zip(batch, vectors):
                    embedding = retriever._vector_literal(vector)
                    cur.execute(
                        """
                        INSERT INTO knowledge_chunk
                          (document_id, document_type, chunk_index, chunk_text, embedding, metadata)
                        VALUES (%s, %s, %s, %s, %s::vector, %s)
                        """,
                        (
                            record["document_id"],
                            record["document_type"],
                            record["chunk_index"],
                            record["chunk_text"],
                            embedding,
                            Jsonb(record["metadata"]),
                        ),
                    )
        conn.commit()
    return {"documents": len(rows), "chunks": len(chunk_records)}


def main() -> None:
    result = reindex()
    print(f"ingested {result['documents']} source documents, {result['chunks']} chunks")


if __name__ == "__main__":
    main()
