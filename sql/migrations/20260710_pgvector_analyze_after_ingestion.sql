-- Run after a large knowledge ingestion or reindex so PostgreSQL refreshes
-- statistics used by scoped pgvector retrieval planning.
ANALYZE knowledge_document;
ANALYZE knowledge_chunk;
