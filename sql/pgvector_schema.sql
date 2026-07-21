-- PostgreSQL pgvector schema for Python-side RAG.
-- Source data is ingested from MySQL knowledge tables into vector chunks.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

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
    valid_from       TIMESTAMP NULL,
    valid_to         TIMESTAMP NULL,
    review_status    VARCHAR(32) NOT NULL DEFAULT 'PUBLISHED',
    content_hash     CHAR(64) NULL,
    revision         BIGINT NOT NULL DEFAULT 1,
    published_revision BIGINT NULL,
    created_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_knowledge_document_valid_window
        CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from),
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
    revision      BIGINT NOT NULL DEFAULT 1,
    product_categories TEXT[] NULL,
    scenes        TEXT[] NULL,
    intents       TEXT[] NULL,
    heading_path  TEXT[] NOT NULL DEFAULT '{}',
    page_number   INTEGER NULL,
    search_text   TEXT NOT NULL DEFAULT '',
    create_time   TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS knowledge_chunk_draft
(
    id                        BIGSERIAL PRIMARY KEY,
    document_id               BIGINT NOT NULL REFERENCES knowledge_document(id) ON DELETE CASCADE,
    chunk_index               INTEGER NOT NULL,
    heading_path              TEXT[] NOT NULL DEFAULT '{}',
    page_number               INTEGER NULL,
    chunk_text                TEXT NOT NULL,
    product_categories        TEXT[] NULL,
    scenes                    TEXT[] NULL,
    intents                   TEXT[] NULL,
    classification_source     VARCHAR(16) NOT NULL,
    classification_confidence NUMERIC(5,4) NULL,
    classification_reason     TEXT NULL,
    review_required           BOOLEAN NOT NULL DEFAULT TRUE,
    revision                  BIGINT NOT NULL,
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_kd_source_type ON knowledge_document (source_type);
CREATE INDEX IF NOT EXISTS idx_kd_merchant_code ON knowledge_document (merchant_code);
CREATE INDEX IF NOT EXISTS idx_kd_product_category ON knowledge_document (product_category);
CREATE INDEX IF NOT EXISTS idx_kd_scene ON knowledge_document (scene);
CREATE INDEX IF NOT EXISTS idx_kd_intent ON knowledge_document (intent);
CREATE INDEX IF NOT EXISTS idx_kd_status ON knowledge_document (status);
CREATE UNIQUE INDEX IF NOT EXISTS uk_kd_active_content_hash
    ON knowledge_document (merchant_code, source_type, content_hash)
    WHERE content_hash IS NOT NULL AND COALESCE(metadata ->> 'deleted', 'false') <> 'true';

CREATE INDEX IF NOT EXISTS idx_kc_document_type ON knowledge_chunk (document_type);
CREATE INDEX IF NOT EXISTS idx_kc_document_id ON knowledge_chunk (document_id, document_type);
CREATE UNIQUE INDEX IF NOT EXISTS uk_kc_document_revision_index
    ON knowledge_chunk (document_id, revision, chunk_index);
CREATE INDEX IF NOT EXISTS idx_kc_product_categories ON knowledge_chunk USING GIN (product_categories);
CREATE INDEX IF NOT EXISTS idx_kc_scenes ON knowledge_chunk USING GIN (scenes);
CREATE INDEX IF NOT EXISTS idx_kc_intents ON knowledge_chunk USING GIN (intents);
CREATE INDEX IF NOT EXISTS idx_kc_search_text_trgm ON knowledge_chunk USING GIN (search_text gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_kc_embedding ON knowledge_chunk
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
