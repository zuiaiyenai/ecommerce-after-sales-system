package com.ecommerce.aftersales.dto;

import lombok.Data;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

public class KnowledgeUploadDto {

    @Data
    public static class UploadRequest {
        private String sourceType;
        private String sourceCode;
        private String merchantCode = "MERCHANT_DEMO";
        private String title;
        private String content;
        private String productCategory;
        private String scene;
        private String intent;
        private String policyVersion = "v1.0";
        private List<String> tags;
        private Map<String, Object> metadata;
        private Integer status;
    }

    @Data
    public static class TextImportRequest {
        private String title;
        private String knowledgeType;
        private String scope = "MERCHANT";
        private String merchantCode;
        private String status = "ENABLED";
        private String content;
    }

    @Data
    public static class UpdateRequest {
        private String title;
        private String merchantCode;
        private Integer status;
        private String content;
        private Map<String, Object> metadata;
    }

    @Data
    public static class KnowledgeInfo {
        private Long id;
        private String sourceType;
        private String sourceCode;
        private String merchantCode;
        private String title;
        private String content;
        private String productCategory;
        private String scene;
        private String intent;
        private String policyVersion;
        private List<String> tags;
        private Map<String, Object> metadata;
        private Integer status;
        private Integer chunkCount;
        private String ingestionStatus;
        private String ingestionSourceType;
        private String fileName;
        private String fileUrl;
        private String errorMessage;
        private String scope;
        private LocalDateTime createdAt;
        private LocalDateTime updatedAt;
    }
}
