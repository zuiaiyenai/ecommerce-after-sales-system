-- Canonical UTF-8 demo after-sales catalog.
-- The JSON file is mounted beside this script as
-- /docker-entrypoint-initdb.d/04-after-sales-knowledge-v2.json.
-- Embeddings are intentionally created by the normal Java/Python knowledge
-- lifecycle after PostgreSQL initialization.

WITH catalog AS (
    SELECT pg_read_file(
        '/docker-entrypoint-initdb.d/04-after-sales-knowledge-v2.json'
    )::jsonb AS payload
),
documents AS (
    SELECT
        catalog.payload,
        jsonb_array_elements(catalog.payload -> 'documents') AS document
    FROM catalog
)
INSERT INTO knowledge_document (
    source_type,
    source_code,
    merchant_code,
    title,
    content,
    product_category,
    scene,
    intent,
    policy_version,
    tags,
    metadata,
    status,
    valid_from,
    valid_to,
    review_status,
    revision,
    published_revision
)
SELECT
    document ->> 'source_type',
    document ->> 'source_code',
    payload ->> 'merchant_code',
    document ->> 'title',
    document ->> 'content',
    NULLIF(document ->> 'product_category', ''),
    NULLIF(document ->> 'scene', ''),
    NULLIF(document ->> 'intent', ''),
    CASE
        WHEN document ->> 'source_type' IN (
            'after_sales_policy',
            'refund_policy',
            'exchange_rule'
        )
        THEN payload ->> 'policy_version'
        ELSE NULL
    END,
    document -> 'tags',
    jsonb_build_object(
        'knowledgeBaseVersion', payload ->> 'knowledge_base_version',
        'contentLanguage', 'zh-CN',
        'managedBy', 'versioned-knowledge-catalog'
    ),
    1,
    CASE
        WHEN document ->> 'source_type' IN (
            'after_sales_policy',
            'refund_policy',
            'exchange_rule'
        )
        THEN (payload ->> 'valid_from')::timestamptz
        ELSE NULL
    END,
    CASE
        WHEN document ->> 'source_type' IN (
            'after_sales_policy',
            'refund_policy',
            'exchange_rule'
        )
        THEN (payload ->> 'valid_to')::timestamptz
        ELSE NULL
    END,
    'PUBLISHED',
    1,
    NULL
FROM documents
ON CONFLICT (source_type, source_code, merchant_code) DO UPDATE SET
    title = EXCLUDED.title,
    content = EXCLUDED.content,
    product_category = EXCLUDED.product_category,
    scene = EXCLUDED.scene,
    intent = EXCLUDED.intent,
    policy_version = EXCLUDED.policy_version,
    tags = EXCLUDED.tags,
    metadata = COALESCE(knowledge_document.metadata, '{}'::jsonb)
        || EXCLUDED.metadata,
    status = EXCLUDED.status,
    valid_from = EXCLUDED.valid_from,
    valid_to = EXCLUDED.valid_to,
    updated_at = NOW();

WITH catalog AS (
    SELECT pg_read_file(
        '/docker-entrypoint-initdb.d/04-after-sales-knowledge-v2.json'
    )::jsonb AS payload
),
disabled AS (
    SELECT
        catalog.payload ->> 'merchant_code' AS merchant_code,
        jsonb_array_elements_text(
            catalog.payload -> 'disabled_source_codes'
        ) AS source_code,
        catalog.payload ->> 'knowledge_base_version' AS version
    FROM catalog
)
UPDATE knowledge_document AS document
SET status = 0,
    metadata = COALESCE(document.metadata, '{}'::jsonb)
        || jsonb_build_object(
            'supersededByKnowledgeBaseVersion', disabled.version,
            'supersededReason',
            'merged-into-structured-category-or-evidence-knowledge'
        ),
    updated_at = NOW()
FROM disabled
WHERE document.merchant_code = disabled.merchant_code
  AND document.source_code = disabled.source_code;
