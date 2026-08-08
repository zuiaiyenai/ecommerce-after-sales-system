package com.ecommerce.aftersales.dto;

import com.ecommerce.aftersales.common.OffsetLocalDateTimeSerializer;
import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;
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
        @JsonSerialize(using = ToStringSerializer.class)
        private Long orderId;
        private String orderNo;
        @JsonSerialize(using = ToStringSerializer.class)
        private Long userId;
        @JsonSerialize(using = ToStringSerializer.class)
        private Long merchantId;
        private String merchantCode;
        private String status;
        private BigDecimal amount;
        private String productName;
        private String category;
        @JsonSerialize(using = OffsetLocalDateTimeSerializer.class)
        private LocalDateTime createTime;
        @JsonSerialize(using = ToStringSerializer.class)
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
    public static class TicketResult {
        @JsonSerialize(using = ToStringSerializer.class)
        private Long ticketId;
        private String ticketNo;
        @JsonSerialize(using = ToStringSerializer.class)
        private Long orderId;
        private String orderNo;
        @JsonSerialize(using = ToStringSerializer.class)
        private Long userId;
        @JsonSerialize(using = ToStringSerializer.class)
        private Long merchantId;
        private String merchantCode;
        private String status;
        private String afterSalesType;
        private String reason;
        private String reasonDetail;
        private String description;
        private BigDecimal refundAmount;
        private Boolean existing;
        private String productName;
        private String category;
        private String policyVersion;
        private String contextVersion;
        @JsonSerialize(using = OffsetLocalDateTimeSerializer.class)
        private LocalDateTime afterSalesAppliedAt;
        private String verdict;
        private String aiReviewResult;
        private String aiReviewStatus;
        private String reviewRequestId;
        private Boolean reviewApplied;
        private Boolean idempotentReplay;
        private String reviewRejectReason;
        private List<String> evidenceUrls;
    }

    @Data
    public static class SubmitAiReviewRequest {
        private Long userId;
        private Long sessionId;
        private String reviewRequestId;
        private Long ticketId;
        private String orderId;
        private String agentArchitecture;
        private String contextVersion;
        private String verdict;
        private String aiReviewStatus;
        @JsonAlias("aiConfidence")
        private BigDecimal aiReviewConfidence;
        private BigDecimal modelConfidence;
        private String confidenceModelVersion;
        private Map<String, Object> confidenceBreakdown;
        private String reason;
        private List<String> evidenceNeeded;
        private Boolean visualUncertain;
        private Boolean policyUncertain;
        private Boolean evidenceConsistent;
        private String filterLevel;
        private Boolean rerankerSucceeded;
        private Boolean trustedPolicyEligible;
        private String policyVersion;
        private BigDecimal visualConfidence;
        private String knowledgeRetrievalMode;
        private BigDecimal policyMatchScore;
        private List<String> riskReviewReasons;
        private List<Map<String, Object>> policyCitations;
        private Map<String, String> skillVersions;
        private Map<String, Object> imageReview;
        private Map<String, Object> specialistAssessments;
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
        @JsonSerialize(using = ToStringSerializer.class)
        private Long sessionId;
        private String sessionNo;
        private String mode;
        private String status;
        @JsonSerialize(using = ToStringSerializer.class)
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
        private String fileUrl;
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
        @JsonSerialize(using = ToStringSerializer.class)
        private Long messageId;
        @JsonSerialize(using = ToStringSerializer.class)
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
