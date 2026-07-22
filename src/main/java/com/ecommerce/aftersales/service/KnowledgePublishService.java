package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.common.KnowledgeRevisionConflictException;
import com.ecommerce.aftersales.common.BizException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Autowired;
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
public class KnowledgePublishService {
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
    private static final List<String> STRUCTURAL_METADATA_KEYS = List.of(
            "page_start", "page_end", "content_types", "estimated_tokens", "chunking_strategy"
    );
    @Qualifier("pgJdbcTemplate") private final JdbcTemplate pgJdbcTemplate;
    private final KnowledgeIngestionAsyncService asyncService;
    private final KnowledgeMetadataPolicy metadataPolicy;

    @Autowired
    public KnowledgePublishService(JdbcTemplate pgJdbcTemplate, KnowledgeIngestionAsyncService asyncService,
                                   KnowledgeMetadataPolicy metadataPolicy) {
        this.pgJdbcTemplate = pgJdbcTemplate;
        this.asyncService = asyncService;
        this.metadataPolicy = metadataPolicy;
    }

    public KnowledgePublishService(JdbcTemplate pgJdbcTemplate, KnowledgeIngestionAsyncService asyncService) {
        this(pgJdbcTemplate, asyncService, null);
    }

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
        validatePublishable(documentId, targetRevision);
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
        validateDraftLabels(rows);
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
                       kd.valid_from, kd.valid_to, kd.revision, kd.metadata document_metadata,
                       d.chunk_index, d.chunk_text, d.heading_path, d.page_number, d.metadata chunk_metadata,
                       d.product_categories, d.scenes, d.intents
                FROM knowledge_document kd JOIN knowledge_chunk_draft d ON d.document_id=kd.id
                WHERE kd.id=? AND kd.revision=? AND kd.review_status='PUBLISHING' AND d.revision=?
                  AND COALESCE(kd.metadata ->> 'deleted', 'false') <> 'true'
                ORDER BY d.chunk_index
                """, documentId, targetRevision, targetRevision);
    }

    private void validatePublishable(Long documentId, long targetRevision) {
        List<Map<String, Object>> rows = targetDraft(documentId, targetRevision);
        if (rows.isEmpty()) throw new BizException("没有可发布的知识草稿");
        Map<String, Object> document = rows.getFirst();
        if (metadataPolicy != null && metadataPolicy.isVersionedKnowledgeType(value(document, "source_type"))) {
            Object version = document.get("policy_version");
            Object validFrom = document.get("valid_from");
            Object validTo = document.get("valid_to");
            if (version == null || String.valueOf(version).isBlank() || validFrom == null || validTo == null
                    || !(validTo instanceof Comparable<?> comparable) || compareTimestamp(comparable, validFrom) <= 0) {
                throw new BizException("政策版本与有效期不合法");
            }
        }
        validateDraftLabels(rows);
    }

    @SuppressWarnings({"unchecked", "rawtypes"})
    private static int compareTimestamp(Comparable validTo, Object validFrom) {
        try { return validTo.compareTo(validFrom); }
        catch (ClassCastException exception) { return -1; }
    }

    private static void validateDraftLabels(List<Map<String, Object>> rows) {
        for (Map<String, Object> row : rows) {
            for (String key : List.of("product_categories", "scenes", "intents")) {
                if (row.get(key) == null) throw new BizException("草稿分类标签尚未确认");
            }
        }
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
    public static String contextualizedText(Map<String, Object> row) {
        return contextualizedText(row, List.of());
    }

    private static String contextualizedText(Map<String, Object> row, List<String> additionalContext) {
        Map<String, Object> structural = metadataMap(row.get("chunk_metadata"));
        Map<String, Object> documentMetadata = metadataMap(row.get("document_metadata"));
        List<String> context = new ArrayList<>();
        addContext(context, "文档：", value(row, "title"));
        String[] headings = array(row.get("heading_path"));
        if (headings != null && headings.length > 0) addContext(context, "章节：", String.join(" > ", headings));
        Integer pageStart = integer(structural.get("page_start"));
        if (pageStart == null) pageStart = integer(row.get("page_number"));
        Integer pageEnd = integer(structural.get("page_end"));
        if (pageStart != null) {
            String range = pageEnd != null && !pageEnd.equals(pageStart) ? pageStart + "-" + pageEnd : pageStart.toString();
            addContext(context, "位置：", "第 " + range + " 页");
        }
        String ingestionMode = canonicalIngestionMode(documentMetadata);
        String fileName = trustedFileName(documentMetadata, ingestionMode);
        List<String> source = new ArrayList<>();
        if (fileName != null) source.add(fileName);
        String sourceCode = nonBlank(row.get("source_code"));
        if (sourceCode != null) source.add(sourceCode);
        if (!source.isEmpty()) addContext(context, "来源：", String.join(" / ", source));
        String[] contentTypes = array(structural.get("content_types"));
        if (contentTypes != null && contentTypes.length > 0) addContext(context, "内容类型：", String.join("、", contentTypes));
        context.addAll(additionalContext);
        String body = value(row, "chunk_text");
        if (context.isEmpty()) return body;
        return String.join("\n", context) + (body.isBlank() ? "" : "\n\n" + body);
    }

    private static String searchText(Map<String, Object> row) {
        List<String> classifications = new ArrayList<>();
        addClassification(classifications, "商品分类：", row.get("product_categories"));
        addClassification(classifications, "场景：", row.get("scenes"));
        addClassification(classifications, "意图：", row.get("intents"));
        return contextualizedText(row, classifications);
    }

    private static Map<String, Object> metadata(Map<String, Object> row) {
        Map<String, Object> data = new LinkedHashMap<>();
        Map<String, Object> structural = metadataMap(row.get("chunk_metadata"));
        for (String key : STRUCTURAL_METADATA_KEYS) {
            if (structural.containsKey(key)) data.put(key, structural.get(key));
        }
        data.put("document_id", value(row, "document_id"));
        data.put("document_title", row.get("title"));
        data.put("title", row.get("title"));
        for (String key : List.of("source_type", "source_code", "merchant_code", "policy_version", "valid_from", "valid_to", "revision", "chunk_index")) {
            data.put(key, row.get(key));
        }
        Map<String, Object> documentMetadata = metadataMap(row.get("document_metadata"));
        String ingestionMode = canonicalIngestionMode(documentMetadata);
        String fileName = trustedFileName(documentMetadata, ingestionMode);
        String sourceFormat = sourceFormat(ingestionMode, fileName);
        if (sourceFormat != null) data.put("source_format", sourceFormat);
        if (fileName != null) data.put("file_name", fileName);
        String[] headings = array(row.get("heading_path"));
        data.put("heading_path", headings == null ? List.of() : Arrays.asList(headings));
        data.put("page_number", row.get("page_number"));
        for (String key : List.of("product_categories", "scenes", "intents")) {
            String[] labels = array(row.get(key));
            data.put(key, labels == null ? null : Arrays.asList(labels));
        }
        Integer pageStart = integer(structural.get("page_start"));
        if (pageStart == null) pageStart = integer(row.get("page_number"));
        Integer pageEnd = integer(structural.get("page_end"));
        Map<String, Object> citation = new LinkedHashMap<>();
        citation.put("headingPath", headings == null ? List.of() : Arrays.asList(headings));
        citation.put("pageNumber", row.get("page_number"));
        citation.put("pageStart", pageStart);
        citation.put("pageEnd", pageEnd == null ? pageStart : pageEnd);
        data.put("citation", citation);
        return data;
    }

    private static void addContext(List<String> context, String prefix, String raw) {
        if (raw != null && !raw.isBlank()) context.add(prefix + raw);
    }

    private static void addClassification(List<String> context, String prefix, Object raw) {
        String[] values = array(raw);
        if (values != null && values.length > 0) addContext(context, prefix, String.join("、", values));
    }

    private static String canonicalIngestionMode(Map<String, Object> documentMetadata) {
        String mode = nonBlank(documentMetadata.get("ingestionSourceType"));
        return mode == null ? "TEXT" : mode.toUpperCase(java.util.Locale.ROOT);
    }

    private static String trustedFileName(Map<String, Object> documentMetadata, String ingestionMode) {
        if (!"FILE".equals(ingestionMode)) return null;
        return firstNonBlank(documentMetadata.get("fileName"), documentMetadata.get("file_name"));
    }

    private static String sourceFormat(String ingestionMode, String fileName) {
        if ("TEXT".equals(ingestionMode)) return "text";
        if (!"FILE".equals(ingestionMode) || fileName == null) return null;
        String lower = fileName.toLowerCase(java.util.Locale.ROOT);
        if (lower.endsWith(".pdf")) return "pdf";
        if (lower.endsWith(".md") || lower.endsWith(".markdown")) return "markdown";
        if (lower.endsWith(".txt")) return "text";
        return null;
    }

    private static String firstNonBlank(Object... values) {
        for (Object raw : values) {
            String value = nonBlank(raw);
            if (value != null) return value;
        }
        return null;
    }

    private static String nonBlank(Object raw) {
        String value = raw == null ? null : String.valueOf(raw).trim();
        return value == null || value.isBlank() ? null : value;
    }

    private static Integer integer(Object raw) {
        if (raw instanceof Number number) return number.intValue();
        try { return raw == null ? null : Integer.valueOf(String.valueOf(raw)); }
        catch (NumberFormatException ignored) { return null; }
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> metadataMap(Object raw) {
        if (raw == null) return Map.of();
        if (raw instanceof Map<?, ?> map) {
            Map<String, Object> result = new LinkedHashMap<>();
            map.forEach((key, value) -> result.put(String.valueOf(key), value));
            return result;
        }
        try {
            Object json = raw;
            if ("org.postgresql.util.PGobject".equals(raw.getClass().getName())) {
                json = raw.getClass().getMethod("getValue").invoke(raw);
            }
            if (json == null || String.valueOf(json).isBlank()) return Map.of();
            return OBJECT_MAPPER.readValue(String.valueOf(json), Map.class);
        } catch (Exception ignored) {
            return Map.of();
        }
    }
    private static String toJson(Object value) { try { return OBJECT_MAPPER.writeValueAsString(value); } catch (Exception e) { throw new IllegalStateException("Unable to serialize knowledge metadata", e); } }
}
