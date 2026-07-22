package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.common.KnowledgeRevisionConflictException;
import com.ecommerce.aftersales.common.enums.ErrorCode;
import com.ecommerce.aftersales.config.KnowledgeUploadProperties;
import com.ecommerce.aftersales.dto.KnowledgeUploadDto;
import com.ecommerce.aftersales.dto.KnowledgeDraftDtos.DraftChunkResponse;
import com.ecommerce.aftersales.dto.KnowledgeDraftDtos.FileImportCommand;
import com.ecommerce.aftersales.dto.KnowledgeDraftDtos.FileImportResponse;
import com.ecommerce.aftersales.dto.KnowledgeDraftDtos.IngestionStatusResponse;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.Timestamp;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

@Service
@Slf4j
public class KnowledgeService {

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
    private static final Set<String> RESERVED_METADATA_KEYS = Set.of(
            "scope", "ingestionStatus", "ingestionSourceType", "errorMessage",
            "chunkCount", "fileName", "fileUrl", "fileStoragePath", "deleted"
    );

    private final JdbcTemplate pgJdbcTemplate;
    private final KnowledgeIngestionAsyncService asyncService;
    private final KnowledgeMetadataPolicy metadataPolicy;
    private final KnowledgeDraftService draftService;
    private final Path uploadRoot;
    private final long maxFileBytes;

    @Autowired
    public KnowledgeService(
            @Qualifier("pgJdbcTemplate") JdbcTemplate pgJdbcTemplate,
            KnowledgeIngestionAsyncService asyncService,
            KnowledgeMetadataPolicy metadataPolicy,
            KnowledgeDraftService draftService,
            @Value("${app.upload.dir:./uploads}") String uploadDir,
            KnowledgeUploadProperties uploadProperties
    ) throws IOException {
        this.pgJdbcTemplate = pgJdbcTemplate;
        this.asyncService = asyncService;
        this.metadataPolicy = metadataPolicy;
        this.draftService = draftService;
        this.uploadRoot = Paths.get(uploadDir).toAbsolutePath().normalize();
        this.maxFileBytes = uploadProperties.getMaxFileBytes();
        Files.createDirectories(this.uploadRoot.resolve("knowledge"));
    }

    KnowledgeService(
            JdbcTemplate pgJdbcTemplate,
            KnowledgeIngestionAsyncService asyncService,
            KnowledgeMetadataPolicy metadataPolicy,
            KnowledgeDraftService draftService,
            String uploadDir
    ) throws IOException {
        this(pgJdbcTemplate, asyncService, metadataPolicy, draftService, uploadDir, new KnowledgeUploadProperties());
    }

    KnowledgeService(
            JdbcTemplate pgJdbcTemplate,
            KnowledgeIngestionAsyncService asyncService,
            KnowledgeMetadataPolicy metadataPolicy,
            String uploadDir
    ) throws IOException {
        this(pgJdbcTemplate, asyncService, metadataPolicy, new KnowledgeDraftService(pgJdbcTemplate), uploadDir);
    }

    @Transactional(transactionManager = "pgTransactionManager")
    Map<String, Object> createTextImport(KnowledgeUploadDto.TextImportRequest request) {
        String knowledgeType = normalizeKnowledgeType(request.getKnowledgeType());
        String merchantCode = normalizeMerchantCode(request.getScope(), request.getMerchantCode());
        Map<String, Object> metadata = copyCustomMetadata(request.getMetadata());
        metadata.put("scope", normalizeScope(request.getScope()));
        metadata.put("ingestionStatus", "PROCESSING");
        metadata.put("ingestionSourceType", "TEXT");
        metadata.put("errorMessage", null);

        Long documentId = insertKnowledgeDocument(
                knowledgeType,
                normalizeSourceCode(request.getSourceCode(), knowledgeType),
                merchantCode,
                request.getTitle(),
                request.getContent(),
                metadataPolicy.normalizeProductCategory(request.getProductCategory()),
                metadataPolicy.normalizeScene(request.getScene()),
                metadataPolicy.normalizeIntent(request.getIntent()),
                metadataPolicy.resolvePolicyVersion(knowledgeType, merchantCode),
                request.getTags(),
                statusToDbValue(request.getStatus()),
                metadata
        );

        runAfterCommit(() -> asyncService.processTextImport(documentId, request.getContent(), 1L));
        return Map.of(
                "documentId", documentId,
                "ingestionStatus", "PROCESSING",
                "ingestionSourceType", "TEXT"
        );
    }

