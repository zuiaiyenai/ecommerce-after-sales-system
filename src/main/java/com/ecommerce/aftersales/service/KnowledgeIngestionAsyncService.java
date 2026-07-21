package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.config.AgentGatewayProperties;
import com.ecommerce.aftersales.config.TraceContext;
import com.ecommerce.aftersales.dto.KnowledgeUploadDto;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.client.RestTemplate;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Timestamp;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Arrays;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.stream.Collectors;

@Service
@Slf4j
public class KnowledgeIngestionAsyncService {

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    @Qualifier("pgJdbcTemplate")
    private final JdbcTemplate pgJdbcTemplate;
    private final RestTemplate restTemplate;
    private final AgentGatewayProperties agentGatewayProperties;
    private final KnowledgeMetadataPolicy metadataPolicy;

    @Autowired
    public KnowledgeIngestionAsyncService(
            JdbcTemplate pgJdbcTemplate,
            RestTemplate restTemplate,
            AgentGatewayProperties agentGatewayProperties,
            KnowledgeMetadataPolicy metadataPolicy
    ) {
        this.pgJdbcTemplate = pgJdbcTemplate;
        this.restTemplate = restTemplate;
        this.agentGatewayProperties = agentGatewayProperties;
        this.metadataPolicy = metadataPolicy;
    }

    KnowledgeIngestionAsyncService(
            JdbcTemplate pgJdbcTemplate, RestTemplate restTemplate, AgentGatewayProperties agentGatewayProperties
    ) {
        this(pgJdbcTemplate, restTemplate, agentGatewayProperties, null);
    }

    @Async("knowledgeIngestionExecutor")
    @Transactional(transactionManager = "pgTransactionManager")
    public void processTextImport(Long documentId, String content) {
        processDocument(documentId, content, null, null);
    }

    @Async("knowledgeIngestionExecutor")
    @Transactional(transactionManager = "pgTransactionManager")
    public void processFileImport(Long documentId, String filePath, String fileName) {
        try {
            Path path = Path.of(filePath);
            if (!Files.exists(path) || Files.size(path) > 10 * 1024 * 1024) {
                throw new IllegalArgumentException("FILE_TOO_LARGE_OR_MISSING");
            }
            processParsedFile(documentId, Files.readAllBytes(path), fileName);
        } catch (Exception e) {
            log.error("Failed to process knowledge file import, documentId={}", documentId, e);
            markFailed(documentId, errorCode(e), e.getMessage());
        }
    }

    @Async("knowledgeIngestionExecutor")
    @Transactional(transactionManager = "pgTransactionManager")
    public void reprocessDocument(Long documentId) {
        Map<String, Object> document = loadDocument(documentId);
        if (document == null) {
            log.warn("Skip reprocess, document not found: {}", documentId);
            return;
        }

        Map<String, Object> metadata = readMetadata(document.get("metadata"));
        String sourceMode = stringValue(metadata.get("ingestionSourceType"));
        markProcessing(documentId, metadata);

        try {
            if ("FILE".equalsIgnoreCase(sourceMode)) {
                String filePath = stringValue(metadata.get("fileStoragePath"));
                String fileName = stringValue(metadata.get("fileName"));
                processFileImport(documentId, filePath, fileName);
                return;
            }

            processDocument(documentId, stringValue(document.get("content")), null, null);
        } catch (Exception e) {
            log.error("Failed to reprocess document {}", documentId, e);
            markFailed(documentId, errorCode(e), e.getMessage());
        }
    }

