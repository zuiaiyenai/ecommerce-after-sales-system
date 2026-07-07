package com.ecommerce.aftersales.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

public final class InternalAgentToolDtos {

    private InternalAgentToolDtos() {
    }

    @Data
    public static class OrderSearchRequest {
        private Long userId;
        private String keyword;
        private List<String> statusFilter;
    }

    @Data
    public static class OrderSummary {
        private Long id;
        private String orderNo;
        private Long userId;
        private Long merchantId;
        private String merchantCode;
        private String status;
        private BigDecimal amount;
        private String productName;
        private String category;
        private Long existingTicketId;
        private String existingTicketNo;
        private String existingTicketStatus;
    }

    @Data
    public static class OrderDetailRequest {
        private Long userId;
        private String orderId;
    }

    @Data
    public static class ExistingAfterSalesRequest {
        private Long userId;
        private String orderId;
    }

    @Data
    public static class CreateTicketRequest {
        private Long userId;
        private Long sessionId;
        private String orderId;
        private String afterSalesType;
        private String reason;
        private String reasonDetail;
        private String description;
        private BigDecimal refundAmount;
        private BigDecimal aiConfidence;
        private String aiRecommendType;
        private String policyCode;
        private String policyVersion;
        private List<String> evidenceUrls;
        private Map<String, Object> aiClassifyResult;
        private Boolean autoApproved;
    }

    @Data
    public static class TicketResult {
        private Long id;
        private String ticketNo;
        private Long orderId;
        private String orderNo;
        private Long userId;
        private String merchantCode;
        private String status;
        private String afterSalesType;
        private BigDecimal refundAmount;
        private Boolean existing;
    }

    @Data
    public static class HandoffRequest {
        private Long userId;
        private Long sessionId;
        private String orderId;
        private Long ticketId;
        private String summary;
        private String emotionLabel;
        private BigDecimal emotionScore;
        private BigDecimal emotionConfidence;
    }

    @Data
    public static class SessionResult {
        private Long sessionId;
        private String sessionNo;
        private String mode;
        private String status;
        private Long ticketId;
    }

    @Data
    public static class AppendMessageRequest {
        private Long userId;
        private Long sessionId;
        private String orderId;
        private Long ticketId;
        private String role;
        private String content;
        private String messageType;
        private BigDecimal confidence;
        private String emotionLabel;
        private BigDecimal emotionScore;
        private BigDecimal emotionConfidence;
        private String knowledgeQuery;
        private String knowledgeRetrievalMode;
        private Integer knowledgeHitCount;
        private String knowledgeHitsJson;
        private String knowledgeTraceJson;
    }

    @Data
    public static class MessageResult {
        private Long messageId;
        private Long sessionId;
    }

    @Data
    public static class MissingEvidenceRequest {
        private Long userId;
        private Long sessionId;
        private String orderId;
        private Long ticketId;
        private List<String> evidenceNeeded;
        private String assistantReply;
    }
}
