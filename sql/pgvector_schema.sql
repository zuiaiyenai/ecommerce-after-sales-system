-- PostgreSQL pgvector schema for Python-side RAG.
-- Source data is ingested from MySQL knowledge tables into vector chunks.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS knowledge_document
(
    id               BIGSERIAL PRIMARY KEY,
    source_type      VARCHAR(40) NOT NULL,
    source_code      VARCHAR(100) NOT NULL,
    merchant_code    VARCHAR(50) NOT NULL DEFAULT 'MERCHANT_DEMO',
    title            VARCHAR(300) NOT NULL,
    content          TEXT NOT NULL,
    product_category VARCHAR(100) NULL,
    scene            VARCHAR(64) NULL,
    intent           VARCHAR(64) NULL,
    policy_version   VARCHAR(64) NULL,
    tags             JSONB NULL,
    metadata         JSONB NULL,
    status           SMALLINT NOT NULL DEFAULT 1,
    created_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (source_type, source_code, merchant_code)
);

CREATE TABLE IF NOT EXISTS knowledge_chunk
(
    id            BIGSERIAL PRIMARY KEY,
    document_id   BIGINT NOT NULL REFERENCES knowledge_document(id) ON DELETE CASCADE,
    document_type VARCHAR(30) NOT NULL,
    chunk_index   INTEGER NOT NULL,
    chunk_text    TEXT NOT NULL,
    embedding     vector(1024) NOT NULL,
    metadata      JSONB NULL,
    create_time   TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kd_source_type ON knowledge_document (source_type);
CREATE INDEX IF NOT EXISTS idx_kd_merchant_code ON knowledge_document (merchant_code);
CREATE INDEX IF NOT EXISTS idx_kd_product_category ON knowledge_document (product_category);
CREATE INDEX IF NOT EXISTS idx_kd_scene ON knowledge_document (scene);
CREATE INDEX IF NOT EXISTS idx_kd_intent ON knowledge_document (intent);
CREATE INDEX IF NOT EXISTS idx_kd_status ON knowledge_document (status);

CREATE INDEX IF NOT EXISTS idx_kc_document_type ON knowledge_chunk (document_type);
CREATE INDEX IF NOT EXISTS idx_kc_document_id ON knowledge_chunk (document_id, document_type);

CREATE INDEX IF NOT EXISTS idx_kc_embedding ON knowledge_chunk
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