    @Transactional(transactionManager = "pgTransactionManager")
    Map<String, Object> createFileImport(
            String title,
            String knowledgeType,
            String scope,
            String merchantCode,
            String status,
            String sourceCode,
            String productCategory,
            String scene,
            String intent,
            List<String> tags,
            MultipartFile file
    ) {
        if (file == null || file.isEmpty()) {
            throw new IllegalArgumentException("上传文件不能为空");
        }

        validateFileSize(file);
        String normalizedMerchantCode = normalizeMerchantCode(scope, merchantCode);
        String normalizedKnowledgeType = normalizeKnowledgeType(knowledgeType);
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
                normalizedKnowledgeType,
                normalizeSourceCode(sourceCode, normalizedKnowledgeType),
                normalizedMerchantCode,
                title,
                "",
                metadataPolicy.normalizeProductCategory(productCategory),
                metadataPolicy.normalizeScene(scene),
                metadataPolicy.normalizeIntent(intent),
                metadataPolicy.resolvePolicyVersion(normalizedKnowledgeType, normalizedMerchantCode),
                tags,
                statusToDbValue(status),
                metadata
        );

        runAfterCommit(() -> asyncService.processFileImport(
                documentId,
                storedFile.storagePath().toString(),
                storedFile.fileName(),
                1L
        ));
        return Map.of(
                "documentId", documentId,
                "ingestionStatus", "PROCESSING",
                "ingestionSourceType", "FILE",
                "fileName", storedFile.fileName()
        );
    }

    @Transactional(transactionManager = "pgTransactionManager")
    public FileImportResponse createFileImport(FileImportCommand command) {
        MultipartFile file = command == null ? null : command.file();
        if (file == null || file.isEmpty()) throw new IllegalArgumentException("Uploaded file must not be empty");
        validateFileSize(file);
        String fileName = normalizedFileName(file.getOriginalFilename());
        validateFileType(fileName, file.getContentType());
        String knowledgeType = normalizeKnowledgeType(command.knowledgeType());
        String merchantCode = normalizeMerchantCode(command.scope(), command.merchantCode());
        byte[] bytes;
        try { bytes = file.getBytes(); } catch (IOException e) { throw new IllegalArgumentException("Unable to read uploaded file", e); }
        String contentHash = sha256(bytes);
        List<Map<String, Object>> duplicates = pgJdbcTemplate.queryForList("""
                SELECT id, review_status FROM knowledge_document
                WHERE merchant_code = ? AND source_type = ? AND content_hash = ?
                  AND COALESCE(metadata ->> 'deleted', 'false') <> 'true'
                LIMIT 1
                """, merchantCode, knowledgeType, contentHash);
        if (!duplicates.isEmpty()) return duplicateResponse(duplicates.getFirst());

        StoredKnowledgeFile stored = storeKnowledgeFile(file);
        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("scope", normalizeScope(command.scope()));
        metadata.put("ingestionSourceType", "FILE");
        metadata.put("fileName", fileName);
        metadata.put("fileUrl", stored.fileUrl());
        metadata.put("fileStoragePath", stored.storagePath().toString());
        metadata.put("errorCode", null);
        metadata.put("errorMessage", null);
        String title = normalizeOptional(command.title());
        if (title == null) title = fileName.substring(0, fileName.lastIndexOf('.'));
        Long documentId;
        try {
            documentId = pgJdbcTemplate.queryForObject("""
                    INSERT INTO knowledge_document (source_type, source_code, merchant_code, title, content, metadata,
                        status, review_status, content_hash, revision, published_revision, created_at, updated_at)
                    VALUES (?, ?, ?, ?, '', ?::jsonb, 1, 'PROCESSING', ?, 1, NULL, NOW(), NOW())
                    ON CONFLICT (merchant_code, source_type, content_hash)
                    WHERE content_hash IS NOT NULL AND COALESCE(metadata ->> 'deleted', 'false') <> 'true'
                    DO NOTHING RETURNING id
                    """, Long.class, knowledgeType, generateSourceCode(knowledgeType), merchantCode, title,
                toJson(metadata), contentHash);
        } catch (EmptyResultDataAccessException ignored) {
            documentId = null;
        }
        if (documentId == null) {
            deleteStoredFileQuietly(stored.storagePath());
            List<Map<String, Object>> active = pgJdbcTemplate.queryForList("""
                    SELECT id, review_status FROM knowledge_document
                    WHERE merchant_code = ? AND source_type = ? AND content_hash = ?
                      AND COALESCE(metadata ->> 'deleted', 'false') <> 'true'
                    LIMIT 1
            """, merchantCode, knowledgeType, contentHash);
            if (!active.isEmpty()) {
                return duplicateResponse(active.getFirst());
            }
            throw new IllegalStateException("Duplicate knowledge import was not found after conflict");
        }
        Long insertedDocumentId = documentId;
        runAfterCommit(() -> asyncService.processFileImport(insertedDocumentId, stored.storagePath().toString(), fileName, 1L));
        return new FileImportResponse(insertedDocumentId, "PROCESSING", false);
    }

    public IngestionStatusResponse ingestionStatus(Long documentId) {
        return draftService.ingestionStatus(documentId);
    }

    public List<DraftChunkResponse> draft(Long documentId) {
        return draftService.draft(documentId);
    }

    @Transactional(transactionManager = "pgTransactionManager")
    public IngestionStatusResponse retryFileImport(Long documentId) {
        Long targetRevision;
        try {
            targetRevision = pgJdbcTemplate.queryForObject("""
                    UPDATE knowledge_document SET review_status = 'PROCESSING', revision = revision + 1,
                        metadata = COALESCE(metadata, '{}'::jsonb) - 'errorCode' - 'errorMessage', updated_at = NOW()
                    WHERE id = ? AND COALESCE(metadata ->> 'ingestionSourceType', '') = 'FILE'
                      AND review_status IN ('PARSE_FAILED', 'CLASSIFY_FAILED', 'EMBEDDING_FAILED')
                      AND COALESCE(metadata ->> 'deleted', 'false') <> 'true'
                    RETURNING revision
                    """, Long.class, documentId);
        } catch (EmptyResultDataAccessException exception) {
            throw new BizException(ErrorCode.NOT_FOUND, "Knowledge file document is not retryable");
        }
        runAfterCommit(() -> asyncService.reprocessDocument(documentId, targetRevision));
        return ingestionStatus(documentId);
    }

    @Transactional(transactionManager = "pgTransactionManager")
    Map<String, Object> uploadKnowledge(KnowledgeUploadDto.UploadRequest request) {
        KnowledgeUploadDto.TextImportRequest importRequest = new KnowledgeUploadDto.TextImportRequest();
        importRequest.setTitle(request.getTitle());
        importRequest.setKnowledgeType(request.getSourceType());
        importRequest.setSourceCode(request.getSourceCode());
        importRequest.setScope("MERCHANT");
        importRequest.setMerchantCode(request.getMerchantCode());
        importRequest.setStatus(request.getStatus() != null && request.getStatus() == 0 ? "DISABLED" : "ENABLED");
        importRequest.setContent(request.getContent());
        importRequest.setProductCategory(request.getProductCategory());
        importRequest.setScene(request.getScene());
        importRequest.setIntent(request.getIntent());
        importRequest.setPolicyVersion(request.getPolicyVersion());
        importRequest.setTags(request.getTags());
        importRequest.setMetadata(request.getMetadata());
        return createTextImport(importRequest);
    }

    @Transactional(transactionManager = "pgTransactionManager")
    Map<String, Object> batchUploadKnowledge(List<KnowledgeUploadDto.UploadRequest> requests) {
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
                d.review_status, d.revision, d.published_revision, d.valid_from, d.valid_to,
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
                rs.getString("review_status"),
                rs.getLong("revision"),
                (Long) rs.getObject("published_revision"),
                rs.getTimestamp("valid_from"),
                rs.getTimestamp("valid_to"),
                rs.getString("tags"),
                rs.getString("metadata"),
                rs.getInt("status"),
                rs.getTimestamp("created_at"),
                rs.getTimestamp("updated_at"),
                rs.getInt("chunk_count")
        ));
    }

    public Map<String, Object> getMetadataOptions(String merchantCode) {
        String normalizedMerchantCode = "GLOBAL".equalsIgnoreCase(merchantCode)
                ? "GLOBAL"
                : normalizeMerchantCode("MERCHANT", merchantCode);
        return metadataPolicy.options(normalizedMerchantCode);
    }

    public KnowledgeUploadDto.KnowledgeInfo getKnowledgeById(Long id) {
        List<KnowledgeUploadDto.KnowledgeInfo> result = pgJdbcTemplate.query(
                """
                SELECT
                    d.id, d.source_type, d.source_code, d.merchant_code, d.title, d.content,
                    d.product_category, d.scene, d.intent, d.policy_version,
                    d.review_status, d.revision, d.published_revision, d.valid_from, d.valid_to,
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
                        rs.getString("review_status"),
                        rs.getLong("revision"),
                        (Long) rs.getObject("published_revision"),
                        rs.getTimestamp("valid_from"),
                        rs.getTimestamp("valid_to"),
                        rs.getString("tags"),
                        rs.getString("metadata"),
                        rs.getInt("status"),
                        rs.getTimestamp("created_at"),
                        rs.getTimestamp("updated_at"),
                        rs.getInt("chunk_count")
                )
        );
        if (result.isEmpty()) {
            throw new BizException(ErrorCode.NOT_FOUND, "知识文档不存在或已删除");
        }
        return result.get(0);
    }

    @Transactional(transactionManager = "pgTransactionManager")
    public Map<String, Object> updateKnowledge(Long id, KnowledgeUploadDto.UpdateRequest request) {
        KnowledgeUploadDto.KnowledgeInfo current = getKnowledgeById(id);

        Map<String, Object> metadata = new LinkedHashMap<>(current.getMetadata() == null ? Map.of() : current.getMetadata());
        mergeCustomMetadata(metadata, request.getMetadata());
        boolean productCategoryProvided = request.getProductCategory() != null;
        boolean sceneProvided = request.getScene() != null;
        boolean intentProvided = request.getIntent() != null;
        boolean policyVersionProvided = request.getPolicyVersion() != null || request.getContent() != null;
        boolean tagsProvided = request.getTags() != null;
        String effectiveMerchantCode = normalizeOptional(request.getMerchantCode()) == null
                ? current.getMerchantCode()
                : normalizeMerchantCode("MERCHANT", request.getMerchantCode());
        String normalizedProductCategory = productCategoryProvided
                ? metadataPolicy.normalizeProductCategory(request.getProductCategory())
                : null;
        String normalizedScene = sceneProvided ? metadataPolicy.normalizeScene(request.getScene()) : null;
        String normalizedIntent = intentProvided ? metadataPolicy.normalizeIntent(request.getIntent()) : null;
        String normalizedPolicyVersion = policyVersionProvided
                ? metadataPolicy.resolvePolicyVersion(current.getSourceType(), effectiveMerchantCode)
                : null;
        if (request.getContent() == null) {
            pgJdbcTemplate.update(
                    """
                    UPDATE knowledge_document
                    SET title = COALESCE(?, title),
                        merchant_code = COALESCE(?, merchant_code),
                        status = COALESCE(?, status),
                        product_category = CASE WHEN ? THEN ? ELSE product_category END,
                        scene = CASE WHEN ? THEN ? ELSE scene END,
                        intent = CASE WHEN ? THEN ? ELSE intent END,
                        policy_version = CASE WHEN ? THEN ? ELSE policy_version END,
                        tags = CASE WHEN ? THEN ?::jsonb ELSE tags END,
                        metadata = ?::jsonb,
                        updated_at = NOW()
                    WHERE id = ?
                    """,
                    request.getTitle(), normalizeOptional(request.getMerchantCode()), request.getStatus(),
                    productCategoryProvided, normalizedProductCategory, sceneProvided, normalizedScene,
                    intentProvided, normalizedIntent, policyVersionProvided, normalizedPolicyVersion,
                    tagsProvided, toNullableJson(normalizeTags(request.getTags())), toJson(metadata), id
            );
        } else {
            metadata.put("ingestionStatus", "PROCESSING");
            metadata.put("ingestionSourceType", "TEXT");
            metadata.remove("errorCode");
            metadata.remove("errorMessage");
            Long targetRevision;
            try {
                targetRevision = pgJdbcTemplate.queryForObject(
                        """
                        UPDATE knowledge_document
                        SET title = COALESCE(?, title),
                            merchant_code = COALESCE(?, merchant_code),
                            status = COALESCE(?, status),
                            product_category = CASE WHEN ? THEN ? ELSE product_category END,
                            scene = CASE WHEN ? THEN ? ELSE scene END,
                            intent = CASE WHEN ? THEN ? ELSE intent END,
                            policy_version = CASE WHEN ? THEN ? ELSE policy_version END,
                            tags = CASE WHEN ? THEN ?::jsonb ELSE tags END,
                            content = ?, metadata = (?::jsonb - 'errorCode' - 'errorMessage'),
                            revision = revision + 1, review_status = 'PROCESSING', updated_at = NOW()
                        WHERE id = ? AND revision = ?
                          AND review_status IN ('PUBLISHED', 'REVIEW_REQUIRED', 'PARSE_FAILED', 'CLASSIFY_FAILED', 'EMBEDDING_FAILED')
                          AND COALESCE(metadata ->> 'deleted', 'false') <> 'true'
                        RETURNING revision
                        """,
                        Long.class,
                        request.getTitle(), normalizeOptional(request.getMerchantCode()), request.getStatus(),
                        productCategoryProvided, normalizedProductCategory, sceneProvided, normalizedScene,
                        intentProvided, normalizedIntent, policyVersionProvided, normalizedPolicyVersion,
                        tagsProvided, toNullableJson(normalizeTags(request.getTags())), request.getContent(),
                        toJson(metadata), id, current.getRevision()
                );
            } catch (EmptyResultDataAccessException ignored) {
                targetRevision = null;
            }
            if (targetRevision == null) {
                throw new KnowledgeRevisionConflictException(
                        current.getRevision() == null ? 0L : current.getRevision(), current.getReviewStatus());
            }
            long frozenRevision = targetRevision;
            runAfterCommit(() -> asyncService.processTextImport(id, request.getContent(), frozenRevision));
        }

        syncChunkMetadata(id);

        return Map.of("documentId", id, "updated", true);
    }

    @Transactional(transactionManager = "pgTransactionManager")
    public void deleteKnowledge(Long id) {
        int updated = pgJdbcTemplate.update(
                """
                UPDATE knowledge_document
                SET metadata = jsonb_set(COALESCE(metadata, '{}'::jsonb), '{deleted}', 'true'::jsonb, true),
                    updated_at = NOW()
                WHERE id = ?
                """,
                id
        );
        if (updated == 0) {
            throw new BizException(ErrorCode.NOT_FOUND, "知识文档不存在或已删除");
        }
    }

    @Transactional(transactionManager = "pgTransactionManager")
    public Map<String, Object> reindexAll() {
        List<Long> ids = pgJdbcTemplate.queryForList(
                """
                SELECT id
                FROM knowledge_document
                WHERE COALESCE(metadata ->> 'deleted', 'false') <> 'true'
                """,
                Long.class
        );
        ids.forEach(this::scheduleReprocess);
        return Map.of("count", ids.size(), "message", "Reindex started");
    }

    @Transactional(transactionManager = "pgTransactionManager")
    public Map<String, Object> syncKnowledge(Long id) {
        KnowledgeUploadDto.KnowledgeInfo info = getKnowledgeById(id);

        scheduleReprocess(id);
        return Map.of("documentId", String.valueOf(id), "message", "Knowledge sync started");
    }

    private void scheduleReprocess(Long documentId) {
        Long targetRevision;
        try {
            targetRevision = pgJdbcTemplate.queryForObject("""
                    UPDATE knowledge_document SET revision = revision + 1, review_status = 'PROCESSING',
                        metadata = COALESCE(metadata, '{}'::jsonb) - 'errorCode' - 'errorMessage', updated_at = NOW()
                    WHERE id = ? AND COALESCE(metadata ->> 'ingestionSourceType', '') IN ('FILE', 'TEXT')
                      AND COALESCE(metadata ->> 'deleted', 'false') <> 'true'
                      AND review_status IN ('PUBLISHED', 'REVIEW_REQUIRED', 'PARSE_FAILED', 'CLASSIFY_FAILED', 'EMBEDDING_FAILED')
                    RETURNING revision
                    """, Long.class, documentId);
        } catch (EmptyResultDataAccessException ignored) {
            return;
        }
        runAfterCommit(() -> asyncService.reprocessDocument(documentId, targetRevision));
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
            String productCategory,
            String scene,
            String intent,
            String policyVersion,
            List<String> tags,
            Integer status,
            Map<String, Object> metadata
    ) {
        return pgJdbcTemplate.queryForObject(
                """
                INSERT INTO knowledge_document (
                    source_type, source_code, merchant_code, title, content,
                    product_category, scene, intent, policy_version, tags,
                    metadata, status, review_status, revision, published_revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?::jsonb, ?, 'PROCESSING', 1, NULL, NOW(), NOW())
                RETURNING id
                """,
                Long.class,
                normalizeKnowledgeType(sourceType),
                sourceCode,
                merchantCode,
                title,
                content == null ? "" : content,
                normalizeOptional(productCategory),
                normalizeOptional(scene),
                normalizeOptional(intent),
                normalizeOptional(policyVersion),
                toNullableJson(normalizeTags(tags)),
                toJson(metadata),
                status
        );
    }

    private void syncChunkMetadata(Long documentId) {
        pgJdbcTemplate.update(
                """
                UPDATE knowledge_chunk kc
                SET metadata = COALESCE(kc.metadata, '{}'::jsonb) || jsonb_build_object(
                    'title', kd.title,
                    'source_type', kd.source_type,
                    'source_code', kd.source_code,
                    'merchant_code', kd.merchant_code,
                    'product_category', kd.product_category,
                    'scene', kd.scene,
                    'intent', kd.intent,
                    'policy_version', kd.policy_version,
                    'tags', COALESCE(kd.tags, '[]'::jsonb)
                )
                FROM knowledge_document kd
                WHERE kc.document_id = kd.id AND kd.id = ?
                """,
                documentId
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
            String reviewStatus,
            Long revision,
            Long publishedRevision,
            Timestamp validFrom,
            Timestamp validTo,
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
        info.setReviewStatus(reviewStatus);
        info.setRevision(revision);
        info.setPublishedRevision(publishedRevision);
        info.setValidFrom(validFrom == null ? null : validFrom.toLocalDateTime());
        info.setValidTo(validTo == null ? null : validTo.toLocalDateTime());
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

    private String normalizedFileName(String originalFilename) {
        String fileName = originalFilename == null ? "" : Path.of(originalFilename).getFileName().toString().trim();
        if (fileName.isBlank() || !fileName.contains(".")) throw new IllegalArgumentException("Unsupported file type");
        return fileName;
    }

    private void validateFileType(String fileName, String contentType) {
        String extension = fileName.substring(fileName.lastIndexOf('.')).toLowerCase(java.util.Locale.ROOT);
        Map<String, Set<String>> supported = Map.of(
                ".pdf", Set.of("application/pdf"),
                ".md", Set.of("text/markdown", "text/plain"),
                ".txt", Set.of("text/plain")
        );
        Set<String> allowed = supported.get(extension);
        if (allowed == null || contentType == null || contentType.isBlank()
                || !allowed.contains(contentType.toLowerCase(java.util.Locale.ROOT))) {
            throw new IllegalArgumentException("Unsupported file type");
        }
    }

    private void validateFileSize(MultipartFile file) {
        if (file.getSize() > maxFileBytes) {
            throw new IllegalArgumentException("File must not exceed configured maximum size");
        }
    }

    private FileImportResponse duplicateResponse(Map<String, Object> document) {
        Object id = document.get("id");
        Long documentId = id instanceof Number number ? number.longValue() : Long.valueOf(String.valueOf(id));
        return new FileImportResponse(documentId, String.valueOf(document.get("review_status")), true);
    }

    private void deleteStoredFileQuietly(Path path) {
        try { Files.deleteIfExists(path); }
        catch (IOException exception) { log.warn("Unable to clean duplicate upload {}", path, exception); }
    }

    private String sha256(byte[] content) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(content);
            StringBuilder result = new StringBuilder(64);
            for (byte value : digest) result.append(String.format("%02x", value));
            return result.toString();
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 is unavailable", e);
        }
    }

    private String normalizeKnowledgeType(String knowledgeType) {
        return (knowledgeType == null || knowledgeType.isBlank())
                ? "faq"
                : knowledgeType.trim().toLowerCase(java.util.Locale.ROOT);
    }

    private String generateSourceCode(String knowledgeType) {
        return normalizeKnowledgeType(knowledgeType) + "_" + UUID.randomUUID().toString().replace("-", "");
    }

    private String normalizeSourceCode(String sourceCode, String knowledgeType) {
        String normalized = normalizeOptional(sourceCode);
        return normalized == null ? generateSourceCode(knowledgeType) : normalized;
    }

    private String normalizeOptional(String value) {
        if (value == null) {
            return null;
        }
        String normalized = value.trim();
        return normalized.isEmpty() ? null : normalized;
    }

    private List<String> normalizeTags(List<String> tags) {
        if (tags == null) {
            return null;
        }
        return tags.stream()
                .map(this::normalizeOptional)
                .filter(java.util.Objects::nonNull)
                .distinct()
                .toList();
    }

    private Map<String, Object> copyCustomMetadata(Map<String, Object> customMetadata) {
        Map<String, Object> result = new LinkedHashMap<>();
        mergeCustomMetadata(result, customMetadata);
        return result;
    }

    private void mergeCustomMetadata(Map<String, Object> target, Map<String, Object> customMetadata) {
        if (customMetadata == null) {
            return;
        }
        customMetadata.forEach((key, value) -> {
            if (key != null && !RESERVED_METADATA_KEYS.contains(key)) {
                target.put(key, value);
            }
        });
    }

    private String normalizeScope(String scope) {
        return (scope == null || scope.isBlank()) ? "MERCHANT" : scope.toUpperCase();
    }

    private String normalizeMerchantCode(String scope, String merchantCode) {
        if ("GLOBAL".equalsIgnoreCase(scope)) {
            return "GLOBAL";
        }
        return metadataPolicy.normalizeMerchantCode(merchantCode);
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

    private String toNullableJson(Object obj) {
        return obj == null ? null : toJson(obj);
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

    private void runAfterCommit(Runnable task) {
        if (!TransactionSynchronizationManager.isActualTransactionActive()) {
            task.run();
            return;
        }
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                task.run();
            }
        });
    }

    private record StoredKnowledgeFile(String fileName, String fileUrl, Path storagePath) {}
}