    @SuppressWarnings("unchecked")
    private void processParsedFile(Long documentId, byte[] content, String fileName) {
        Map<String, Object> document = loadDocument(documentId);
        if (document == null) throw new IllegalArgumentException("Knowledge document not found");
        Map<String, Object> request = new LinkedHashMap<>();
        request.put("file_name", fileName);
        request.put("content_base64", Base64.getEncoder().encodeToString(content));
        request.put("knowledge_type", stringValue(document.get("source_type")));
        request.put("allowed_metadata", canonicalAllowedMetadata(stringValue(document.get("merchant_code"))));
        String baseUrl = agentGatewayProperties.getBaseUrl().replaceAll("/+$", "");
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        if (agentGatewayProperties.getInternalToken() != null && !agentGatewayProperties.getInternalToken().isBlank()) {
            headers.set("X-Agent-Internal-Token", agentGatewayProperties.getInternalToken());
        }
        TraceContext.putHeader(headers);
        Map<String, Object> response = restTemplate.postForObject(baseUrl + "/knowledge/parse", new HttpEntity<>(request, headers), Map.class);
        if (response == null) throw new IllegalStateException("PARSE_RESPONSE_EMPTY");
        Object body = response.getOrDefault("data", response);
        if (!(body instanceof Map<?, ?> parsed)) throw new IllegalStateException("PARSE_RESPONSE_INVALID");
        Object chunksValue = parsed.get("chunks");
        if (!(chunksValue instanceof List<?> chunks)) throw new IllegalStateException("PARSE_RESPONSE_INVALID");
        long revision = ((Number) document.getOrDefault("revision", 1L)).longValue();
        pgJdbcTemplate.update("DELETE FROM knowledge_chunk_draft WHERE document_id = ?", documentId);
        for (Object item : chunks) {
            if (!(item instanceof Map<?, ?> chunk)) continue;
            pgJdbcTemplate.update("""
                    INSERT INTO knowledge_chunk_draft (document_id, chunk_index, heading_path, page_number, chunk_text,
                        product_categories, scenes, intents, classification_source, classification_confidence,
                        classification_reason, review_required, revision)
                    VALUES (?, ?, ?::text[], ?, ?, ?::text[], ?::text[], ?::text[], ?, ?, ?, ?, ?)
                    """, documentId, number(chunk.get("chunk_index")), stringArray(chunk.get("heading_path")),
                    chunk.get("page_number"), stringValue(chunk.get("text")), stringArray(chunk.get("product_categories")),
                    stringArray(chunk.get("scenes")), stringArray(chunk.get("intents")),
                    stringValue(chunk.get("classification_source")), chunk.get("classification_confidence"),
                    stringValue(chunk.get("classification_reason")), Boolean.TRUE.equals(chunk.get("review_required")), revision);
        }
        pgJdbcTemplate.update("""
                UPDATE knowledge_document SET content = ?, valid_from = CAST(? AS timestamp), valid_to = CAST(? AS timestamp),
                    review_status = 'REVIEW_REQUIRED', updated_at = NOW()
                WHERE id = ? AND revision = ? AND review_status = 'PROCESSING'
                """, stringValue(parsed.get("content")), stringValue(parsed.get("valid_from")), stringValue(parsed.get("valid_to")), documentId, revision);
    }

    private void processDocument(Long documentId, String content, String filePath, String fileName) {
        Map<String, Object> document = loadDocument(documentId);
        if (document == null) {
            throw new IllegalArgumentException("Knowledge document not found: " + documentId);
        }
        if (content == null || content.isBlank()) {
            throw new IllegalArgumentException("Knowledge content is empty");
        }

        List<String> chunks = splitContent(content, 700);
        if (chunks.isEmpty()) {
            throw new IllegalArgumentException("Knowledge content produced no chunks");
        }

        List<Map<String, Object>> chunkRecords = generateEmbeddings(documentId, document, chunks);

        pgJdbcTemplate.update("DELETE FROM knowledge_chunk WHERE document_id = ?", documentId);

        String insertChunkSql = """
            INSERT INTO knowledge_chunk (
                document_id, document_type, chunk_index, chunk_text, embedding, metadata, create_time
            ) VALUES (?, ?, ?, ?, ?::vector, ?::jsonb, NOW())
            """;

        for (Map<String, Object> record : chunkRecords) {
            pgJdbcTemplate.update(
                insertChunkSql,
                documentId,
                stringValue(document.get("source_type")),
                record.get("chunk_index"),
                record.get("chunk_text"),
                record.get("embedding"),
                record.get("metadata")
            );
        }

        Map<String, Object> metadata = readMetadata(document.get("metadata"));
        metadata.put("ingestionStatus", "SUCCESS");
        metadata.put("errorMessage", null);
        metadata.put("chunkCount", chunkRecords.size());
        if (filePath != null) {
            metadata.put("fileStoragePath", filePath);
        }
        if (fileName != null) {
            metadata.put("fileName", fileName);
        }

        pgJdbcTemplate.update(
            """
            UPDATE knowledge_document
            SET content = ?, metadata = ?::jsonb, updated_at = NOW()
            WHERE id = ?
            """,
            content,
            toJson(metadata),
            documentId
        );
    }

