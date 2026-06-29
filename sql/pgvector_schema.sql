-- ============================================================
-- 知识库向量分块表 —— 存储在 PostgreSQL (pgvector)
-- 用于 RAG 检索：用户问题向量化后，与知识块做相似度搜索
--
-- 数据来源（MySQL 3 张知识表）：
--   product_knowledge  → document_type = 'PRODUCT_KNOWLEDGE'
--   faq                → document_type = 'FAQ'
--   after_sales_policy → document_type = 'AFTER_SALES_POLICY'
-- ============================================================

-- 前置：安装 pgvector 扩展
CREATE EXTENSION IF NOT EXISTS vector;

-- 知识向量分块表
CREATE TABLE IF NOT EXISTS knowledge_chunk
(
    id             BIGSERIAL    PRIMARY KEY,
    document_id    BIGINT       NOT NULL,                    -- 关联 MySQL 来源表的主键
    document_type  VARCHAR(30)  NOT NULL,                    -- 来源表: PRODUCT_KNOWLEDGE / FAQ / AFTER_SALES_POLICY
    chunk_index    INTEGER      NOT NULL,                    -- 分块序号（从 0 开始）
    chunk_text     TEXT         NOT NULL,                    -- 分块文本内容
    embedding      vector(1536) NOT NULL,                    -- 向量维度（取决于 Embedding 模型）
    metadata       JSONB        NULL,                        -- 元数据（标题/版本/商品名等）
    create_time    TIMESTAMP    NOT NULL DEFAULT NOW()       -- 创建时间
);

-- 索引：按来源类型过滤
CREATE INDEX IF NOT EXISTS idx_kc_document_type ON knowledge_chunk (document_type);

-- 索引：按文档查询
CREATE INDEX IF NOT EXISTS idx_kc_document_id ON knowledge_chunk (document_id, document_type);

-- 向量相似度索引（IVFFlat，适合中等数据量）
-- 如果数据量 < 10000 条，用 IVFFlat；数据量大可换 HNSW
CREATE INDEX IF NOT EXISTS idx_kc_embedding ON knowledge_chunk
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- ============================================================
-- 查询示例 1：全库检索 Top-K 相似知识块
-- ============================================================
-- 假设用户问题已向量化为 query_embedding (vector(1536))
--
-- SELECT
--     id,
--     document_id,
--     document_type,
--     chunk_text,
--     1 - (embedding <=> query_embedding) AS similarity
-- FROM knowledge_chunk
-- ORDER BY embedding <=> query_embedding          -- 余弦距离排序
-- LIMIT 5;                                        -- Top-K

-- ============================================================
-- 查询示例 2：只在 FAQ 中检索
-- ============================================================
-- SELECT id, document_id, chunk_text,
--        1 - (embedding <=> query_embedding) AS similarity
-- FROM knowledge_chunk
-- WHERE document_type = 'FAQ'
-- ORDER BY embedding <=> query_embedding
-- LIMIT 5;

-- ============================================================
-- 查询示例 3：在商品知识 + 售后政策中检索
-- ============================================================
-- SELECT id, document_id, document_type, chunk_text,
--        1 - (embedding <=> query_embedding) AS similarity
-- FROM knowledge_chunk
-- WHERE document_type IN ('PRODUCT_KNOWLEDGE', 'AFTER_SALES_POLICY')
-- ORDER BY embedding <=> query_embedding
-- LIMIT 5;
