-- Backfill structured RAG filter columns from legacy JSON metadata when the
-- value already exists there. Do not guess category, scene, intent or policy
-- version for documents without an explicit source value.

UPDATE knowledge_document
SET product_category = COALESCE(
        product_category,
        NULLIF(metadata ->> 'product_category', ''),
        NULLIF(metadata ->> 'productCategory', '')
    ),
    scene = COALESCE(scene, NULLIF(metadata ->> 'scene', '')),
    intent = COALESCE(intent, NULLIF(metadata ->> 'intent', '')),
    policy_version = COALESCE(
        policy_version,
        NULLIF(metadata ->> 'policy_version', ''),
        NULLIF(metadata ->> 'policyVersion', '')
    ),
    tags = COALESCE(
        tags,
        CASE
            WHEN jsonb_typeof(metadata -> 'tags') = 'array' THEN metadata -> 'tags'
            ELSE NULL
        END
    ),
    updated_at = NOW()
WHERE (product_category IS NULL AND COALESCE(
           NULLIF(metadata ->> 'product_category', ''),
           NULLIF(metadata ->> 'productCategory', '')
       ) IS NOT NULL)
   OR (scene IS NULL AND NULLIF(metadata ->> 'scene', '') IS NOT NULL)
   OR (intent IS NULL AND NULLIF(metadata ->> 'intent', '') IS NOT NULL)
   OR (policy_version IS NULL AND COALESCE(
           NULLIF(metadata ->> 'policy_version', ''),
           NULLIF(metadata ->> 'policyVersion', '')
       ) IS NOT NULL)
   OR (tags IS NULL AND jsonb_typeof(metadata -> 'tags') = 'array');

-- Canonicalize legacy aliases after safe backfill. NULL is the only canonical
-- representation for a dimension that applies to all categories/scenes.
UPDATE knowledge_document
SET product_category = CASE LOWER(product_category)
        WHEN 'general' THEN NULL
        WHEN '通用' THEN NULL
        WHEN '数码' THEN 'digital'
        WHEN '手机' THEN 'phone'
        WHEN '耳机' THEN 'headphone'
        WHEN '蓝牙耳机' THEN 'headphone'
        WHEN '服装' THEN 'apparel'
        WHEN '日用' THEN 'daily'
        WHEN '鞋靴' THEN 'shoes'
        WHEN '食品' THEN 'food'
        WHEN '家居' THEN 'home'
        WHEN '其他' THEN 'other'
        ELSE product_category
    END,
    scene = CASE LOWER(scene)
        WHEN 'product_damage' THEN 'damage'
        WHEN 'logistics_damage' THEN 'logistics_issue'
        ELSE scene
    END,
    intent = CASE LOWER(intent)
        WHEN 'resend' THEN 'reissue'
        ELSE intent
    END,
    updated_at = NOW()
WHERE product_category IN ('general', '通用', '数码', '手机', '耳机', '蓝牙耳机', '服装', '日用', '鞋靴', '食品', '家居', '其他')
   OR scene IN ('product_damage', 'logistics_damage')
   OR intent = 'resend';

UPDATE knowledge_chunk kc
SET metadata = COALESCE(kc.metadata, '{}'::jsonb) || jsonb_build_object(
    'title', kd.title,
    'source_type', kd.source_type,
    'source_code', kd.source_code,
    'merchant_code', kd.merchant_code,
    'product_category', kd.product_category,
    'scene', kd.scene,
    'intent', kd.intent,
    'policy_version', kd.policy_version,
    'tags', COALESCE(kd.tags, '[]'::jsonb)
)
FROM knowledge_document kd
WHERE kc.document_id = kd.id;
