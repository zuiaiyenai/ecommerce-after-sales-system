package com.ecommerce.aftersales.integration;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.MethodOrderer;
import org.junit.jupiter.api.Order;
import org.junit.jupiter.api.TestMethodOrder;
import org.springframework.dao.DataIntegrityViolationException;

import java.util.Collections;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
class LayeredRagSchemaIntegrationTest extends PostgresRagIntegrationSupport {

    @Test
    @Order(1)
    void onlyPublishedRevisionIsVisibleAndDraftHasNoEmbedding() {
        jdbc.update("""
                INSERT INTO knowledge_document(
                    id, source_type, source_code, merchant_code, title, content,
                    review_status, revision, published_revision
                ) VALUES (9001, 'faq', 'T-1', 'MERCHANT_DEMO', 'title', 'body', 'PROCESSING', 2, 1)
                """);
        jdbc.update("""
                INSERT INTO knowledge_chunk(
                    document_id, document_type, chunk_index, chunk_text, embedding,
                    revision, product_categories, scenes, intents, search_text
                ) VALUES (9001, 'faq', 0, 'old-version', ?::vector, 1, '{}', '{}', '{}', 'old-version')
                """, zeroVector());
        jdbc.update("""
                INSERT INTO knowledge_chunk(
                    document_id, document_type, chunk_index, chunk_text, embedding,
                    revision, product_categories, scenes, intents, search_text
                ) VALUES (9001, 'faq', 0, 'new-version', ?::vector, 2, '{}', '{}', '{}', 'new-version')
                """, zeroVector());

        List<String> visible = jdbc.queryForList("""
                SELECT kc.chunk_text
                FROM knowledge_chunk kc
                JOIN knowledge_document kd ON kd.id = kc.document_id
                WHERE kc.revision = kd.published_revision
                """, String.class);

        assertThat(visible).contains("old-version").doesNotContain("new-version");
        assertThat(columns("knowledge_chunk_draft")).doesNotContain("embedding");
    }

    @Test
    @Order(2)
    void migrationBackfillsExistingChunksAndEnforcesValidWindow() throws Exception {
        createLegacyTables();
        jdbc.update("""
                INSERT INTO knowledge_document(
                    id, source_type, source_code, merchant_code, title, content, product_category, scene, intent
                ) VALUES (8001, 'faq', 'legacy-1', 'MERCHANT_DEMO', 'legacy knowledge', 'legacy body', 'electronics', 'return', 'refund')
                """);
        jdbc.update("""
                INSERT INTO knowledge_chunk(document_id, document_type, chunk_index, chunk_text, embedding)
                VALUES (8001, 'faq', 0, 'legacy chunk', ?::vector)
                """, zeroVector());

        executeLifecycleMigration();
        executeLifecycleMigration();

        assertThat(jdbc.queryForObject(
                "SELECT published_revision FROM knowledge_document WHERE id = 8001", Long.class)).isEqualTo(1L);
        assertThat(jdbc.queryForObject(
                "SELECT array_to_string(product_categories, ',') FROM knowledge_chunk WHERE document_id = 8001", String.class))
                .isEqualTo("electronics");
        assertThat(jdbc.queryForObject(
                "SELECT array_to_string(scenes, ',') FROM knowledge_chunk WHERE document_id = 8001", String.class))
                .isEqualTo("return");
        assertThat(jdbc.queryForObject(
                "SELECT array_to_string(intents, ',') FROM knowledge_chunk WHERE document_id = 8001", String.class))
                .isEqualTo("refund");
        assertThatThrownBy(() -> jdbc.update("""
                INSERT INTO knowledge_document(
                    id, source_type, source_code, merchant_code, title, content, valid_from, valid_to
                ) VALUES (8002, 'faq', 'invalid-window', 'MERCHANT_DEMO', 'invalid window', 'body',
                    TIMESTAMP '2026-07-22 00:00:00', TIMESTAMP '2026-07-21 00:00:00')
                """))
                .isInstanceOf(DataIntegrityViolationException.class);
    }

    @Test
    @Order(3)
    void migrationRollsBackWhenLegacyChunkKeysConflict() {
        createLegacyTables();
        jdbc.update("""
                INSERT INTO knowledge_document(id, source_type, source_code, merchant_code, title, content)
                VALUES (8101, 'faq', 'legacy-duplicate', 'MERCHANT_DEMO', 'legacy', 'body')
                """);
        jdbc.update("""
                INSERT INTO knowledge_chunk(document_id, document_type, chunk_index, chunk_text, embedding)
                VALUES (8101, 'faq', 0, 'first duplicate', ?::vector)
                """, zeroVector());
        jdbc.update("""
                INSERT INTO knowledge_chunk(document_id, document_type, chunk_index, chunk_text, embedding)
                VALUES (8101, 'faq', 0, 'second duplicate', ?::vector)
                """, zeroVector());

        assertThatThrownBy(PostgresRagIntegrationSupport::executeLifecycleMigration)
                .isInstanceOf(RuntimeException.class)
                .hasStackTraceContaining("knowledge_chunk duplicate lifecycle keys")
                .hasStackTraceContaining("document_id=8101, revision=1, chunk_index=0, count=2");

        assertThat(columns("knowledge_document")).doesNotContain("review_status");
        assertThat(jdbc.queryForObject(
                "SELECT count(*) FROM knowledge_chunk WHERE document_id = 8101", Integer.class)).isEqualTo(2);
    }

    private void createLegacyTables() {
        jdbc.execute("DROP TABLE IF EXISTS knowledge_chunk_draft");
        jdbc.execute("DROP TABLE IF EXISTS knowledge_chunk");
        jdbc.execute("DROP TABLE IF EXISTS knowledge_document");
        jdbc.execute("""
                CREATE TABLE knowledge_document (
                    id BIGSERIAL PRIMARY KEY,
                    source_type VARCHAR(40) NOT NULL,
                    source_code VARCHAR(100) NOT NULL,
                    merchant_code VARCHAR(50) NOT NULL DEFAULT 'MERCHANT_DEMO',
                    title VARCHAR(300) NOT NULL,
                    content TEXT NOT NULL,
                    product_category VARCHAR(100) NULL,
                    scene VARCHAR(64) NULL,
                    intent VARCHAR(64) NULL,
                    policy_version VARCHAR(64) NULL,
                    tags JSONB NULL,
                    metadata JSONB NULL,
                    status SMALLINT NOT NULL DEFAULT 1,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    UNIQUE (source_type, source_code, merchant_code)
                )
                """);
        jdbc.execute("""
                CREATE TABLE knowledge_chunk (
                    id BIGSERIAL PRIMARY KEY,
                    document_id BIGINT NOT NULL REFERENCES knowledge_document(id) ON DELETE CASCADE,
                    document_type VARCHAR(30) NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    chunk_text TEXT NOT NULL,
                    embedding vector(1024) NOT NULL,
                    metadata JSONB NULL,
                    create_time TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """);
    }

    private String zeroVector() {
        return "[" + String.join(",", Collections.nCopies(1024, "0")) + "]";
    }

    private List<String> columns(String table) {
        return jdbc.queryForList("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = ?
                ORDER BY ordinal_position
                """, String.class, table);
    }
}
