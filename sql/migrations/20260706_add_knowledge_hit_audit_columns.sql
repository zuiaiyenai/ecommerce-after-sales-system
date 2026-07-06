ALTER TABLE chat_message
    ADD COLUMN knowledge_query VARCHAR(255) NULL COMMENT '本条AI回复触发的知识检索查询词' AFTER emotion_confidence,
    ADD COLUMN knowledge_retrieval_mode VARCHAR(64) NULL COMMENT '知识检索模式，例如 lexical_hybrid_v1' AFTER knowledge_query,
    ADD COLUMN knowledge_hit_count INT NULL COMMENT '本条AI回复命中的知识条数' AFTER knowledge_retrieval_mode,
    ADD COLUMN knowledge_hits_json JSON NULL COMMENT '命中的知识列表(JSON)' AFTER knowledge_hit_count,
    ADD COLUMN knowledge_trace_json JSON NULL COMMENT '知识检索trace(JSON)' AFTER knowledge_hits_json;
