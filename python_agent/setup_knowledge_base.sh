#!/bin/bash
# 售后知识库初始化脚本

set -e

PGVECTOR_HOST="${PGVECTOR_HOST:-127.0.0.1}"
PGVECTOR_PORT="${PGVECTOR_PORT:-5432}"
PGVECTOR_DATABASE="${PGVECTOR_DATABASE:-after_sales_rag}"
PGVECTOR_USERNAME="${PGVECTOR_USERNAME:-postgres}"
export PGPASSWORD="${PGVECTOR_PASSWORD:-local-dev-password}"
PSQL=(psql -h "$PGVECTOR_HOST" -p "$PGVECTOR_PORT" -U "$PGVECTOR_USERNAME" -d "$PGVECTOR_DATABASE")

echo "=========================================="
echo "售后知识库初始化"
echo "=========================================="

# 1. 导入知识库数据到PostgreSQL
echo ""
echo "步骤1: 导入知识库文档..."
"${PSQL[@]}" -f ../sql/seed_knowledge_base.sql
echo "✓ 知识库文档导入完成"

# 2. 生成向量embeddings
echo ""
echo "步骤2: 生成向量embeddings..."
echo "注意：需要配置DASHSCOPE_API_KEY环境变量"
python ingest_pgvector_knowledge.py
echo "✓ 向量embeddings生成完成"

# 3. 查看结果
echo ""
echo "步骤3: 查看知识库统计..."
"${PSQL[@]}" -c "
SELECT
    source_type,
    COUNT(*) as doc_count
FROM knowledge_document
WHERE status = 1
GROUP BY source_type;
"

"${PSQL[@]}" -c "
SELECT COUNT(*) as total_chunks FROM knowledge_chunk;
"

echo ""
echo "=========================================="
echo "知识库初始化完成！"
echo "=========================================="
