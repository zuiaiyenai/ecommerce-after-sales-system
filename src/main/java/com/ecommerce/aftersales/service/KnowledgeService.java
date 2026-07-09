package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.dto.KnowledgeUploadDto;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Timestamp;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@Service
@Slf4j
public class KnowledgeService {

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    private final JdbcTemplate pgJdbcTemplate;
    private final KnowledgeIngestionAsyncService asyncService;
    private final Path uploadRoot;

    public KnowledgeService(
            @Qualifier("pgJdbcTemplate") JdbcTemplate pgJdbcTemplate,
            KnowledgeIngestionAsyncService asyncService,
            @Value("${app.upload.dir:./uploads}") String uploadDir
    ) throws IOException {
        this.pgJdbcTemplate = pgJdbcTemplate;
        this.asyncService = asyncService;
        this.uploadRoot = Paths.get(uploadDir).toAbsolutePath().normalize();
        Files.createDirectories(this.uploadRoot.resolve("knowledge"));
    }

    @Transactional(transactionManager = "pgTransactionManager")
    public Map<String, Object> createTextImport(KnowledgeUploadDto.TextImportRequest request) {
        String merchantCode = normalizeMerchantCode(request.getScope(), request.getMerchantCode());
        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("scope", normalizeScope(request.getScope()));
        metadata.put("ingestionStatus", "PROCESSING");
        metadata.put("ingestionSourceType", "TEXT");
        metadata.put("errorMessage", null);

        Long documentId = insertKnowledgeDocument(
                request.getKnowledgeType(),
                generateSourceCode(request.getKnowledgeType()),
                merchantCode,
                request.getTitle(),
                request.getContent(),
                statusToDbValue(request.getStatus()),
                metadata
        );

        asyncService.processTextImport(documentId, request.getContent());
        return Map.of(
                "documentId", documentId,
                "ingestionStatus", "PROCESSING",
                "ingestionSourceType", "TEXT"
        );
    }

    @Transactional(transactionManager = "pgTransactionManager")
    public Map<String, Object> createFileImport(
            String title,
            String knowledgeType,
            String scope,
            String merchantCode,
            String status,
            MultipartFile file
    ) {
        if (file == null || file.isEmpty()) {
            throw new IllegalArgumentException("上传文件不能为空");
        }

        String normalizedMerchantCode = normalizeMerchantCode(scope, merchantCode);
        StoredKnowledgeFile storedFile = storeKnowledgeFile(file);

        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("scope", normalizeScope(scope));
        metadata.put("ingestionStatus", "PROCESSING");
        metadata.put("ingestionSourceType", "FILE");
        metadata.put("fileName", storedFile.fileName());
        metadata.put("fileUrl", storedFile.fileUrl());
        metadata.put("fileStoragePath", storedFile.storagePath().toString());
        metadata.put("errorMessage", null);

        Long documentId = insertKnowledgeDocument(
                knowledgeType,
                generateSourceCode(knowledgeType),
                normalizedMerchantCode,
                title,
                "",
                statusToDbValue(status),
                metadata
        );

        asyncService.processFileImport(documentId, storedFile.storagePath().toString(), storedFile.fileName());
        return Map.of(
                "documentId", documentId,
                "ingestionStatus", "PROCESSING",
                "ingestionSourceType", "FILE",
                "fileName", storedFile.fileName()
        );
    }

    @Transactional(transactionManager = "pgTransactionManager")
    public Map<String, Object> uploadKnowledge(KnowledgeUploadDto.UploadRequest request) {
        KnowledgeUploadDto.TextImportRequest importRequest = new KnowledgeUploadDto.TextImportRequest();
        importRequest.setTitle(request.getTitle());
        importRequest.setKnowledgeType(request.getSourceType());
        importRequest.setScope("MERCHANT");
        importRequest.setMerchantCode(request.getMerchantCode());
        importRequest.setStatus(request.getStatus() != null && request.getStatus() == 0 ? "DISABLED" : "ENABLED");
        importRequest.setContent(request.getContent());
        return createTextImport(importRequest);
    }

