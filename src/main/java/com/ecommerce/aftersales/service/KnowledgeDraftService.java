package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.common.enums.ErrorCode;
import com.ecommerce.aftersales.dto.KnowledgeDraftDtos.DraftChunkResponse;
import com.ecommerce.aftersales.dto.KnowledgeDraftDtos.IngestionStatusResponse;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.sql.Array;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.time.LocalDateTime;

@Service
public class KnowledgeDraftService {
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
    @Qualifier("pgJdbcTemplate") private final JdbcTemplate pgJdbcTemplate;
    private final KnowledgeMetadataPolicy metadataPolicy;

    @Autowired
    public KnowledgeDraftService(JdbcTemplate pgJdbcTemplate, KnowledgeMetadataPolicy metadataPolicy) {
        this.pgJdbcTemplate = pgJdbcTemplate;
        this.metadataPolicy = metadataPolicy;
    }

    public KnowledgeDraftService(JdbcTemplate pgJdbcTemplate) {
        this(pgJdbcTemplate, null);
    }
    public IngestionStatusResponse ingestionStatus(Long documentId) {
        List<IngestionStatusResponse> rows = pgJdbcTemplate.query("SELECT id, review_status, metadata ->> 'errorCode' error_code, metadata ->> 'errorMessage' error_message, revision, published_revision FROM knowledge_document WHERE id = ? AND COALESCE(metadata ->> 'deleted', 'false') <> 'true'", (rs, rowNum) -> new IngestionStatusResponse(rs.getLong("id"), rs.getString("review_status"), rs.getString("error_code"), rs.getString("error_message"), rs.getLong("revision"), (Long) rs.getObject("published_revision")), documentId);
        if (rows.isEmpty()) throw new BizException(ErrorCode.NOT_FOUND, "Knowledge document not found");
        return rows.getFirst();
    }
    public List<DraftChunkResponse> draft(Long documentId) {
        return pgJdbcTemplate.query("SELECT d.id, d.chunk_index, d.heading_path, d.page_number, d.chunk_text, d.product_categories, d.scenes, d.intents, d.classification_source, d.classification_confidence, d.classification_reason, d.review_required, d.revision FROM knowledge_chunk_draft d JOIN knowledge_document kd ON kd.id = d.document_id WHERE d.document_id = ? AND COALESCE(kd.metadata ->> 'deleted', 'false') <> 'true' ORDER BY d.chunk_index", (rs, rowNum) -> new DraftChunkResponse(rs.getLong("id"), rs.getInt("chunk_index"), strings(rs.getArray("heading_path")), (Integer) rs.getObject("page_number"), rs.getString("chunk_text"), strings(rs.getArray("product_categories")), strings(rs.getArray("scenes")), strings(rs.getArray("intents")), rs.getString("classification_source"), rs.getBigDecimal("classification_confidence"), rs.getString("classification_reason"), rs.getBoolean("review_required"), rs.getLong("revision")), documentId);
    }

    @Transactional(transactionManager = "pgTransactionManager")
    public long updateDraftDocument(Long documentId, long expectedRevision, Map<String, Object> edit) {
        String policyVersion = string(edit.get("policyVersion"));
        String validFrom = string(edit.get("validFrom"));
        String validTo = string(edit.get("validTo"));
        if (policyVersion == null || policyVersion.isBlank() || validFrom == null || validTo == null
                || !validWindow(validFrom, validTo)) {
            throw new BizException("政策版本与有效期不合法");
        }
        Long revision = casRevision(documentId, expectedRevision);
        int changed = pgJdbcTemplate.update("""
                UPDATE knowledge_document SET policy_version=?, valid_from=CAST(? AS timestamp), valid_to=CAST(? AS timestamp),
                    updated_at=NOW() WHERE id=? AND revision=? AND review_status='REVIEW_REQUIRED'
                """, policyVersion.trim(), validFrom, validTo, documentId, revision);
        if (changed != 1) throw new IllegalStateException("STALE_DRAFT_TARGET");
        pgJdbcTemplate.update("UPDATE knowledge_chunk_draft SET revision=? WHERE document_id=?", revision, documentId);
        return revision;
    }

