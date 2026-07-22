package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.common.KnowledgeRevisionConflictException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.sql.Array;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class KnowledgePublishService {
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
    @Qualifier("pgJdbcTemplate") private final JdbcTemplate pgJdbcTemplate;
    private final KnowledgeIngestionAsyncService asyncService;

    @Transactional(transactionManager = "pgTransactionManager")
    public long startPublishing(Long documentId, long expectedRevision) {
        Long targetRevision;
        try {
            targetRevision = pgJdbcTemplate.queryForObject("""
                    UPDATE knowledge_document SET review_status='PUBLISHING', revision=revision+1, updated_at=NOW()
                    WHERE id=? AND revision=? AND review_status='REVIEW_REQUIRED'
                      AND COALESCE(metadata ->> 'deleted', 'false') <> 'true'
                    RETURNING revision
                    """, Long.class, documentId, expectedRevision);
        } catch (EmptyResultDataAccessException ignored) {
            targetRevision = null;
        }
        if (targetRevision == null) throw conflict(documentId);
        pgJdbcTemplate.update("UPDATE knowledge_chunk_draft SET revision=? WHERE document_id=?", targetRevision, documentId);
        long frozenRevision = targetRevision;
        afterCommit(() -> asyncService.publish(documentId, frozenRevision));
        return frozenRevision;
    }

    @Transactional(transactionManager = "pgTransactionManager")
    public void commitPublishedRevision(Long documentId, long targetRevision, List<List<Double>> embeddings) {
        List<Map<String, Object>> rows = targetDraft(documentId, targetRevision);
        if (rows.isEmpty() || embeddings == null || embeddings.size() != rows.size()) {
            throw new IllegalStateException("EMBEDDING_COUNT_MISMATCH");
        }
        for (int index = 0; index < rows.size(); index++) {
            List<Double> vector = embeddings.get(index);
            if (vector == null || vector.size() != 1024) throw new IllegalStateException("EMBEDDING_DIMENSION_INVALID");
            Map<String, Object> row = rows.get(index);
            pgJdbcTemplate.update("""
                    INSERT INTO knowledge_chunk(document_id, document_type, chunk_index, chunk_text, embedding, revision,
                        product_categories, scenes, intents, heading_path, page_number, search_text, metadata, create_time)
                    VALUES (?, ?, ?, ?, ?::vector, ?, ?::text[], ?::text[], ?::text[], ?::text[], ?, ?, ?::jsonb, NOW())
                    """, documentId, value(row, "source_type"), intValue(row, "chunk_index"), value(row, "chunk_text"), vectorText(vector),
                    targetRevision, array(row.get("product_categories")), array(row.get("scenes")), array(row.get("intents")),
                    array(row.get("heading_path")), row.get("page_number"), searchText(row), toJson(metadata(row)));
        }
        int switched = pgJdbcTemplate.update("""
                UPDATE knowledge_document SET published_revision=?, review_status='PUBLISHED', updated_at=NOW()
                WHERE id=? AND review_status='PUBLISHING' AND revision=?
                  AND COALESCE(metadata ->> 'deleted', 'false') <> 'true'
                """, targetRevision, documentId, targetRevision);
        if (switched != 1) throw new IllegalStateException("STALE_PUBLISH_TARGET");
        pgJdbcTemplate.update("DELETE FROM knowledge_chunk WHERE document_id=? AND revision<>?", documentId, targetRevision);
    }

    @Transactional(transactionManager = "pgTransactionManager", propagation = Propagation.REQUIRES_NEW)
    public boolean markEmbeddingFailed(Long documentId, long targetRevision, String code) {
        int changed = pgJdbcTemplate.update("""
                UPDATE knowledge_document SET review_status='EMBEDDING_FAILED',
                    metadata=COALESCE(metadata, '{}'::jsonb) || ?::jsonb, updated_at=NOW()
                WHERE id=? AND revision=? AND review_status='PUBLISHING'
                  AND COALESCE(metadata ->> 'deleted', 'false') <> 'true'
                """, toJson(Map.of("errorCode", code == null ? "EMBEDDING_FAILED" : code)), documentId, targetRevision);
        return changed == 1;
    }

    List<Map<String, Object>> targetDraft(Long documentId, long targetRevision) {
        return pgJdbcTemplate.queryForList("""
                SELECT kd.id document_id, kd.source_type, kd.source_code, kd.merchant_code, kd.title, kd.policy_version,
                       kd.valid_from, kd.valid_to, d.chunk_index, d.chunk_text, d.heading_path, d.page_number,
                       d.product_categories, d.scenes, d.intents
                FROM knowledge_document kd JOIN knowledge_chunk_draft d ON d.document_id=kd.id
                WHERE kd.id=? AND kd.revision=? AND kd.review_status='PUBLISHING' AND d.revision=?
                  AND COALESCE(kd.metadata ->> 'deleted', 'false') <> 'true'
                ORDER BY d.chunk_index
                """, documentId, targetRevision, targetRevision);
    }

    private KnowledgeRevisionConflictException conflict(Long id) {
        List<Map<String, Object>> current = pgJdbcTemplate.queryForList(
                "SELECT revision, review_status FROM knowledge_document WHERE id=?", id);
        if (current.isEmpty()) return new KnowledgeRevisionConflictException(0L, "NOT_FOUND");
        return new KnowledgeRevisionConflictException(longValue(current.getFirst(), "revision"), value(current.getFirst(), "review_status"));
    }

    private void afterCommit(Runnable task) {
        if (!TransactionSynchronizationManager.isSynchronizationActive()) { task.run(); return; }
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override public void afterCommit() { task.run(); }
        });
    }

    private static String value(Map<String, Object> row, String key) { return Objects.toString(row.get(key), ""); }
    private static long longValue(Map<String, Object> row, String key) { return ((Number) row.get(key)).longValue(); }
    private static Integer intValue(Map<String, Object> row, String key) { return ((Number) row.get(key)).intValue(); }
    private static String[] array(Object raw) {
        if (raw == null) return null;
        if (raw instanceof String[] values) return values;
        if (raw instanceof Array sqlArray) try { return Arrays.stream((Object[]) sqlArray.getArray()).map(String::valueOf).toArray(String[]::new); } catch (Exception ignored) { return null; }
        if (raw instanceof List<?> values) return values.stream().map(String::valueOf).toArray(String[]::new);
        return null;
    }
    private static String vectorText(List<Double> vector) { return vector.stream().map(String::valueOf).collect(Collectors.joining(",", "[", "]")); }
    private static String searchText(Map<String, Object> row) {
        List<String> values = new ArrayList<>();
        values.add(value(row, "title")); values.add(String.join(" ", array(row.get("heading_path")) == null ? new String[0] : array(row.get("heading_path"))));
        values.add(value(row, "chunk_text"));
        for (String key : List.of("product_categories", "scenes", "intents")) { String[] tags = array(row.get(key)); if (tags != null) values.add(String.join(" ", tags)); }
        return values.stream().filter(value -> !value.isBlank()).collect(Collectors.joining(" "));
    }
    private static Map<String, Object> metadata(Map<String, Object> row) {
        Map<String, Object> data = new LinkedHashMap<>();
        for (String key : List.of("title", "source_type", "source_code", "merchant_code", "policy_version", "valid_from", "valid_to")) data.put(key, row.get(key));
        String[] headings = array(row.get("heading_path"));
        Map<String, Object> citation = new LinkedHashMap<>();
        citation.put("headingPath", headings == null ? List.of() : Arrays.asList(headings));
        citation.put("pageNumber", row.get("page_number"));
        data.put("citation", citation);
        return data;
    }
    private static String toJson(Object value) { try { return OBJECT_MAPPER.writeValueAsString(value); } catch (Exception e) { throw new IllegalStateException("Unable to serialize knowledge metadata", e); } }
}
