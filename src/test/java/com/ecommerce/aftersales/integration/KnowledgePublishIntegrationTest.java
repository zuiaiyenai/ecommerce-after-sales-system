package com.ecommerce.aftersales.integration;

import com.ecommerce.aftersales.service.KnowledgeIngestionAsyncService;
import com.ecommerce.aftersales.service.KnowledgePublishService;
import org.junit.jupiter.api.Test;

import java.util.Collections;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import static org.assertj.core.api.Assertions.assertThatThrownBy;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

class KnowledgePublishIntegrationTest extends PostgresRagIntegrationSupport {

    @Test
    void staleFinalSwitchRollsBackInsertedTargetChunksAndKeepsPublishedRevision() {
        insertPublishingDocument(9411, 6, 5);
        insertOldChunk(9411, 5, "old");
        insertDraft(9411, 6, "new");
        jdbc.update("UPDATE knowledge_document SET review_status='REVIEW_REQUIRED', revision=7 WHERE id=9411");

        assertThatThrownBy(() -> new KnowledgePublishService(jdbc, mock(KnowledgeIngestionAsyncService.class))
                .commitPublishedRevision(9411L, 6L, List.of(Collections.nCopies(1024, 0.0d))))
                .isInstanceOf(IllegalStateException.class);

        assertThat(jdbc.queryForObject("SELECT published_revision FROM knowledge_document WHERE id=9411", Long.class)).isEqualTo(5L);
        assertThat(jdbc.queryForList("SELECT chunk_text FROM knowledge_chunk WHERE document_id=9411", String.class)).containsExactly("old");
    }

    @Test
    void embeddingFailureKeepsOldPublishedChunksVisibleThroughView() {
        insertPublishingDocument(9412, 6, 5);
        insertOldChunk(9412, 5, "old");
        boolean changed = new KnowledgePublishService(jdbc, mock(KnowledgeIngestionAsyncService.class))
                .markEmbeddingFailed(9412L, 6L, "TIMEOUT");

        assertThat(changed).isTrue();
        assertThat(jdbc.queryForObject("SELECT published_revision FROM knowledge_document WHERE id=9412", Long.class)).isEqualTo(5L);
        assertThat(jdbc.queryForList("SELECT chunk_text FROM published_knowledge_chunk WHERE document_id=9412", String.class)).containsExactly("old");
    }

    @Test
    void lateTargetCannotOverwriteNewerRevisionOrPublishedPointer() {
        insertPublishingDocument(9413, 7, 5);
        insertOldChunk(9413, 5, "old");
        new KnowledgePublishService(jdbc, mock(KnowledgeIngestionAsyncService.class))
                .markEmbeddingFailed(9413L, 6L, "LATE");

        assertThat(jdbc.queryForObject("SELECT revision FROM knowledge_document WHERE id=9413", Long.class)).isEqualTo(7L);
        assertThat(jdbc.queryForObject("SELECT review_status FROM knowledge_document WHERE id=9413", String.class)).isEqualTo("PUBLISHING");
        assertThat(jdbc.queryForObject("SELECT published_revision FROM knowledge_document WHERE id=9413", Long.class)).isEqualTo(5L);
        assertThat(jdbc.queryForList("SELECT chunk_text FROM published_knowledge_chunk WHERE document_id=9413", String.class)).containsExactly("old");
    }

    @Test
    void concurrentCommitsAllowOnlyOneWinner() throws Exception {
        insertPublishingDocument(9414, 6, 5);
        insertOldChunk(9414, 5, "old");
        insertDraft(9414, 6, "new");
        CountDownLatch ready = new CountDownLatch(2);
        CountDownLatch start = new CountDownLatch(1);
        ExecutorService executor = Executors.newFixedThreadPool(2);
        TransactionTemplate tx = new TransactionTemplate(new DataSourceTransactionManager(jdbc.getDataSource()));
        List<Future<Boolean>> futures = List.of(executor.submit(() -> commitAfterBarrier(ready, start, tx)),
                executor.submit(() -> commitAfterBarrier(ready, start, tx)));
        ready.await(); start.countDown();
        long winners = 0;
        for (Future<Boolean> future : futures) if (future.get()) winners++;
        executor.shutdownNow();
        assertThat(winners).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT published_revision FROM knowledge_document WHERE id=9414", Long.class)).isEqualTo(6L);
    }

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

    private void insertPublishingDocument(long id, long revision, long publishedRevision) {
        jdbc.update("""
                INSERT INTO knowledge_document(id, source_type, source_code, merchant_code, title, content,
                review_status, revision, published_revision, policy_version, valid_from, valid_to)
                VALUES (?, 'faq', ?, 'MERCHANT_DEMO', 'title', 'body', 'PUBLISHING', ?, ?, 'v1',
                TIMESTAMP '2026-01-01', TIMESTAMP '2026-12-31')
                """, id, "publish-" + id, revision, publishedRevision);
    }
    private void insertOldChunk(long id, long revision, String text) {
        jdbc.update("""
                INSERT INTO knowledge_chunk(document_id, document_type, chunk_index, chunk_text, embedding, revision,
                product_categories, scenes, intents, heading_path, search_text)
                VALUES (?, 'faq', 0, ?, ?::vector, ?, '{phone}', '{quality_issue}', '{refund}', '{title}', ?)
                """, id, text, zeroVector(), revision, text);
    }
    private void insertDraft(long id, long revision, String text) {
        jdbc.update("""
                INSERT INTO knowledge_chunk_draft(document_id, chunk_index, heading_path, chunk_text,
                product_categories, scenes, intents, classification_source, review_required, revision)
                VALUES (?, 0, '{title}', ?, '{phone}', '{quality_issue}', '{refund}', 'RULE', false, ?)
                """, id, text, revision);
    }

    private boolean commitAfterBarrier(CountDownLatch ready, CountDownLatch start, TransactionTemplate tx) throws Exception {
        ready.countDown(); start.await();
        try {
            return Boolean.TRUE.equals(tx.execute(status -> {
                new KnowledgePublishService(jdbc, mock(KnowledgeIngestionAsyncService.class))
                        .commitPublishedRevision(9414L, 6L, List.of(Collections.nCopies(1024, 0.0d)));
                return true;
            }));
        } catch (RuntimeException expectedLoser) { return false; }
    }
}