    @Transactional(transactionManager = "pgTransactionManager")
    public Map<String, Object> batchUploadKnowledge(List<KnowledgeUploadDto.UploadRequest> requests) {
        List<Map<String, Object>> created = new ArrayList<>();
        for (KnowledgeUploadDto.UploadRequest request : requests) {
            created.add(uploadKnowledge(request));
        }
        return Map.of(
                "successCount", created.size(),
                "totalDocuments", requests.size(),
                "records", created
        );
    }

    public List<KnowledgeUploadDto.KnowledgeInfo> listKnowledge(String sourceType, String merchantCode, Integer page, Integer pageSize) {
        StringBuilder sql = new StringBuilder("""
            SELECT
                d.id, d.source_type, d.source_code, d.merchant_code, d.title, d.content,
                d.product_category, d.scene, d.intent, d.policy_version,
                d.tags, d.metadata, d.status, d.created_at, d.updated_at,
                COUNT(c.id) AS chunk_count
            FROM knowledge_document d
            LEFT JOIN knowledge_chunk c ON c.document_id = d.id
            WHERE COALESCE(d.metadata ->> 'deleted', 'false') <> 'true'
            """);

        List<Object> params = new ArrayList<>();
        if (sourceType != null && !sourceType.isBlank()) {
            sql.append(" AND d.source_type = ?");
            params.add(sourceType);
        }
        if (merchantCode != null && !merchantCode.isBlank()) {
            sql.append(" AND d.merchant_code = ?");
            params.add(merchantCode);
        }

        sql.append(" GROUP BY d.id ORDER BY d.created_at DESC LIMIT ? OFFSET ?");
        params.add(pageSize);
        params.add((page - 1) * pageSize);

        return pgJdbcTemplate.query(sql.toString(), params.toArray(), (rs, rowNum) -> mapKnowledgeInfo(
                rs.getLong("id"),
                rs.getString("source_type"),
                rs.getString("source_code"),
                rs.getString("merchant_code"),
                rs.getString("title"),
                rs.getString("content"),
                rs.getString("product_category"),
                rs.getString("scene"),
                rs.getString("intent"),
                rs.getString("policy_version"),
                rs.getString("tags"),
                rs.getString("metadata"),
                rs.getInt("status"),
                rs.getTimestamp("created_at"),
                rs.getTimestamp("updated_at"),
                rs.getInt("chunk_count")
        ));
    }

    public KnowledgeUploadDto.KnowledgeInfo getKnowledgeById(Long id) {
        List<KnowledgeUploadDto.KnowledgeInfo> result = pgJdbcTemplate.query(
                """
                SELECT
                    d.id, d.source_type, d.source_code, d.merchant_code, d.title, d.content,
                    d.product_category, d.scene, d.intent, d.policy_version,
                    d.tags, d.metadata, d.status, d.created_at, d.updated_at,
                    COUNT(c.id) AS chunk_count
                FROM knowledge_document d
                LEFT JOIN knowledge_chunk c ON c.document_id = d.id
                WHERE d.id = ? AND COALESCE(d.metadata ->> 'deleted', 'false') <> 'true'
                GROUP BY d.id
                LIMIT 1
                """,
                new Object[]{id},
                (rs, rowNum) -> mapKnowledgeInfo(
                        rs.getLong("id"),
                        rs.getString("source_type"),
                        rs.getString("source_code"),
                        rs.getString("merchant_code"),
                        rs.getString("title"),
                        rs.getString("content"),
                        rs.getString("product_category"),
                        rs.getString("scene"),
                        rs.getString("intent"),
                        rs.getString("policy_version"),
                        rs.getString("tags"),
                        rs.getString("metadata"),
                        rs.getInt("status"),
                        rs.getTimestamp("created_at"),
                        rs.getTimestamp("updated_at"),
                        rs.getInt("chunk_count")
                )
        );
        return result.isEmpty() ? null : result.get(0);
    }

