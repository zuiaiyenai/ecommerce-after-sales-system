package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.common.KnowledgeRevisionConflictException;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.util.List;
import java.util.Map;
import java.util.LinkedHashMap;
import java.util.Collections;
import java.sql.Timestamp;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.mockito.Mockito.verifyNoInteractions;

class KnowledgePublishServiceTest {

    @Test
    void stalePublishReportsCurrentRevisionAndDoesNotDispatchWorker() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        KnowledgeIngestionAsyncService async = mock(KnowledgeIngestionAsyncService.class);
        when(jdbc.queryForObject(anyString(), eq(Long.class), eq(42L), eq(3L))).thenReturn(null);
        when(jdbc.queryForList(anyString(), eq(42L))).thenReturn(List.of(Map.of("revision", 5L, "review_status", "REVIEW_REQUIRED")));
        KnowledgePublishService service = new KnowledgePublishService(jdbc, async);

        assertThatThrownBy(() -> service.startPublishing(42L, 3L))
                .isInstanceOf(KnowledgeRevisionConflictException.class)
                .hasMessageContaining("知识已被其他操作更新");
        verify(async, never()).publish(42L, 4L);
    }

    @Test
    void commitOnlySwitchesTheFrozenPublishingRevision() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        KnowledgePublishService service = new KnowledgePublishService(jdbc, mock(KnowledgeIngestionAsyncService.class));
        Map<String, Object> draft = new LinkedHashMap<>();
        draft.put("document_id", 42L); draft.put("source_type", "faq"); draft.put("source_code", "FAQ-1");
        draft.put("merchant_code", "MERCHANT_DEMO"); draft.put("title", "title"); draft.put("policy_version", "v1");
        draft.put("chunk_index", 0); draft.put("chunk_text", "body"); draft.put("heading_path", new String[]{"title"});
        draft.put("product_categories", new String[]{"phone"}); draft.put("scenes", new String[]{"quality_issue"});
        draft.put("intents", new String[]{"refund"});
        when(jdbc.queryForList(anyString(), eq(42L), eq(6L), eq(6L))).thenReturn(List.of(draft));
        when(jdbc.update(anyString(), org.mockito.ArgumentMatchers.any(Object[].class))).thenReturn(1);

        service.commitPublishedRevision(42L, 6L, List.of(Collections.nCopies(1024, 0.0d)));

        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        verify(jdbc, org.mockito.Mockito.atLeast(3)).update(sql.capture(), org.mockito.ArgumentMatchers.any(Object[].class));
        assertThat(sql.getAllValues()).anyMatch(value -> value.contains("published_revision") && value.contains("review_status='PUBLISHING'"));
        assertThat(sql.getAllValues()).anyMatch(value -> value.contains("DELETE FROM knowledge_chunk") && value.contains("revision<>?"));
    }

    @Test
    void publishWorkerIsDispatchedOnlyAfterCommit() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        KnowledgeIngestionAsyncService async = mock(KnowledgeIngestionAsyncService.class);
        KnowledgePublishService service = new KnowledgePublishService(jdbc, async);
        Map<String, Object> draft = new LinkedHashMap<>();
        draft.put("source_type", "faq"); draft.put("product_categories", new String[0]);
        draft.put("scenes", new String[0]); draft.put("intents", new String[0]);
        when(jdbc.queryForObject(anyString(), eq(Long.class), eq(42L), eq(5L))).thenReturn(6L);
        when(jdbc.queryForList(anyString(), eq(42L), eq(6L), eq(6L))).thenReturn(List.of(draft));

        TransactionSynchronizationManager.initSynchronization();
        TransactionSynchronizationManager.setActualTransactionActive(true);
        try {
            assertThat(service.startPublishing(42L, 5L)).isEqualTo(6L);
            verifyNoInteractions(async);
            TransactionSynchronizationManager.getSynchronizations().getFirst().afterCommit();
            verify(async).publish(42L, 6L);
        } finally {
            TransactionSynchronizationManager.clearSynchronization();
            TransactionSynchronizationManager.setActualTransactionActive(false);
        }
    }

    @Test
    void lateEmbeddingFailureAffectingNoRowDoesNotMovePublishedRevision() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.update(anyString(), org.mockito.ArgumentMatchers.any(Object[].class))).thenReturn(0);
        KnowledgePublishService service = new KnowledgePublishService(jdbc, mock(KnowledgeIngestionAsyncService.class));

        assertThat(service.markEmbeddingFailed(42L, 6L, "EMBEDDING_FAILED")).isFalse();

        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        verify(jdbc).update(sql.capture(), org.mockito.ArgumentMatchers.any(Object[].class));
        assertThat(sql.getValue()).contains("revision=? AND review_status='PUBLISHING'").doesNotContain("published_revision");
    }

    @Test
    void publishGateRejectsUnconfirmedTagsAndInvalidVersionedPolicyButAllowsEmptyConfirmedTagsAndFaq() {
        List<java.util.function.Consumer<Map<String, Object>>> invalidCases = List.of(
                row -> row.put("product_categories", null), row -> row.put("scenes", null), row -> row.put("intents", null),
                row -> row.put("policy_version", ""),
                row -> row.put("valid_to", Timestamp.valueOf("2026-01-01 00:00:00")),
                row -> row.put("valid_to", Timestamp.valueOf("2025-12-31 23:59:59")));
        for (var mutation : invalidCases) {
            JdbcTemplate jdbc = mock(JdbcTemplate.class);
            KnowledgeIngestionAsyncService async = mock(KnowledgeIngestionAsyncService.class);
            Map<String, Object> row = gateRow("after_sales_policy");
            mutation.accept(row);
            when(jdbc.queryForObject(anyString(), eq(Long.class), eq(42L), eq(5L))).thenReturn(6L);
            when(jdbc.queryForList(anyString(), eq(42L), eq(6L), eq(6L))).thenReturn(List.of(row));
            KnowledgePublishService service = new KnowledgePublishService(jdbc, async, metadataPolicy());

            assertThatThrownBy(() -> service.startPublishing(42L, 5L)).isInstanceOf(com.ecommerce.aftersales.common.BizException.class);
            verifyNoInteractions(async);
        }

        for (String sourceType : List.of("after_sales_policy", "faq")) {
            JdbcTemplate jdbc = mock(JdbcTemplate.class);
            KnowledgeIngestionAsyncService async = mock(KnowledgeIngestionAsyncService.class);
            Map<String, Object> row = gateRow(sourceType);
            if ("faq".equals(sourceType)) { row.remove("policy_version"); row.remove("valid_from"); row.remove("valid_to"); }
            when(jdbc.queryForObject(anyString(), eq(Long.class), eq(42L), eq(5L))).thenReturn(6L);
            when(jdbc.queryForList(anyString(), eq(42L), eq(6L), eq(6L))).thenReturn(List.of(row));
            assertThat(new KnowledgePublishService(jdbc, async, metadataPolicy()).startPublishing(42L, 5L)).isEqualTo(6L);
            verify(async).publish(42L, 6L);
        }
    }

    private Map<String, Object> gateRow(String sourceType) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("source_type", sourceType); row.put("policy_version", "v1");
        row.put("valid_from", Timestamp.valueOf("2026-01-01 00:00:00")); row.put("valid_to", Timestamp.valueOf("2026-01-02 00:00:00"));
        row.put("product_categories", new String[0]); row.put("scenes", new String[0]); row.put("intents", new String[0]);
        return row;
    }

    private KnowledgeMetadataPolicy metadataPolicy() {
        AgentPolicyCatalogService catalog = mock(AgentPolicyCatalogService.class);
        when(catalog.getCatalog()).thenReturn(Map.of("merchants", Map.of("MERCHANT_DEMO", Map.of())));
        when(catalog.getMerchantPolicy(org.mockito.ArgumentMatchers.any())).thenReturn(Map.of("service_policy", Map.of("policy_version", "v1")));
        return new KnowledgeMetadataPolicy(catalog);
    }
}
