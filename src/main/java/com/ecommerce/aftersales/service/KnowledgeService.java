package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.dto.KnowledgeUploadDto;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.client.RestTemplate;

import java.time.LocalDateTime;
import java.util.*;
import java.util.stream.Collectors;

/**
 * 知识库服务
 * 负责知识库的CRUD和向量化
 */
@Service
@Slf4j
@RequiredArgsConstructor
public class KnowledgeService {

    private final JdbcTemplate pgJdbcTemplate; // 注入PgVector数据源的JdbcTemplate
    private final RestTemplate restTemplate;

    @Value("${python.agent.url:http://localhost:8765}")
    private String pythonAgentUrl;

    /**
     * 上传知识库
     */
    @Transactional(transactionManager = "pgTransactionManager")
    public Map<String, Object> uploadKnowledge(KnowledgeUploadDto.UploadRequest request) {
        // 1. 插入文档到knowledge_document
        String insertDocSql = """
            INSERT INTO knowledge_document (
                source_type, source_code, merchant_code, title, content,
                product_category, scene, intent, policy_version,
                tags, metadata, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?::jsonb, 1, NOW(), NOW())
            RETURNING id
            """;

        Long documentId = pgJdbcTemplate.queryForObject(
            insertDocSql,
            Long.class,
            request.getSourceType(),
            request.getSourceCode(),
            request.getMerchantCode(),
            request.getTitle(),
            request.getContent(),
            request.getProductCategory(),
            request.getScene(),
            request.getIntent(),
            request.getPolicyVersion(),
            toJsonString(request.getTags()),
            toJsonString(request.getMetadata())
        );

        log.info("Created knowledge document id={}, title={}", documentId, request.getTitle());

        // 2. 切片并生成向量
        List<String> chunks = splitContent(request.getContent(), 700);
        log.info("Split content into {} chunks", chunks.size());

        // 3. 调用Python Agent生成embeddings
        List<Map<String, Object>> chunkRecords = generateEmbeddings(documentId, request, chunks);

        // 4. 批量插入chunks
        String insertChunkSql = """
            INSERT INTO knowledge_chunk (
                document_id, document_type, chunk_index, chunk_text, embedding, metadata, create_time
            ) VALUES (?, ?, ?, ?, ?::vector, ?::jsonb, NOW())
            """;

        for (Map<String, Object> record : chunkRecords) {
            pgJdbcTemplate.update(
                insertChunkSql,
                documentId,
                request.getSourceType(),
                record.get("chunk_index"),
                record.get("chunk_text"),
                record.get("embedding"), // 格式: "[0.1,0.2,...]"
                record.get("metadata")
            );
        }

        log.info("Inserted {} chunks for document id={}", chunkRecords.size(), documentId);

        return Map.of(
            "documentId", documentId,
            "title", request.getTitle(),
            "chunkCount", chunks.size()
        );
    }

    /**
     * 批量上传
     */
    @Transactional(transactionManager = "pgTransactionManager")
    public Map<String, Object> batchUploadKnowledge(List<KnowledgeUploadDto.UploadRequest> requests) {
        List<Long> documentIds = new ArrayList<>();
        int totalChunks = 0;

        for (KnowledgeUploadDto.UploadRequest request : requests) {
            try {
                Map<String, Object> result = uploadKnowledge(request);
                documentIds.add((Long) result.get("documentId"));
                totalChunks += (Integer) result.get("chunkCount");
            } catch (Exception e) {
                log.error("Failed to upload knowledge: {}", request.getTitle(), e);
            }
        }

        return Map.of(
            "successCount", documentIds.size(),
            "totalDocuments", requests.size(),
            "totalChunks", totalChunks,
            "documentIds", documentIds
        );
    }

