package com.ecommerce.aftersales.dto;

import lombok.Data;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

public class KnowledgeUploadDto {

    /**
     * 上传知识库请求
     */
    @Data
    public static class UploadRequest {
        /**
         * 知识库类型：after_sales_policy（售后政策）、faq（常见问题）、product_knowledge（商品知识）、guideline（操作指南）
         */
        private String sourceType;

        /**
         * 知识库编码（唯一标识）
         */
        private String sourceCode;

        /**
         * 商户代码
         */
        private String merchantCode = "MERCHANT_DEMO";

        /**
         * 标题
         */
        private String title;

        /**
         * 内容（会自动切片）
         */
        private String content;

        /**
         * 商品分类（可选）
         */
        private String productCategory;

        /**
         * 场景（damage, quality_issue, return, exchange等）
         */
        private String scene;

        /**
         * 意图（refund, exchange, evidence_requirement等）
         */
        private String intent;

        /**
         * 政策版本
         */
        private String policyVersion = "v1.0";

        /**
         * 标签（可选）
         */
        private List<String> tags;

        /**
         * 元数据（可选）
         */
        private Map<String, Object> metadata;
    }

    /**
     * 更新知识库请求
     */
    @Data
    public static class UpdateRequest {
        private String title;
        private String content;
        private String productCategory;
        private String scene;
        private String intent;
        private String policyVersion;
        private List<String> tags;
        private Map<String, Object> metadata;
        private Integer status; // 1-启用 0-禁用
    }

    /**
     * 知识库信息
     */
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
        private LocalDateTime createdAt;
        private LocalDateTime updatedAt;
        private Integer chunkCount; // 切分的chunk数量
    }
}