    @Transactional(transactionManager = "pgTransactionManager")
    public Map<String, Object> updateKnowledge(Long id, KnowledgeUploadDto.UpdateRequest request) {
        KnowledgeUploadDto.KnowledgeInfo current = getKnowledgeById(id);
        if (current == null) {
            throw new IllegalArgumentException("Knowledge document not found: " + id);
        }

        Map<String, Object> metadata = new LinkedHashMap<>(current.getMetadata() == null ? Map.of() : current.getMetadata());
        pgJdbcTemplate.update(
                """
                UPDATE knowledge_document
                SET title = COALESCE(?, title),
                    merchant_code = COALESCE(?, merchant_code),
                    status = COALESCE(?, status),
                    metadata = ?::jsonb,
                    updated_at = NOW()
                WHERE id = ?
                """,
                request.getTitle(),
                request.getMerchantCode(),
                request.getStatus(),
                toJson(metadata),
                id
        );

        if (request.getContent() != null) {
            metadata.put("ingestionStatus", "PROCESSING");
            metadata.put("ingestionSourceType", "TEXT");
            metadata.put("errorMessage", null);
            pgJdbcTemplate.update(
                    "UPDATE knowledge_document SET content = ?, metadata = ?::jsonb, updated_at = NOW() WHERE id = ?",
                    request.getContent(),
                    toJson(metadata),
                    id
            );
            asyncService.processTextImport(id, request.getContent());
        }

        return Map.of("documentId", id, "updated", true);
    }

    @Transactional(transactionManager = "pgTransactionManager")
    public void deleteKnowledge(Long id) {
        pgJdbcTemplate.update(
                """
                UPDATE knowledge_document
                SET metadata = jsonb_set(COALESCE(metadata, '{}'::jsonb), '{deleted}', 'true'::jsonb, true),
                    updated_at = NOW()
                WHERE id = ?
                """,
                id
        );
    }

    public Map<String, Object> reindexAll() {
        List<Long> ids = pgJdbcTemplate.queryForList(
                """
                SELECT id
                FROM knowledge_document
                WHERE COALESCE(metadata ->> 'deleted', 'false') <> 'true'
                """,
                Long.class
        );
        ids.forEach(asyncService::reprocessDocument);
        return Map.of("count", ids.size(), "message", "Reindex started");
    }

    public Map<String, Object> syncKnowledge(Long id) {
        KnowledgeUploadDto.KnowledgeInfo info = getKnowledgeById(id);
        if (info == null) {
            throw new IllegalArgumentException("Knowledge document not found: " + id);
        }

        Map<String, Object> metadata = new LinkedHashMap<>(info.getMetadata() == null ? Map.of() : info.getMetadata());
        metadata.put("ingestionStatus", "PROCESSING");
        metadata.put("errorMessage", null);
        pgJdbcTemplate.update(
                "UPDATE knowledge_document SET metadata = ?::jsonb, updated_at = NOW() WHERE id = ?",
                toJson(metadata),
                id
        );
        asyncService.reprocessDocument(id);
        return Map.of("documentId", id, "message", "Knowledge sync started");
    }

    public List<Map<String, Object>> testRetrieval(String query, String merchantCode, Integer topK) {
        log.info("Test retrieval: query={}, merchantCode={}, topK={}", query, merchantCode, topK);
        return List.of();
    }

    private Long insertKnowledgeDocument(
            String sourceType,
            String sourceCode,
            String merchantCode,
            String title,
            String content,
            Integer status,
            Map<String, Object> metadata
    ) {
        return pgJdbcTemplate.queryForObject(
                """
                INSERT INTO knowledge_document (
                    source_type, source_code, merchant_code, title, content,
                    metadata, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?::jsonb, ?, NOW(), NOW())
                RETURNING id
                """,
                Long.class,
                normalizeKnowledgeType(sourceType),
                sourceCode,
                merchantCode,
                title,
                content == null ? "" : content,
                toJson(metadata),
                status
        );
    }