    @Transactional(transactionManager = "pgTransactionManager")
    public long updateDraftChunk(Long documentId, Long chunkId, long expectedRevision, Map<String, Object> edit) {
        Long revision = casRevision(documentId, expectedRevision);
        pgJdbcTemplate.update("UPDATE knowledge_chunk_draft SET revision=? WHERE document_id=?", revision, documentId);
        int changed = pgJdbcTemplate.update("""
                UPDATE knowledge_chunk_draft SET product_categories=?::text[], scenes=?::text[], intents=?::text[], revision=?
                WHERE id=? AND document_id=?
                """, canonical(edit.get("productCategories"), Field.CATEGORY), canonical(edit.get("scenes"), Field.SCENE),
                canonical(edit.get("intents"), Field.INTENT), revision, chunkId, documentId);
        if (changed != 1) throw new IllegalArgumentException("Draft chunk not found");
        return revision;
    }

    private Long casRevision(Long documentId, long expectedRevision) {
        try {
            Long revision = pgJdbcTemplate.queryForObject("""
                    UPDATE knowledge_document SET revision=revision+1, updated_at=NOW()
                    WHERE id=? AND revision=? AND review_status='REVIEW_REQUIRED'
                      AND COALESCE(metadata ->> 'deleted', 'false') <> 'true'
                    RETURNING revision
                    """, Long.class, documentId, expectedRevision);
            if (revision != null) return revision;
        } catch (org.springframework.dao.EmptyResultDataAccessException ignored) { }
        List<Map<String, Object>> current = pgJdbcTemplate.queryForList(
                "SELECT revision, review_status FROM knowledge_document WHERE id=? AND COALESCE(metadata ->> 'deleted', 'false') <> 'true'", documentId);
        if (current.isEmpty()) throw new BizException(ErrorCode.NOT_FOUND, "Knowledge document not found");
        Map<String, Object> row = current.getFirst();
        throw new com.ecommerce.aftersales.common.KnowledgeRevisionConflictException(
                ((Number) row.get("revision")).longValue(), String.valueOf(row.get("review_status")));
    }

    private String[] canonical(Object raw, Field field) {
        if (!(raw instanceof List<?> values)) return null;
        if (metadataPolicy == null) return values.stream().filter(Objects::nonNull).map(String::valueOf).toArray(String[]::new);
        return values.stream().filter(Objects::nonNull).map(String::valueOf).map(value -> switch (field) {
            case CATEGORY -> metadataPolicy.normalizeProductCategory(value);
            case SCENE -> metadataPolicy.normalizeScene(value);
            case INTENT -> metadataPolicy.normalizeIntent(value);
        }).filter(Objects::nonNull).toArray(String[]::new);
    }

    private static boolean validWindow(String validFrom, String validTo) {
        try { return LocalDateTime.parse(validTo).isAfter(LocalDateTime.parse(validFrom)); }
        catch (java.time.format.DateTimeParseException exception) { return false; }
    }

    private enum Field { CATEGORY, SCENE, INTENT }