    private void markProcessing(Long documentId, Map<String, Object> metadata) {
        metadata.put("ingestionStatus", "PROCESSING");
        metadata.put("errorMessage", null);
        pgJdbcTemplate.update(
            "UPDATE knowledge_document SET metadata = ?::jsonb, updated_at = NOW() WHERE id = ?",
            toJson(metadata),
            documentId
        );
    }

    private void markFailed(Long documentId, String errorCode, String errorMessage) {
        Map<String, Object> document = loadDocument(documentId);
        Map<String, Object> metadata = readMetadata(document == null ? null : document.get("metadata"));
        metadata.put("ingestionStatus", "FAILED");
        metadata.put("errorCode", errorCode);
        metadata.put("errorMessage", errorMessage == null ? "Unknown error" : errorMessage);
        pgJdbcTemplate.update(
            "UPDATE knowledge_document SET review_status = 'PARSE_FAILED', metadata = ?::jsonb, updated_at = NOW() WHERE id = ?",
            toJson(metadata),
            documentId
        );
    }

    private String errorCode(Exception exception) {
        String message = exception.getMessage();
        if (message == null || message.isBlank()) return "PARSE_FAILED";
        int separator = message.indexOf(':');
        return (separator < 0 ? message : message.substring(0, separator)).replaceAll("[^A-Z0-9_]", "_").toUpperCase();
    }

    private Integer number(Object value) {
        return value instanceof Number number ? number.intValue() : Integer.parseInt(String.valueOf(value));
    }

    private String[] stringArray(Object value) {
        if (!(value instanceof List<?> values)) return null;
        return values.stream().filter(Objects::nonNull).map(String::valueOf).toArray(String[]::new);
    }

    private Map<String, List<String>> canonicalAllowedMetadata(String merchantCode) {
        if (metadataPolicy == null) {
            throw new IllegalStateException("Knowledge metadata policy is required for file parsing");
        }
        Map<String, Object> options = metadataPolicy.options(merchantCode);
        return Map.of(
                "product_categories", optionValues(options.get("productCategories")),
                "scenes", optionValues(options.get("scenes")),
                "intents", optionValues(options.get("intents"))
        );
    }

    private List<String> optionValues(Object value) {
        if (!(value instanceof List<?> options)) return List.of();
        return options.stream()
                .filter(KnowledgeMetadataPolicy.Option.class::isInstance)
                .map(KnowledgeMetadataPolicy.Option.class::cast)
                .map(KnowledgeMetadataPolicy.Option::value)
                .toList();
    }

    private Map<String, Object> loadDocument(Long id) {
        List<Map<String, Object>> rows = pgJdbcTemplate.queryForList(
            """
            SELECT id, source_type, source_code, merchant_code, title, content,
                   product_category, scene, intent, policy_version, tags, metadata, status
            FROM knowledge_document
            WHERE id = ?
            LIMIT 1
            """,
            id
        );
        return rows.isEmpty() ? null : rows.get(0);
    }

    private String extractTextFromFile(Path filePath, String fileName) throws IOException {
        if (filePath == null || !Files.exists(filePath)) {
            throw new IllegalArgumentException("Uploaded file not found");
        }
        String lower = (fileName == null ? filePath.getFileName().toString() : fileName).toLowerCase();
        if (!(lower.endsWith(".txt") || lower.endsWith(".md"))) {
            throw new IllegalArgumentException("Only .txt and .md files are supported in v1");
        }
        return Files.readString(filePath, StandardCharsets.UTF_8);
    }

