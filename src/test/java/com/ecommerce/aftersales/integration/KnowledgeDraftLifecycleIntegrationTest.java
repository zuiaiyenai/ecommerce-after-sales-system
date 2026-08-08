package com.ecommerce.aftersales.integration;

import com.ecommerce.aftersales.config.KnowledgeUploadProperties;
import com.ecommerce.aftersales.service.KnowledgeDraftService;
import com.ecommerce.aftersales.service.KnowledgeIngestionAsyncService;
import com.ecommerce.aftersales.service.KnowledgeMetadataPolicy;
import com.ecommerce.aftersales.service.KnowledgeService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;

class KnowledgeDraftLifecycleIntegrationTest extends PostgresRagIntegrationSupport {

    @TempDir
    Path tempDir;

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

    @Test
    void syncCanonicalizesLegacyBlankAndMixedCaseSourceMarkersBeforeClaiming() throws Exception {
        jdbc.update("""
                INSERT INTO knowledge_document(id, source_type, source_code, merchant_code, title, content,
                    metadata, review_status, revision, published_revision)
                VALUES
                    (9422, 'faq', 'legacy-text-9422', 'MERCHANT_DEMO', 'legacy null', 'body',
                        NULL, 'PUBLISHED', 1, 1),
                    (9423, 'faq', 'legacy-text-9423', 'MERCHANT_DEMO', 'legacy blank', 'body',
                        '{"ingestionSourceType":"   "}'::jsonb, 'PUBLISHED', 1, 1),
                    (9424, 'faq', 'legacy-file-9424', 'MERCHANT_DEMO', 'mixed file', '',
                        '{"ingestionSourceType":" fIlE "}'::jsonb, 'PUBLISHED', 1, 1)
                """);
        KnowledgeIngestionAsyncService worker = mock(KnowledgeIngestionAsyncService.class);
        KnowledgeService service = new KnowledgeService(
                jdbc,
                worker,
                mock(KnowledgeMetadataPolicy.class),
                new KnowledgeDraftService(jdbc),
                tempDir.toString(),
                new KnowledgeUploadProperties());
        TransactionTemplate transaction = new TransactionTemplate(
                new DataSourceTransactionManager(jdbc.getDataSource()));

        transaction.executeWithoutResult(status -> {
            assertThat(service.syncKnowledge(9422L)).containsEntry("documentId", "9422");
            assertThat(service.syncKnowledge(9423L)).containsEntry("documentId", "9423");
            assertThat(service.syncKnowledge(9424L)).containsEntry("documentId", "9424");
            verifyNoInteractions(worker);
            for (long id : List.of(9422L, 9423L, 9424L)) {
                assertThat(jdbc.queryForObject(
                        "SELECT revision FROM knowledge_document WHERE id=?", Long.class, id)).isEqualTo(2L);
                assertThat(jdbc.queryForObject(
                        "SELECT review_status FROM knowledge_document WHERE id=?", String.class, id)).isEqualTo("PROCESSING");
                assertThat(jdbc.queryForObject(
                        "SELECT published_revision FROM knowledge_document WHERE id=?", Long.class, id)).isEqualTo(1L);
            }
        });

        verify(worker).reprocessDocument(9422L, 2L);
        verify(worker).reprocessDocument(9423L, 2L);
        verify(worker).reprocessDocument(9424L, 2L);
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
