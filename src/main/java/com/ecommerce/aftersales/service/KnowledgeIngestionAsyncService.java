package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.config.AgentGatewayProperties;
import com.ecommerce.aftersales.config.TraceContext;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.client.RestClientResponseException;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

@Service
@Slf4j
public class KnowledgeIngestionAsyncService {

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
    private static final Set<String> PARSE_ERROR_CODES = Set.of(
            "UNSUPPORTED_FILE_TYPE", "PDF_ENCRYPTED", "PDF_TEXT_LAYER_MISSING", "FILE_DECODE_FAILED",
            "DOCUMENT_CONTENT_EMPTY", "DOCUMENT_CHUNKING_FAILED"
    );

    @Qualifier("pgJdbcTemplate")
    private final JdbcTemplate pgJdbcTemplate;
    private final RestTemplate restTemplate;
    private final AgentGatewayProperties agentGatewayProperties;
    private final KnowledgeMetadataPolicy metadataPolicy;
    private final KnowledgeDraftService draftService;
    private final ObjectProvider<KnowledgePublishService> publishServiceProvider;

    @Autowired
    public KnowledgeIngestionAsyncService(
            JdbcTemplate pgJdbcTemplate,
            RestTemplate restTemplate,
            AgentGatewayProperties agentGatewayProperties,
            KnowledgeMetadataPolicy metadataPolicy,
            KnowledgeDraftService draftService,
            ObjectProvider<KnowledgePublishService> publishServiceProvider
    ) {
        this.pgJdbcTemplate = pgJdbcTemplate;
        this.restTemplate = restTemplate;
        this.agentGatewayProperties = agentGatewayProperties;
        this.metadataPolicy = metadataPolicy;
        this.draftService = draftService;
        this.publishServiceProvider = publishServiceProvider;
    }

    public KnowledgeIngestionAsyncService(JdbcTemplate pgJdbcTemplate, RestTemplate restTemplate,
                                          AgentGatewayProperties agentGatewayProperties, KnowledgeMetadataPolicy metadataPolicy,
                                          KnowledgeDraftService draftService) {
        this(pgJdbcTemplate, restTemplate, agentGatewayProperties, metadataPolicy, draftService, null);
    }

    public KnowledgeIngestionAsyncService(
            JdbcTemplate pgJdbcTemplate, RestTemplate restTemplate, AgentGatewayProperties agentGatewayProperties,
            KnowledgeMetadataPolicy metadataPolicy
    ) {
        this(pgJdbcTemplate, restTemplate, agentGatewayProperties, metadataPolicy, new KnowledgeDraftService(pgJdbcTemplate), null);
    }

    KnowledgeIngestionAsyncService(
            JdbcTemplate pgJdbcTemplate, RestTemplate restTemplate, AgentGatewayProperties agentGatewayProperties
    ) {
        this(pgJdbcTemplate, restTemplate, agentGatewayProperties, null, new KnowledgeDraftService(pgJdbcTemplate), null);
    }

    @Async("knowledgeIngestionExecutor")
    public void publish(Long documentId, long targetRevision) {
        KnowledgePublishService publishService = publishServiceProvider == null ? null : publishServiceProvider.getIfAvailable();
        if (publishService == null) {
            log.warn("Skip publish without publish service, documentId={}, revision={}", documentId, targetRevision);
            return;
        }
        try {
            List<Map<String, Object>> draft = publishService.targetDraft(documentId, targetRevision);
            List<String> texts = draft.stream().map(KnowledgePublishService::contextualizedText).toList();
            if (texts.isEmpty()) throw new IllegalStateException("EMBEDDING_EMPTY_DRAFT");
            String baseUrl = agentGatewayProperties.getBaseUrl().replaceAll("/+$", "");
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            if (agentGatewayProperties.getInternalToken() != null && !agentGatewayProperties.getInternalToken().isBlank()) {
                headers.set("X-Agent-Internal-Token", agentGatewayProperties.getInternalToken());
            }
            TraceContext.putHeader(headers);
            Map<String, Object> response = restTemplate.postForObject(baseUrl + "/embeddings",
                    new HttpEntity<>(Map.of("chunks", texts, "document_id", documentId), headers), Map.class);
            Object raw = response == null ? null : response.get("embeddings");
            if (!(raw instanceof List<?> records) || records.size() != texts.size()) throw new IllegalStateException("EMBEDDING_COUNT_MISMATCH");
            List<List<Double>> vectors = new ArrayList<>();
            for (Object record : records) {
                if (!(record instanceof List<?> values) || values.size() != 1024) throw new IllegalStateException("EMBEDDING_DIMENSION_INVALID");
                vectors.add(values.stream().map(value -> ((Number) value).doubleValue()).toList());
            }
            publishService.commitPublishedRevision(documentId, targetRevision, vectors);
        } catch (Exception exception) {
            log.error("Failed to publish knowledge documentId={}, revision={}", documentId, targetRevision, exception);
            publishService.markEmbeddingFailed(documentId, targetRevision, "EMBEDDING_FAILED");
        }
    }