    /**
     * 查询知识库列表
     */
    public List<KnowledgeUploadDto.KnowledgeInfo> listKnowledge(String sourceType, String merchantCode, Integer page, Integer pageSize) {
        StringBuilder sql = new StringBuilder("""
            SELECT
                d.id, d.source_type, d.source_code, d.merchant_code, d.title, d.content,
                d.product_category, d.scene, d.intent, d.policy_version,
                d.tags, d.metadata, d.status, d.created_at, d.updated_at,
                COUNT(c.id) as chunk_count
            FROM knowledge_document d
            LEFT JOIN knowledge_chunk c ON c.document_id = d.id
            WHERE d.status = 1
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

        sql.append(" GROUP BY d.id ORDER BY d.created_at DESC");
        sql.append(" LIMIT ? OFFSET ?");
        params.add(pageSize);
        params.add((page - 1) * pageSize);

        return pgJdbcTemplate.query(sql.toString(), params.toArray(), (rs, rowNum) -> {
            KnowledgeUploadDto.KnowledgeInfo info = new KnowledgeUploadDto.KnowledgeInfo();
            info.setId(rs.getLong("id"));
            info.setSourceType(rs.getString("source_type"));
            info.setSourceCode(rs.getString("source_code"));
            info.setMerchantCode(rs.getString("merchant_code"));
            info.setTitle(rs.getString("title"));
            info.setContent(rs.getString("content"));
            info.setProductCategory(rs.getString("product_category"));
            info.setScene(rs.getString("scene"));
            info.setIntent(rs.getString("intent"));
            info.setPolicyVersion(rs.getString("policy_version"));
            info.setStatus(rs.getInt("status"));
            info.setCreatedAt(rs.getTimestamp("created_at").toLocalDateTime());
            info.setUpdatedAt(rs.getTimestamp("updated_at").toLocalDateTime());
            info.setChunkCount(rs.getInt("chunk_count"));
            return info;
        });
    }

    /**
     * 更新知识库
     */
    @Transactional(transactionManager = "pgTransactionManager")
    public Map<String, Object> updateKnowledge(Long id, KnowledgeUploadDto.UpdateRequest request) {
        // 1. 更新文档
        String updateSql = """
            UPDATE knowledge_document
            SET title = COALESCE(?, title),
                content = COALESCE(?, content),
                product_category = COALESCE(?, product_category),
                scene = COALESCE(?, scene),
                intent = COALESCE(?, intent),
                policy_version = COALESCE(?, policy_version),
                tags = COALESCE(?::jsonb, tags),
                metadata = COALESCE(?::jsonb, metadata),
                status = COALESCE(?, status),
                updated_at = NOW()
            WHERE id = ?
            """;

        pgJdbcTemplate.update(
            updateSql,
            request.getTitle(),
            request.getContent(),
            request.getProductCategory(),
            request.getScene(),
            request.getIntent(),
            request.getPolicyVersion(),
            toJsonString(request.getTags()),
            toJsonString(request.getMetadata()),
            request.getStatus(),
            id
        );

        // 2. 如果content更新了，需要重新生成向量
        if (request.getContent() != null) {
            // 删除旧的chunks
            pgJdbcTemplate.update("DELETE FROM knowledge_chunk WHERE document_id = ?", id);

            // 重新生成（TODO: 实现）
            log.info("Content updated for document id={}, need to regenerate embeddings", id);
        }

        return Map.of("documentId", id, "updated", true);
    }

    /**
     * 删除知识库
     */
    @Transactional(transactionManager = "pgTransactionManager")
    public void deleteKnowledge(Long id) {
        // 软删除
        pgJdbcTemplate.update("UPDATE knowledge_document SET status = 0, updated_at = NOW() WHERE id = ?", id);
        log.info("Soft deleted knowledge document id={}", id);
    }

    /**
     * 重建所有向量索引
     */
    public Map<String, Object> reindexAll() {
        // TODO: 调用Python Agent的reindex接口
        log.info("Reindex all knowledge documents");
        return Map.of("message", "Reindex started");
    }

    /**
     * 测试知识库检索
     */
    public List<Map<String, Object>> testRetrieval(String query, String merchantCode, Integer topK) {
        // TODO: 调用Python Agent的检索接口
        log.info("Test retrieval: query={}, merchantCode={}, topK={}", query, merchantCode, topK);
        return List.of();
    }

    /**
     * 切分文本为chunks
     */
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
        int overlapSize = (int) (maxChunkSize * 0.2); // 20%重叠

        while (start < normalized.length()) {
            int end = Math.min(start + maxChunkSize, normalized.length());
            chunks.add(normalized.substring(start, end));
            start += maxChunkSize - overlapSize;
        }

        return chunks;
    }

    /**
     * 调用Python Agent生成embeddings
     */
    private List<Map<String, Object>> generateEmbeddings(
        Long documentId,
        KnowledgeUploadDto.UploadRequest request,
        List<String> chunks
    ) {
        try {
            // 调用Python Agent的embedding接口
            Map<String, Object> requestBody = Map.of(
                "chunks", chunks,
                "document_id", documentId,
                "document_type", request.getSourceType()
            );

            String url = pythonAgentUrl + "/api/embeddings";
            Map<String, Object> response = restTemplate.postForObject(url, requestBody, Map.class);

            if (response != null && response.containsKey("embeddings")) {
                List<List<Double>> embeddings = (List<List<Double>>) response.get("embeddings");

                List<Map<String, Object>> records = new ArrayList<>();
                for (int i = 0; i < chunks.size(); i++) {
                    Map<String, Object> metadata = new HashMap<>();
                    metadata.put("title", request.getTitle());
                    metadata.put("source_type", request.getSourceType());
                    metadata.put("merchant_code", request.getMerchantCode());
                    metadata.put("product_category", request.getProductCategory());
                    metadata.put("scene", request.getScene());
                    metadata.put("intent", request.getIntent());

                    String embeddingVector = embeddings.get(i).stream()
                        .map(String::valueOf)
                        .collect(Collectors.joining(",", "[", "]"));

                    records.add(Map.of(
                        "chunk_index", i,
                        "chunk_text", chunks.get(i),
                        "embedding", embeddingVector,
                        "metadata", toJsonString(metadata)
                    ));
                }

                return records;
            }
        } catch (Exception e) {
            log.error("Failed to generate embeddings via Python Agent", e);
        }

        // 降级：不生成向量，只返回待处理记录。调用方应避免写入空向量。
        List<Map<String, Object>> fallbackRecords = new ArrayList<>();
        for (int i = 0; i < chunks.size(); i++) {
            Map<String, Object> record = new HashMap<>();
            record.put("chunk_index", i);
            record.put("chunk_text", chunks.get(i));
            record.put("embedding", "[]");
            record.put("metadata", "{}");
            fallbackRecords.add(record);
        }
        return fallbackRecords;
    }

    private String toJsonString(Object obj) {
        if (obj == null) return null;
        try {
            return new com.fasterxml.jackson.databind.ObjectMapper().writeValueAsString(obj);
        } catch (Exception e) {
            return "{}";
        }
    }
}
