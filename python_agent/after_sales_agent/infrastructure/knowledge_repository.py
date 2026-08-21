"""PostgreSQL / pgvector knowledge data-access layer.

Encapsulates all direct ``psycopg`` usage so that the application service
layer does not import the driver itself.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ActiveDocumentRow:
    document_id: int
    document_type: str | None
    title: str
    text: str
    metadata: dict[str, Any]
    revision: Any
    updated_at: Any
    product_categories: list[str] | None
    scenes: list[str] | None
    intents: list[str] | None


class KnowledgeRepository(Protocol):
    """Access pattern for knowledge-document rows and chunks."""

    def list_active_documents(self, dsn: str) -> list[ActiveDocumentRow]:
        ...

    def lock_and_delete_chunks(
        self,
        dsn: str,
        document_ids: list[int],
    ) -> dict[int, tuple[Any, Any]]:
        ...

    def insert_chunks(
        self,
        dsn: str,
        document_ids: list[int],
        records: list[dict[str, Any]],
        vector_literal_fn: Any,
        jsonb_type: Any,
    ) -> None:
        ...

    def set_published_revision(
        self,
        dsn: str,
        document_ids: list[int],
    ) -> None:
        ...


def _parse_row_metadata(raw_metadata: Any, row: tuple) -> dict[str, Any]:
    metadata = raw_metadata or {}
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    tags = row[9] or []
    return {
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


def _row_to_active_document(row: tuple) -> ActiveDocumentRow:
    metadata = _parse_row_metadata(row[10], row)
    return ActiveDocumentRow(
        document_id=row[0],
        document_type=row[1],
        title=row[3],
        text=f"{row[3]}\n{row[4]}",
        metadata=metadata,
        revision=row[12],
        updated_at=row[13],
        product_categories=[row[5]] if row[5] else None,
        scenes=[row[6]] if row[6] else None,
        intents=[row[7]] if row[7] else None,
    )


class PsycopgKnowledgeRepository:
    """Real PostgreSQL-backed implementation of ``KnowledgeRepository``."""

    def list_active_documents(self, dsn: str) -> list[ActiveDocumentRow]:
        try:
            import psycopg
        except Exception as exc:
            raise RuntimeError(f"pg_dependency_missing: {exc}") from exc

        rows: list[ActiveDocumentRow] = []
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
                        merchant_code,
                        COALESCE(published_revision, revision) AS target_revision,
                        updated_at
                    FROM knowledge_document
                    WHERE status = 1
                      AND review_status = 'PUBLISHED'
                      AND COALESCE(metadata ->> 'deleted', 'false') <> 'true'
                    ORDER BY id
                    """
                )
                for row in cur.fetchall():
                    rows.append(_row_to_active_document(row))
        return rows

    def lock_and_delete_chunks(
        self,
        dsn: str,
        document_ids: list[int],
    ) -> dict[int, tuple[Any, Any]]:
        try:
            import psycopg
        except Exception as exc:
            raise RuntimeError(f"pg_dependency_missing: {exc}") from exc

        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, COALESCE(published_revision, revision), updated_at
                    FROM knowledge_document
                    WHERE id = ANY(%s)
                      AND status = 1
                      AND review_status = 'PUBLISHED'
                      AND COALESCE(metadata ->> 'deleted', 'false') <> 'true'
                    FOR UPDATE
                    """,
                    (document_ids,),
                )
                locked = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
                cur.execute(
                    "DELETE FROM knowledge_chunk WHERE document_id = ANY(%s)",
                    (document_ids,),
                )
        return locked

    def insert_chunks(
        self,
        dsn: str,
        document_ids: list[int],
        records: list[dict[str, Any]],
        vector_literal_fn: Any,
        jsonb_type: Any,
    ) -> None:
        try:
            import psycopg
        except Exception as exc:
            raise RuntimeError(f"pg_dependency_missing: {exc}") from exc

        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                for record in records:
                    cur.execute(
                        """
                        INSERT INTO knowledge_chunk
                          (document_id, document_type, chunk_index, chunk_text, embedding, metadata,
                           revision, product_categories, scenes, intents, heading_path, search_text)
                        VALUES (%s, %s, %s, %s, %s::vector, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            record["document_id"],
                            record["document_type"],
                            record["chunk_index"],
                            record["chunk_text"],
                            vector_literal_fn(record["vector"]),
                            jsonb_type(record["metadata"]),
                            record["revision"],
                            record["product_categories"],
                            record["scenes"],
                            record["intents"],
                            [],
                            record["search_text"],
                        ),
                    )

    def set_published_revision(
        self,
        dsn: str,
        document_ids: list[int],
    ) -> None:
        try:
            import psycopg
        except Exception as exc:
            raise RuntimeError(f"pg_dependency_missing: {exc}") from exc

        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE knowledge_document
                    SET published_revision = COALESCE(published_revision, revision),
                        updated_at = NOW()
                    WHERE id = ANY(%s)
                      AND status = 1
                      AND review_status = 'PUBLISHED'
                      AND published_revision IS NULL
                      AND COALESCE(metadata ->> 'deleted', 'false') <> 'true'
                    """,
                    (document_ids,),
                )
