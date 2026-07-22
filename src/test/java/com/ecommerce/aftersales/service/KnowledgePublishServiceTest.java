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
import org.postgresql.util.PGobject;

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
    void publishedChunkKeepsOriginalTextAndMergesPgObjectStructuralMetadataUnderAuthoritativeFacts() throws Exception {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        KnowledgePublishService service = new KnowledgePublishService(jdbc, mock(KnowledgeIngestionAsyncService.class));
        Map<String, Object> draft = new LinkedHashMap<>();
        draft.put("document_id", 42L); draft.put("source_type", "after_sales_policy");
        draft.put("source_code", "POLICY-2026"); draft.put("merchant_code", "MERCHANT_DEMO");
        draft.put("title", "平台售后退款规则"); draft.put("policy_version", "v3");
        draft.put("chunk_index", 5); draft.put("chunk_text", "body");
        draft.put("heading_path", new String[]{"退款政策", "举证要求"}); draft.put("page_number", 3);
        draft.put("product_categories", new String[]{"phone"}); draft.put("scenes", new String[]{"quality_issue"});
        draft.put("intents", new String[]{"refund"});
        draft.put("chunk_metadata", jsonb("{\"page_start\":3,\"page_end\":4,\"content_types\":[\"paragraph\",\"list\"],"
                + "\"estimated_tokens\":2,\"chunking_strategy\":\"structured_recursive_v1\","
                + "\"source_type\":\"pdf\",\"merchant_code\":\"UNTRUSTED\",\"unknown\":\"drop-me\"}"));
        draft.put("document_metadata", jsonb("{\"ingestionSourceType\":\"FILE\",\"fileName\":\"policy.pdf\"}"));
        when(jdbc.queryForList(anyString(), eq(42L), eq(6L), eq(6L))).thenReturn(List.of(draft));
        when(jdbc.update(anyString(), org.mockito.ArgumentMatchers.any(Object[].class))).thenReturn(1);

        service.commitPublishedRevision(42L, 6L, List.of(Collections.nCopies(1024, 0.0d)));

        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<Object[]> arguments = ArgumentCaptor.forClass(Object[].class);
        verify(jdbc, org.mockito.Mockito.atLeast(3)).update(sql.capture(), arguments.capture());
        int insert = java.util.stream.IntStream.range(0, sql.getAllValues().size())
                .filter(index -> sql.getAllValues().get(index).contains("INSERT INTO knowledge_chunk"))
                .findFirst().orElseThrow();
        Object[] published = arguments.getAllValues().get(insert);
        assertThat(published[3]).isEqualTo("body");
        assertThat(String.valueOf(published[11]))
                .contains("文档：平台售后退款规则", "章节：退款政策 > 举证要求", "位置：第 3-4 页")
                .contains("来源：policy.pdf / POLICY-2026", "商品分类：phone", "场景：quality_issue", "意图：refund")
                .endsWith("body");
        assertThat(String.valueOf(published[12]))
                .contains("\"page_end\":4", "\"pageNumber\":3", "\"pageStart\":3", "\"pageEnd\":4")
                .contains("\"source_type\":\"after_sales_policy\"", "\"source_format\":\"pdf\"")
                .contains("\"product_categories\":[\"phone\"]")
                .doesNotContain("UNTRUSTED", "drop-me");
    }

    @Test
    void publishedMetadataInfersTextAndMarkdownSourceFormatsWithoutChangingBusinessSourceType() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        KnowledgePublishService service = new KnowledgePublishService(jdbc, mock(KnowledgeIngestionAsyncService.class));
        Map<String, Object> text = publishRow(0, "{\"ingestionSourceType\":\"TEXT\"}");
        Map<String, Object> markdown = publishRow(1, "{\"ingestionSourceType\":\"FILE\",\"fileName\":\"policy.md\"}");
        when(jdbc.queryForList(anyString(), eq(42L), eq(6L), eq(6L))).thenReturn(List.of(text, markdown));
        when(jdbc.update(anyString(), org.mockito.ArgumentMatchers.any(Object[].class))).thenReturn(1);

        service.commitPublishedRevision(42L, 6L, List.of(
                Collections.nCopies(1024, 0.0d), Collections.nCopies(1024, 0.0d)));

        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<Object[]> arguments = ArgumentCaptor.forClass(Object[].class);
        verify(jdbc, org.mockito.Mockito.atLeast(4)).update(sql.capture(), arguments.capture());
        List<String> metadata = java.util.stream.IntStream.range(0, sql.getAllValues().size())
                .filter(index -> sql.getAllValues().get(index).contains("INSERT INTO knowledge_chunk"))
                .mapToObj(index -> String.valueOf(arguments.getAllValues().get(index)[12]))
                .toList();
        assertThat(metadata).anyMatch(value -> value.contains("\"source_format\":\"text\""))
                .anyMatch(value -> value.contains("\"source_format\":\"markdown\""))
                .allMatch(value -> value.contains("\"source_type\":\"after_sales_policy\""));
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

    private Map<String, Object> publishRow(int chunkIndex, Object documentMetadata) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("document_id", 42L); row.put("source_type", "after_sales_policy"); row.put("source_code", "POLICY-42");
        row.put("merchant_code", "MERCHANT_DEMO"); row.put("title", "Policy"); row.put("revision", 6L);
        row.put("chunk_index", chunkIndex); row.put("chunk_text", "body-" + chunkIndex); row.put("heading_path", new String[0]);
        row.put("product_categories", new String[0]); row.put("scenes", new String[0]); row.put("intents", new String[0]);
        row.put("chunk_metadata", Map.of()); row.put("document_metadata", documentMetadata);
        return row;
    }

    private PGobject jsonb(String value) throws Exception {
        PGobject object = new PGobject();
        object.setType("jsonb");
        object.setValue(value);
        return object;
    }
}
