-- Backfill chunk metadata from knowledge_document and add indexes for
-- merchant / source / scene / intent scoped retrieval.

BEGIN;

-- 1. Backfill and normalize chunk metadata from the document table.
UPDATE knowledge_chunk kc
SET metadata = jsonb_strip_nulls(
    COALESCE(kc.metadata, '{}'::jsonb)
    || jsonb_build_object(
        'merchant_code', kd.merchant_code,
        'source_type', kd.source_type,
        'source_code', kd.source_code,
        'title', kd.title,
        'product_category', kd.product_category,
        'scene', kd.scene,
        'intent', kd.intent,
        'policy_version', kd.policy_version,
        'tags', COALESCE(kd.tags, '[]'::jsonb)
    )
)
FROM knowledge_document kd
WHERE kd.id = kc.document_id;

-- 2. Normalize deleted marker on document metadata.
UPDATE knowledge_document
SET metadata = jsonb_set(COALESCE(metadata, '{}'::jsonb), '{deleted}', 'false'::jsonb, true)
WHERE metadata IS NULL OR NOT (metadata ? 'deleted');

-- 3. Indexes for active document filtering and scoped retrieval.
CREATE INDEX IF NOT EXISTS idx_kd_active_scope_lookup
    ON knowledge_document (status, merchant_code, source_type, scene, intent, product_category, policy_version);

CREATE INDEX IF NOT EXISTS idx_kd_metadata_gin
    ON knowledge_document
    USING GIN (metadata);

CREATE INDEX IF NOT EXISTS idx_kc_metadata_gin
    ON knowledge_chunk
    USING GIN (metadata);

CREATE INDEX IF NOT EXISTS idx_kc_document_id_chunk_index
    ON knowledge_chunk (document_id, chunk_index);

COMMIT;
