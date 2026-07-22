package com.ecommerce.aftersales.integration;

import com.ecommerce.aftersales.service.KnowledgeIngestionAsyncService;
import com.ecommerce.aftersales.service.KnowledgePublishService;
import org.junit.jupiter.api.Test;

import java.util.Collections;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

class KnowledgePublishIntegrationTest extends PostgresRagIntegrationSupport {

    @Test
    void commitPublishesOnlyTheFrozenRevisionAndRemovesOldChunks() {
        jdbc.update("""
                INSERT INTO knowledge_document(id, source_type, source_code, merchant_code, title, content,
                    review_status, revision, published_revision, policy_version, valid_from, valid_to)
                VALUES (9401, 'faq', 'publish-1', 'MERCHANT_DEMO', 'title', 'body',
                    'PUBLISHING', 6, 5, 'v1', TIMESTAMP '2026-01-01', TIMESTAMP '2026-12-31')
                """);
        jdbc.update("""
                INSERT INTO knowledge_chunk(document_id, document_type, chunk_index, chunk_text, embedding, revision,
                    product_categories, scenes, intents, heading_path, search_text)
                VALUES (9401, 'faq', 0, 'old', ?::vector, 5, '{phone}', '{quality_issue}', '{refund}', '{title}', 'old')
                """, zeroVector());
        jdbc.update("""
                INSERT INTO knowledge_chunk_draft(document_id, chunk_index, heading_path, chunk_text,
                    product_categories, scenes, intents, classification_source, review_required, revision)
                VALUES (9401, 0, '{title}', 'new', '{phone}', '{quality_issue}', '{refund}', 'RULE', false, 6)
                """);

        new KnowledgePublishService(jdbc, mock(KnowledgeIngestionAsyncService.class))
                .commitPublishedRevision(9401L, 6L, List.of(Collections.nCopies(1024, 0.0d)));

        assertThat(jdbc.queryForObject("SELECT published_revision FROM knowledge_document WHERE id=9401", Long.class)).isEqualTo(6L);
        assertThat(jdbc.queryForObject("SELECT review_status FROM knowledge_document WHERE id=9401", String.class)).isEqualTo("PUBLISHED");
        assertThat(jdbc.queryForList("SELECT chunk_text FROM knowledge_chunk WHERE document_id=9401", String.class)).containsExactly("new");
    }

    private String zeroVector() {
        return "[" + String.join(",", Collections.nCopies(1024, "0")) + "]";
    }
}