    private List<String> splitContent(String content, int maxChunkSize) {
        if (content == null || content.isBlank()) {
            return List.of();
        }

        String normalized = Arrays.stream(content.split("\n"))
            .map(String::strip)
            .filter(line -> !line.isEmpty())
            .collect(Collectors.joining("\n"));

        if (normalized.length() <= maxChunkSize) {
            return List.of(normalized);
        }

        List<String> chunks = new ArrayList<>();
        int start = 0;
        int overlapSize = (int) (maxChunkSize * 0.2);

        while (start < normalized.length()) {
            int end = Math.min(start + maxChunkSize, normalized.length());
            chunks.add(normalized.substring(start, end));
            start += maxChunkSize - overlapSize;
        }

        return chunks;
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> generateEmbeddings(Long documentId, Map<String, Object> document, List<String> chunks) {
        Map<String, Object> requestBody = Map.of(
            "chunks", chunks,
            "document_id", documentId,
            "document_type", stringValue(document.get("source_type"))
        );

        String baseUrl = agentGatewayProperties.getBaseUrl();
        if (baseUrl.endsWith("/")) {
            baseUrl = baseUrl.substring(0, baseUrl.length() - 1);
        }
        String url = baseUrl + "/embeddings";
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        if (agentGatewayProperties.getInternalToken() != null
                && !agentGatewayProperties.getInternalToken().isBlank()) {
            headers.set("X-Agent-Internal-Token", agentGatewayProperties.getInternalToken());
        }
        TraceContext.putHeader(headers);
        Map<String, Object> response = restTemplate.postForObject(
                url,
                new HttpEntity<>(requestBody, headers),
                Map.class
        );
        if (response == null || !response.containsKey("embeddings")) {
            throw new IllegalStateException("Embedding service returned no embeddings");
        }

        List<List<Double>> embeddings = (List<List<Double>>) response.get("embeddings");
        if (embeddings.size() != chunks.size()) {
            throw new IllegalStateException("Embedding count mismatch");
        }

        List<Map<String, Object>> records = new ArrayList<>();
        for (int i = 0; i < chunks.size(); i++) {
            Map<String, Object> chunkMetadata = new LinkedHashMap<>();
            chunkMetadata.put("title", stringValue(document.get("title")));
            chunkMetadata.put("source_type", stringValue(document.get("source_type")));
            chunkMetadata.put("source_code", stringValue(document.get("source_code")));
            chunkMetadata.put("merchant_code", stringValue(document.get("merchant_code")));
            chunkMetadata.put("product_category", stringValue(document.get("product_category")));
            chunkMetadata.put("scene", stringValue(document.get("scene")));
            chunkMetadata.put("intent", stringValue(document.get("intent")));
            chunkMetadata.put("policy_version", stringValue(document.get("policy_version")));
            chunkMetadata.put("tags", readTags(document.get("tags")));

            String embeddingVector = embeddings.get(i).stream()
                .map(String::valueOf)
                .collect(Collectors.joining(",", "[", "]"));

            Map<String, Object> record = new HashMap<>();
            record.put("chunk_index", i);
            record.put("chunk_text", chunks.get(i));
            record.put("embedding", embeddingVector);
            record.put("metadata", toJson(chunkMetadata));
            records.add(record);
        }
        return records;
    }

    private List<String> readTags(Object rawTags) {
        if (rawTags == null) {
            return List.of();
        }
        try {
            if (rawTags instanceof List<?> list) {
                return list.stream().map(String::valueOf).toList();
            }
            return OBJECT_MAPPER.readValue(String.valueOf(rawTags), new TypeReference<>() {});
        } catch (Exception e) {
            log.warn("Failed to parse knowledge tags: {}", rawTags, e);
            return List.of();
        }
    }

    private Map<String, Object> readMetadata(Object rawMetadata) {
        if (rawMetadata == null) {
            return new LinkedHashMap<>();
        }
        try {
            if (rawMetadata instanceof Map<?, ?> map) {
                return new LinkedHashMap<>((Map<String, Object>) map);
            }
            String json = String.valueOf(rawMetadata);
            if (json.isBlank()) {
                return new LinkedHashMap<>();
            }
            return OBJECT_MAPPER.readValue(json, new TypeReference<>() {});
        } catch (Exception e) {
            log.warn("Failed to parse metadata: {}", rawMetadata, e);
            return new LinkedHashMap<>();
        }
    }

    private String toJson(Object value) {
        try {
            return OBJECT_MAPPER.writeValueAsString(value);
        } catch (Exception e) {
            throw new IllegalStateException("Failed to serialize metadata", e);
        }
    }

    private String stringValue(Object value) {
        return value == null ? null : Objects.toString(value, null);
    }
}
