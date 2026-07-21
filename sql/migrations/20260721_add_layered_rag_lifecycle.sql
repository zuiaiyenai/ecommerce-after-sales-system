BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

ALTER TABLE knowledge_document
    ADD COLUMN IF NOT EXISTS valid_from TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS valid_to TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS review_status VARCHAR(32) NOT NULL DEFAULT 'PUBLISHED',
    ADD COLUMN IF NOT EXISTS content_hash CHAR(64) NULL,
    ADD COLUMN IF NOT EXISTS revision BIGINT NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS published_revision BIGINT NULL;

ALTER TABLE knowledge_document
    DROP CONSTRAINT IF EXISTS ck_knowledge_document_valid_window;

ALTER TABLE knowledge_document
    ADD CONSTRAINT ck_knowledge_document_valid_window
        CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from);

ALTER TABLE knowledge_chunk
    ADD COLUMN IF NOT EXISTS revision BIGINT NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS product_categories TEXT[] NULL,
    ADD COLUMN IF NOT EXISTS scenes TEXT[] NULL,
    ADD COLUMN IF NOT EXISTS intents TEXT[] NULL,
    ADD COLUMN IF NOT EXISTS heading_path TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS page_number INTEGER NULL,
    ADD COLUMN IF NOT EXISTS search_text TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS knowledge_chunk_draft (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES knowledge_document(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    heading_path TEXT[] NOT NULL DEFAULT '{}',
    page_number INTEGER NULL,
    chunk_text TEXT NOT NULL,
    product_categories TEXT[] NULL,
    scenes TEXT[] NULL,
    intents TEXT[] NULL,
    classification_source VARCHAR(16) NOT NULL,
    classification_confidence NUMERIC(5,4) NULL,
    classification_reason TEXT NULL,
    review_required BOOLEAN NOT NULL DEFAULT TRUE,
    revision BIGINT NOT NULL,
    UNIQUE(document_id, chunk_index)
);

UPDATE knowledge_document kd
SET published_revision = 1
WHERE published_revision IS NULL
  AND EXISTS (SELECT 1 FROM knowledge_chunk kc WHERE kc.document_id = kd.id);

UPDATE knowledge_chunk kc
SET product_categories = ARRAY[kd.product_category]
FROM knowledge_document kd
WHERE kc.document_id = kd.id
  AND kc.product_categories IS NULL
  AND kd.product_category IS NOT NULL;

UPDATE knowledge_chunk kc
SET scenes = ARRAY[kd.scene]
FROM knowledge_document kd
WHERE kc.document_id = kd.id
  AND kc.scenes IS NULL
  AND kd.scene IS NOT NULL;

UPDATE knowledge_chunk kc
SET intents = ARRAY[kd.intent]
FROM knowledge_document kd
WHERE kc.document_id = kd.id
  AND kc.intents IS NULL
  AND kd.intent IS NOT NULL;

DO 'DECLARE
    duplicate_keys TEXT;
BEGIN
    SELECT string_agg(
        format(''document_id=%s, revision=%s, chunk_index=%s, count=%s'',
            document_id, revision, chunk_index, duplicate_count),
        ''; '' ORDER BY document_id, revision, chunk_index
    )
    INTO duplicate_keys
    FROM (
        SELECT document_id, revision, chunk_index, count(*) AS duplicate_count
        FROM knowledge_chunk
        GROUP BY document_id, revision, chunk_index
        HAVING count(*) > 1
        ORDER BY document_id, revision, chunk_index
        LIMIT 20
    ) duplicate_chunks;

    IF duplicate_keys IS NOT NULL THEN
        RAISE EXCEPTION ''knowledge_chunk duplicate lifecycle keys: %'', duplicate_keys;
    END IF;
END';

CREATE UNIQUE INDEX IF NOT EXISTS uk_kc_document_revision_index
    ON knowledge_chunk(document_id, revision, chunk_index);
CREATE INDEX IF NOT EXISTS idx_kc_product_categories ON knowledge_chunk USING GIN(product_categories);
CREATE INDEX IF NOT EXISTS idx_kc_scenes ON knowledge_chunk USING GIN(scenes);
CREATE INDEX IF NOT EXISTS idx_kc_intents ON knowledge_chunk USING GIN(intents);
CREATE INDEX IF NOT EXISTS idx_kc_search_text_trgm ON knowledge_chunk USING GIN(search_text gin_trgm_ops);
CREATE UNIQUE INDEX IF NOT EXISTS uk_kd_active_content_hash
    ON knowledge_document(merchant_code, source_type, content_hash)
    WHERE content_hash IS NOT NULL AND COALESCE(metadata ->> 'deleted', 'false') <> 'true';

COMMIT;
