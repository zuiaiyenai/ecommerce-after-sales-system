package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.dto.KnowledgeDraftDtos.DraftChunkResponse;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class KnowledgeDraftServiceTest {

    @Test
    void draftChunkResponseKeepsLongIdAsStringAtTheApiBoundary() {
        DraftChunkResponse response = new DraftChunkResponse(
                9007199254740993L, 0, List.of("Refund"), 1, "policy text",
                List.of("headphone"), List.of("quality_issue"), List.of("refund"),
                "RULE", new BigDecimal("0.9500"), "matched policy", false, 1L);

        assertThat(response.chunkId()).isEqualTo(9007199254740993L);
        assertThat(response.reviewRequired()).isFalse();
    }

    @Test
    void deletedDocumentsAreExcludedFromStatusAndDraftQueries() {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        KnowledgeDraftService service = new KnowledgeDraftService(jdbcTemplate);
        when(jdbcTemplate.query(anyString(), any(RowMapper.class), any(Object[].class))).thenReturn(List.of());

        assertThatThrownBy(() -> service.ingestionStatus(42L))
                .isInstanceOf(com.ecommerce.aftersales.common.BizException.class);
        assertThat(service.draft(42L)).isEmpty();

        org.mockito.ArgumentCaptor<String> sql = org.mockito.ArgumentCaptor.forClass(String.class);
        org.mockito.Mockito.verify(jdbcTemplate, org.mockito.Mockito.times(2))
                .query(sql.capture(), any(RowMapper.class), any(Object[].class));
        assertThat(sql.getAllValues().get(0)).contains("COALESCE(metadata ->> 'deleted', 'false') <> 'true'");
        assertThat(sql.getAllValues().get(1)).contains("COALESCE(kd.metadata ->> 'deleted', 'false') <> 'true'");
    }

    @Test
    void staleRevisionOrStatusCannotReplaceDrafts() {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        KnowledgeDraftService service = new KnowledgeDraftService(jdbcTemplate);
        when(jdbcTemplate.queryForList(anyString(), any(Object[].class))).thenReturn(List.of());

        assertThatThrownBy(() -> service.replaceParsedDraft(42L, 7L, parsedDraft()))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("STALE_DRAFT_TARGET");
    }

    @Test
    void chunkInsertFailurePropagatesSoTheDraftReplacementTransactionRollsBack() {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        KnowledgeDraftService service = new KnowledgeDraftService(jdbcTemplate);
        when(jdbcTemplate.queryForList(anyString(), any(Object[].class))).thenReturn(List.of(Map.of("id", 42L)));
        when(jdbcTemplate.update(anyString(), any(Object[].class))).thenAnswer(invocation -> {
            String sql = invocation.getArgument(0, String.class);
            if (sql.contains("INSERT INTO knowledge_chunk_draft")) throw new IllegalStateException("insert failed");
            return 1;
        });

        assertThatThrownBy(() -> service.replaceParsedDraft(42L, 7L, parsedDraft()))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("insert failed");
    }

    @Test
    void conditionalCompletionMustAffectExactlyOneRow() {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        KnowledgeDraftService service = new KnowledgeDraftService(jdbcTemplate);
        when(jdbcTemplate.queryForList(anyString(), any(Object[].class))).thenReturn(List.of(Map.of("id", 42L)));
        when(jdbcTemplate.update(anyString(), any(Object[].class))).thenAnswer(invocation ->
                invocation.getArgument(0, String.class).contains("SET content") ? 0 : 1);

        assertThatThrownBy(() -> service.replaceParsedDraft(42L, 7L, parsedDraft()))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("STALE_DRAFT_TARGET");
    }

    private Map<String, Object> parsedDraft() {
        Map<String, Object> parsed = new LinkedHashMap<>();
        parsed.put("content", "draft content");
        parsed.put("chunks", List.of(Map.of(
                "chunk_index", 0,
                "heading_path", List.of("Refund"),
                "text", "draft content",
                "classification_source", "RULE",
                "review_required", false
        )));
        return parsed;
    }
}
