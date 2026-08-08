from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime
import os
from types import SimpleNamespace

import pytest

from after_sales_agent.retrieval.pgvector_retriever import PgVectorConfig, PgVectorKnowledgeRetriever


pytestmark = pytest.mark.integration


@pytest.fixture()
def pg_connection():
    dsn = os.getenv("PGVECTOR_INTEGRATION_DSN", "").strip()
    if not dsn:
        pytest.skip("PGVECTOR_INTEGRATION_DSN is required")
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            cursor.execute("""
                CREATE TEMP TABLE knowledge_document (
                    id BIGINT PRIMARY KEY, status INTEGER NOT NULL, metadata JSONB NOT NULL,
                    published_revision BIGINT, merchant_code TEXT NOT NULL, source_type TEXT,
                    policy_version TEXT, valid_from TIMESTAMP, valid_to TIMESTAMP,
                    source_code TEXT, title TEXT, tags TEXT[]
                ) ON COMMIT PRESERVE ROWS
            """)
            cursor.execute("""
                CREATE TEMP TABLE knowledge_chunk (
                    id BIGINT PRIMARY KEY, document_id BIGINT NOT NULL, document_type TEXT,
                    chunk_text TEXT, metadata JSONB, product_categories TEXT[], scenes TEXT[],
                    intents TEXT[], heading_path TEXT[], page_number INTEGER, revision BIGINT,
                    embedding vector(1), search_text TEXT
                ) ON COMMIT PRESERVE ROWS
            """)
            cursor.execute("""
                INSERT INTO knowledge_document
                    (id,status,metadata,published_revision,merchant_code,source_type,policy_version,
                     valid_from,valid_to,source_code,title,tags)
                VALUES (9001,1,'{}',1,'M1','faq','v2','2026-01-01','2027-01-01','FAQ-1','Refund FAQ','{}')
            """)
            cursor.execute("""
                INSERT INTO knowledge_chunk
                    (id,document_id,document_type,chunk_text,metadata,product_categories,scenes,
                     intents,heading_path,page_number,revision,embedding,search_text)
                VALUES (
                    9101,9001,'faq','refund policy','{}',ARRAY['headphone'],ARRAY['quality_issue'],
                    ARRAY['refund'],ARRAY['Refund'],1,1,'[0]','refund policy'
                )
            """)
        connection.commit()
        yield connection, psycopg


@pytest.mark.parametrize(
    ("source_type", "policy_version", "product_category", "scene", "intent"),
    [
        (None, None, None, None, None),
        ("faq", None, "headphone", None, None),
        ("faq", "v2", "headphone", "quality_issue", "refund"),
    ],
)
def test_dense_and_keyword_execute_with_nullable_filters_on_real_postgres(
    pg_connection,
    source_type,
    policy_version,
    product_category,
    scene,
    intent,
) -> None:
    connection, psycopg = pg_connection
    borrowed_module = SimpleNamespace(connect=lambda _dsn: nullcontext(connection))
    retriever = PgVectorKnowledgeRetriever(
        PgVectorConfig(
            dsn="borrowed",
            dimensions=1,
            embedding_api_key="unused",
            layered_retrieval_enabled=True,
        )
    )
    common = {
        "merchant_code": "M1",
        "product_category": product_category,
        "scene": scene,
        "intent": intent,
        "source_type": source_type,
        "policy_version": policy_version,
        "as_of_time": datetime(2026, 7, 21),
        "limit": 20,
    }

    dense = retriever._vector_search(psycopg_module=borrowed_module, embedding=[0.0], **common)
    keyword = retriever._keyword_search(
        psycopg_module=borrowed_module,
        query="refund policy",
        filter_plan=None,
        **common,
    )

    assert [hit["chunk_id"] for hit in dense] == [9101]
    assert [hit["chunk_id"] for hit in keyword] == [9101]
