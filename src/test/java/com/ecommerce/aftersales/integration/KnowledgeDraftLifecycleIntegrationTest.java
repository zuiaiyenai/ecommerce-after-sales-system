package com.ecommerce.aftersales.integration;

import com.ecommerce.aftersales.service.KnowledgeDraftService;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class KnowledgeDraftLifecycleIntegrationTest extends PostgresRagIntegrationSupport {

    @Test
    void parsedDraftRequiresAClaimedProcessingRevisionAndKeepsPublishedPointer() {
        jdbc.update("""
                INSERT INTO knowledge_document(id, source_type, source_code, merchant_code, title, content,
                    metadata, review_status, revision, published_revision)
                VALUES (9421, 'faq', 'draft-lifecycle-9421', 'MERCHANT_DEMO', 'title', 'old',
                    '{"ingestionSourceType":"TEXT"}'::jsonb, 'PUBLISHED', 1, 1)
                """);
        KnowledgeDraftService service = new KnowledgeDraftService(jdbc);
        Map<String, Object> parsed = parsedDraft();

        assertThatThrownBy(() -> service.replaceParsedDraft(9421L, 1L, parsed))
                .isInstanceOf(IllegalStateException.class)
                .hasMessage("STALE_DRAFT_TARGET");

        Long targetRevision = jdbc.queryForObject("""
                UPDATE knowledge_document SET revision=revision+1, review_status='PROCESSING'
                WHERE id=9421 AND revision=1 AND review_status='PUBLISHED'
                RETURNING revision
                """, Long.class);
        TransactionTemplate transaction = new TransactionTemplate(new DataSourceTransactionManager(jdbc.getDataSource()));
        transaction.executeWithoutResult(status -> service.replaceParsedDraft(9421L, targetRevision, parsed));

        assertThat(jdbc.queryForObject("SELECT revision FROM knowledge_document WHERE id=9421", Long.class)).isEqualTo(2L);
        assertThat(jdbc.queryForObject("SELECT review_status FROM knowledge_document WHERE id=9421", String.class))
                .isEqualTo("REVIEW_REQUIRED");
        assertThat(jdbc.queryForObject("SELECT published_revision FROM knowledge_document WHERE id=9421", Long.class)).isEqualTo(1L);
        assertThat(jdbc.queryForObject("SELECT revision FROM knowledge_chunk_draft WHERE document_id=9421", Long.class)).isEqualTo(2L);
    }

    private Map<String, Object> parsedDraft() {
        Map<String, Object> chunk = new LinkedHashMap<>();
        chunk.put("chunk_index", 0); chunk.put("heading_path", List.of()); chunk.put("text", "new");
        chunk.put("metadata", Map.of("chunking_strategy", "structured_recursive_v1"));
        chunk.put("product_categories", List.of()); chunk.put("scenes", List.of()); chunk.put("intents", List.of());
        chunk.put("classification_source", "RULE"); chunk.put("review_required", false);
        return Map.of("content", "new", "chunks", List.of(chunk));
    }
}
