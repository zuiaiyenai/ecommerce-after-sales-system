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

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

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
}