    @Async("knowledgeIngestionExecutor")
    public void processTextImport(Long documentId, String content, long targetRevision) {
        try {
            processParsedFile(documentId, bytes(content), textFileName(documentId), targetRevision);
        } catch (Exception e) {
            log.error("Failed to process knowledge text import, documentId={}", documentId, e);
            draftService.markParseFailed(documentId, targetRevision, errorCode(e), safeErrorMessage(e));
        }
    }

    @Async("knowledgeIngestionExecutor")
    public void processFileImport(Long documentId, String filePath, String fileName) {
        processFileImport(documentId, filePath, fileName, 1L);
    }

    @Async("knowledgeIngestionExecutor")
    public void processFileImport(Long documentId, String filePath, String fileName, long targetRevision) {
        try {
            Path path = Path.of(filePath);
            if (!Files.exists(path) || Files.size(path) > 10 * 1024 * 1024) {
                throw new IllegalArgumentException("FILE_TOO_LARGE_OR_MISSING");
            }
            processParsedFile(documentId, Files.readAllBytes(path), fileName, targetRevision);
        } catch (Exception e) {
            log.error("Failed to process knowledge file import, documentId={}", documentId, e);
            draftService.markParseFailed(documentId, targetRevision, errorCode(e), safeErrorMessage(e));
        }
    }

    @Async("knowledgeIngestionExecutor")
    public void reprocessDocument(Long documentId, long targetRevision) {
        Map<String, Object> document = loadDocument(documentId);
        if (document == null) {
            log.warn("Skip reprocess, document not found: {}", documentId);
            return;
        }
        Map<String, Object> metadata = readMetadata(document.get("metadata"));
        String sourceMode = stringValue(metadata.get("ingestionSourceType"));

        try {
            if ("FILE".equalsIgnoreCase(sourceMode)) {
                String filePath = stringValue(metadata.get("fileStoragePath"));
                String fileName = stringValue(metadata.get("fileName"));
                processFileImport(documentId, filePath, fileName, targetRevision);
                return;
            }

            processParsedFile(documentId, bytes(stringValue(document.get("content"))),
                    textFileName(documentId), targetRevision);
        } catch (Exception e) {
            log.error("Failed to reprocess document {}", documentId, e);
            draftService.markParseFailed(documentId, targetRevision, errorCode(e), safeErrorMessage(e));
        }
    }

    @SuppressWarnings("unchecked")
    private void processParsedFile(Long documentId, byte[] content, String fileName, long targetRevision) {
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
        draftService.replaceParsedDraft(documentId, targetRevision, castParsed(parsed, chunks));
    }

    private Map<String, Object> castParsed(Map<?, ?> parsed, List<?> chunks) {
        Map<String, Object> result = new LinkedHashMap<>();
        parsed.forEach((key, value) -> result.put(String.valueOf(key), value));
        result.put("chunks", chunks);
        return result;
    }

    private String errorCode(Exception exception) {
        if (exception instanceof RestClientResponseException responseException) {
            try {
                Map<String, Object> body = OBJECT_MAPPER.readValue(responseException.getResponseBodyAsString(), new TypeReference<>() {});
                String code = stringValue(body.get("error"));
                if (code != null && PARSE_ERROR_CODES.contains(code)) return code;
            } catch (Exception ignored) {
                // A non-JSON or unknown error response deliberately remains a stable generic failure.
            }
            return "PARSE_FAILED";
        }
        String message = exception.getMessage();
        if (message == null || message.isBlank()) return "PARSE_FAILED";
        int separator = message.indexOf(':');
        return (separator < 0 ? message : message.substring(0, separator)).replaceAll("[^A-Z0-9_]", "_").toUpperCase();
    }

    private String safeErrorMessage(Exception exception) {
        String message = exception instanceof RestClientResponseException responseException
                ? responseException.getResponseBodyAsString()
                : exception.getMessage();
        if (message == null || message.isBlank()) return "Parse failed";
        String sanitized = message.replaceAll("[\\r\\n\\t]+", " ")
                .replaceAll("(?i)(https?://\\S+|[A-Za-z]:\\\\\\S+|/(?:[^\\s/]+/)*[^\\s]+)", "[redacted]");
        return sanitized.length() <= 300 ? sanitized : sanitized.substring(0, 300);
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
                   product_category, scene, intent, policy_version, tags, metadata, status, revision, review_status
            FROM knowledge_document
            WHERE id = ?
            LIMIT 1
            """,
            id
        );
        return rows.isEmpty() ? null : rows.get(0);
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

    private String stringValue(Object value) {
        return value == null ? null : Objects.toString(value, null);
    }

    private String textFileName(Long documentId) {
        return "knowledge-" + documentId + ".txt";
    }

    private byte[] bytes(String content) {
        return (content == null ? "" : content).getBytes(StandardCharsets.UTF_8);
    }
}