    /** Replaces only the still-current processing draft in one PostgreSQL transaction. */
    @Transactional(transactionManager = "pgTransactionManager")
    public void replaceParsedDraft(Long documentId, long targetRevision, Map<String, Object> parsed) {
        List<Map<String, Object>> locked = pgJdbcTemplate.queryForList("""
                SELECT id FROM knowledge_document
                WHERE id = ? AND revision = ? AND review_status = 'PROCESSING'
                  AND COALESCE(metadata ->> 'deleted', 'false') <> 'true'
                FOR UPDATE
                """, documentId, targetRevision);
        if (locked.isEmpty()) throw new IllegalStateException("STALE_DRAFT_TARGET");

        Object rawChunks = parsed.get("chunks");
        if (!(rawChunks instanceof List<?> chunks)) throw new IllegalStateException("PARSE_RESPONSE_INVALID");
        pgJdbcTemplate.update("DELETE FROM knowledge_chunk_draft WHERE document_id = ?", documentId);
        for (Object rawChunk : chunks) {
            if (!(rawChunk instanceof Map<?, ?> raw)) continue;
            Map<String, Object> chunk = new LinkedHashMap<>();
            raw.forEach((key, value) -> chunk.put(String.valueOf(key), value));
            pgJdbcTemplate.update("""
                    INSERT INTO knowledge_chunk_draft (document_id, chunk_index, heading_path, page_number, chunk_text,
                        product_categories, scenes, intents, classification_source, classification_confidence,
                        classification_reason, review_required, revision)
                    VALUES (?, ?, ?::text[], ?, ?, ?::text[], ?::text[], ?::text[], ?, ?, ?, ?, ?)
                    """, documentId, number(chunk.get("chunk_index")), strings(chunk.get("heading_path")),
                    chunk.get("page_number"), string(chunk.get("text")), strings(chunk.get("product_categories")),
                    strings(chunk.get("scenes")), strings(chunk.get("intents")),
                    string(chunk.get("classification_source")), chunk.get("classification_confidence"),
                    string(chunk.get("classification_reason")), Boolean.TRUE.equals(chunk.get("review_required")), targetRevision);
        }
        int completed = pgJdbcTemplate.update("""
                UPDATE knowledge_document SET content = ?, valid_from = CAST(? AS timestamp), valid_to = CAST(? AS timestamp),
                    review_status = 'REVIEW_REQUIRED', updated_at = NOW()
                WHERE id = ? AND revision = ? AND review_status = 'PROCESSING'
                  AND COALESCE(metadata ->> 'deleted', 'false') <> 'true'
                """, string(parsed.get("content")), string(parsed.get("valid_from")), string(parsed.get("valid_to")),
                documentId, targetRevision);
        if (completed != 1) throw new IllegalStateException("STALE_DRAFT_TARGET");
    }

    /** Failure bookkeeping deliberately has a separate transaction and cannot overwrite another revision. */
    @Transactional(transactionManager = "pgTransactionManager", propagation = Propagation.REQUIRES_NEW)
    public boolean markParseFailed(Long documentId, long targetRevision, String errorCode, String errorMessage) {
        Map<String, Object> failure = new LinkedHashMap<>();
        failure.put("ingestionStatus", "FAILED");
        failure.put("errorCode", errorCode);
        failure.put("errorMessage", errorMessage == null ? "Unknown error" : errorMessage);
        int changed = pgJdbcTemplate.update("""
                UPDATE knowledge_document SET review_status = 'PARSE_FAILED',
                    metadata = COALESCE(metadata, '{}'::jsonb) || ?::jsonb, updated_at = NOW()
                WHERE id = ? AND revision = ? AND review_status = 'PROCESSING'
                  AND COALESCE(metadata ->> 'deleted', 'false') <> 'true'
                """, toJson(failure), documentId, targetRevision);
        return changed == 1;
    }

    private static Integer number(Object value) { return value instanceof Number number ? number.intValue() : Integer.valueOf(String.valueOf(value)); }
    private static String string(Object value) { return value == null ? null : Objects.toString(value, null); }
    private static String[] strings(Object value) {
        if (!(value instanceof List<?> values)) return null;
        return values.stream().filter(Objects::nonNull).map(String::valueOf).toArray(String[]::new);
    }
    private static String toJson(Map<String, Object> value) {
        try { return OBJECT_MAPPER.writeValueAsString(value); }
        catch (Exception exception) { throw new IllegalStateException("Unable to serialize ingestion failure", exception); }
    }
    private static List<String> strings(Array array) throws java.sql.SQLException { return array == null ? null : Arrays.stream((Object[]) array.getArray()).map(String::valueOf).toList(); }
}