    private KnowledgeUploadDto.KnowledgeInfo mapKnowledgeInfo(
            Long id,
            String sourceType,
            String sourceCode,
            String merchantCode,
            String title,
            String content,
            String productCategory,
            String scene,
            String intent,
            String policyVersion,
            String tagsJson,
            String metadataJson,
            Integer status,
            Timestamp createdAt,
            Timestamp updatedAt,
            Integer chunkCount
    ) {
        Map<String, Object> metadata = parseJsonToMap(metadataJson);
        KnowledgeUploadDto.KnowledgeInfo info = new KnowledgeUploadDto.KnowledgeInfo();
        info.setId(id);
        info.setSourceType(sourceType);
        info.setSourceCode(sourceCode);
        info.setMerchantCode(merchantCode);
        info.setTitle(title);
        info.setContent(content);
        info.setProductCategory(productCategory);
        info.setScene(scene);
        info.setIntent(intent);
        info.setPolicyVersion(policyVersion);
        info.setTags(parseJsonToStringList(tagsJson));
        info.setMetadata(metadata);
        info.setStatus(status);
        info.setCreatedAt(createdAt == null ? null : createdAt.toLocalDateTime());
        info.setUpdatedAt(updatedAt == null ? null : updatedAt.toLocalDateTime());
        info.setChunkCount(chunkCount);
        info.setIngestionStatus(stringMetadata(metadata, "ingestionStatus", "SUCCESS"));
        info.setIngestionSourceType(stringMetadata(metadata, "ingestionSourceType", "TEXT"));
        info.setFileName(stringMetadata(metadata, "fileName", null));
        info.setFileUrl(stringMetadata(metadata, "fileUrl", null));
        info.setErrorMessage(stringMetadata(metadata, "errorMessage", null));
        info.setScope(stringMetadata(metadata, "scope", "MERCHANT"));
        return info;
    }

    private StoredKnowledgeFile storeKnowledgeFile(MultipartFile file) {
        try {
            String dateDir = LocalDate.now().format(DateTimeFormatter.ofPattern("yyyy/MM/dd"));
            Path targetDir = uploadRoot.resolve("knowledge").resolve(dateDir);
            Files.createDirectories(targetDir);

            String originalFilename = file.getOriginalFilename() == null ? "knowledge.txt" : file.getOriginalFilename();
            String extension = "";
            int dotIndex = originalFilename.lastIndexOf('.');
            if (dotIndex >= 0) {
                extension = originalFilename.substring(dotIndex);
            }
            String storedFilename = UUID.randomUUID() + extension;
            Path targetPath = targetDir.resolve(storedFilename);
            file.transferTo(targetPath.toFile());

            String fileUrl = "/uploads/knowledge/" + dateDir + "/" + storedFilename;
            return new StoredKnowledgeFile(originalFilename, fileUrl, targetPath);
        } catch (IOException e) {
            throw new IllegalStateException("Failed to store upload file", e);
        }
    }

    private String normalizeKnowledgeType(String knowledgeType) {
        return (knowledgeType == null || knowledgeType.isBlank()) ? "faq" : knowledgeType;
    }

    private String generateSourceCode(String knowledgeType) {
        return normalizeKnowledgeType(knowledgeType) + "_" + UUID.randomUUID().toString().replace("-", "");
    }

    private String normalizeScope(String scope) {
        return (scope == null || scope.isBlank()) ? "MERCHANT" : scope.toUpperCase();
    }

    private String normalizeMerchantCode(String scope, String merchantCode) {
        if ("GLOBAL".equalsIgnoreCase(scope)) {
            return "GLOBAL";
        }
        return (merchantCode == null || merchantCode.isBlank()) ? "MERCHANT_DEMO" : merchantCode;
    }

    private Integer statusToDbValue(String status) {
        return "DISABLED".equalsIgnoreCase(status) ? 0 : 1;
    }

    private String toJson(Object obj) {
        if (obj == null) {
            return "{}";
        }
        try {
            return OBJECT_MAPPER.writeValueAsString(obj);
        } catch (Exception e) {
            throw new IllegalStateException("Failed to serialize json", e);
        }
    }

    private List<String> parseJsonToStringList(String json) {
        if (json == null || json.isBlank()) {
            return null;
        }
        try {
            return OBJECT_MAPPER.readValue(json, new TypeReference<>() {});
        } catch (Exception e) {
            log.warn("Failed to parse tags json: {}", json, e);
            return null;
        }
    }

    private Map<String, Object> parseJsonToMap(String json) {
        if (json == null || json.isBlank()) {
            return new LinkedHashMap<>();
        }
        try {
            return OBJECT_MAPPER.readValue(json, new TypeReference<>() {});
        } catch (Exception e) {
            log.warn("Failed to parse metadata json: {}", json, e);
            return new LinkedHashMap<>();
        }
    }

    private String stringMetadata(Map<String, Object> metadata, String key, String defaultValue) {
        Object value = metadata.get(key);
        return value == null ? defaultValue : String.valueOf(value);
    }

    private record StoredKnowledgeFile(String fileName, String fileUrl, Path storagePath) {}
}
