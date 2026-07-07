#!/bin/bash
# 售后知识库初始化脚本

set -e

echo "=========================================="
echo "售后知识库初始化"
echo "=========================================="

# 1. 导入知识库数据到PostgreSQL
echo ""
echo "步骤1: 导入知识库文档..."
PGPASSWORD=ecommerce_pgvector psql -h localhost -p 5432 -U ecommerce -d ecommerce_rag -f ../sql/seed_knowledge_base.sql
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
PGPASSWORD=ecommerce_pgvector psql -h localhost -p 5432 -U ecommerce -d ecommerce_rag -c "
SELECT
    source_type,
    COUNT(*) as doc_count
FROM knowledge_document
WHERE status = 1
GROUP BY source_type;
"

PGPASSWORD=ecommerce_pgvector psql -h localhost -p 5432 -U ecommerce -d ecommerce_rag -c "
SELECT COUNT(*) as total_chunks FROM knowledge_chunk;
"

echo ""
echo "=========================================="
echo "知识库初始化完成！"
echo "=========================================="
