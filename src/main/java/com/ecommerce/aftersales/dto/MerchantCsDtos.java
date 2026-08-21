package com.ecommerce.aftersales.dto;

import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

public final class MerchantCsDtos {

    private MerchantCsDtos() {
    }

    @Data
    public static class LoginRequest {
        private String account;
        private String password;
        private String merchantCode;
        private String clientType;
        private String deviceId;
    }

    @Data
    public static class RegisterRequest {
        private String account;
        private String password;
        private String realName;
        private String phone;
        private String code;
    }

    @Data
    public static class AuthCodeRequest {
        private String account;
        private String phone;
        private String scene;
    }

    @Data
    public static class ResetPasswordRequest {
        private String account;
        private String phone;
        private String code;
        private String newPassword;
        private String confirmPassword;
    }

    @Data
    public static class LoginResponse {
        private String token;
        private StaffProfile staff;
    }

    @Data
    public static class StaffProfile {
        @JsonSerialize(using = ToStringSerializer.class)
        private Long staffId;
        private String staffNo;
        private String merchantCode;
        private String account;
        private String realName;
        private String phone;
        private String role;
        private String onlineStatus;
        private String accountStatus;
        private Integer maxSessionCount;
    }

    @Data
    public static class WorkStatusRequest {
        private String onlineStatus;
    }

    @Data
    public static class DashboardOverview {
        private String greeting;
        private String subtitle;
        private Integer todayTodoCount;
        private Boolean aiEnabled;
        private List<MetricItem> metrics;
        private List<TimelineItem> timeline;
    }

    @Data
    public static class MetricItem {
        private String title;
        private Object value;
        private String trend;
        private String accent;
    }

    @Data
    public static class TimelineItem {
        private String time;
        private String title;
        private String type;
    }

    @Data
    public static class TodoItem {
        @JsonSerialize(using = ToStringSerializer.class)
        private Long id;
        private String title;
        private String tag;
        private String amount;
        private String priority;
        private String priorityTone;
        private String action;
        private String target;
    }

    @Data
    public static class DashboardPerformance {
        private Integer serviceScore;
        private String scoreStatus;
        private String trendSummary;
        private List<String> tags;
        private List<PerformanceTrendPoint> trend;
        private List<PerformanceMetric> metrics;
    }

    @Data
    public static class PerformanceTrendPoint {
        private String day;
        private Integer score;
    }

    @Data
    public static class PerformanceMetric {
        private String label;
        private String value;
        private String desc;
        private Integer currentPercent;
        private Integer targetPercent;
        private Integer sampleSize;
        private Boolean lowerIsBetter;
    }

    @Data
    public static class SessionView {
        @JsonSerialize(using = ToStringSerializer.class)
        private Long sessionId;
        private String sessionNo;
        private String merchantCode;
        @JsonSerialize(using = ToStringSerializer.class)
        private Long userId;
        @JsonSerialize(using = ToStringSerializer.class)
        private Long orderId;
        @JsonSerialize(using = ToStringSerializer.class)
        private Long ticketId;
        @JsonSerialize(using = ToStringSerializer.class)
        private Long serviceId;
        private String user;
        private String topic;
        private String level;
        private String wait;
        private String emotion;
        private String emotionLabel;
        private BigDecimal emotionScore;
        private BigDecimal emotionConfidence;
        private String sourceChannel;
        private Integer serviceUnreadCount;
        private String orderNo;
        private String product;
        private String productName;
        private String ticketNo;
        private String lastMessageContent;
        private String lastMessageSender;
        private String lastMessageTime;
        private String replyStatus;
        private String emotionTrend;
        private String riskLevel;
        private Integer priorityScore;
        private String aiSummary;
        private String status;
        private String evaluationRequestedAt;
        private String evaluatedAt;
        private Integer rating;
        private String evaluationStatus;
    }

    @Data
    public static class MessageView {
        @JsonSerialize(using = ToStringSerializer.class)
        private Long messageId;
        @JsonSerialize(using = ToStringSerializer.class)
        private Long sessionId;
        @JsonSerialize(using = ToStringSerializer.class)
        private Long senderId;
        private String sender;
        private String senderRole;
        private String messageType;
        private String content;
        private String fileUrl;
        private String aiIntent;
        private BigDecimal aiReplyConfidence;
        private String emotionLabel;
        private BigDecimal emotionScore;
        private BigDecimal emotionConfidence;
        private String knowledgeQuery;
        private String knowledgeRetrievalMode;
        private Integer knowledgeHitCount;
        private List<KnowledgeHitView> knowledgeHits;
        private Map<String, Object> knowledgeTrace;
        private String createdAt;
    }

    @Data
    public static class SessionAiAssistView {
        @JsonSerialize(using = ToStringSerializer.class)
        private Long sessionId;
        private RecommendationView recommendation;
        private QuickReplyView staffSuggestion;
        private List<QuickReplyView> quickReplies;
        private String quickReplySource;
        private String latestUserMessage;
        private String sceneCode;
        private String intentCode;
        private String knowledgeQuery;
        private String knowledgeRetrievalMode;
        private List<KnowledgeHitView> knowledgeHits;
        private Map<String, Object> handoffSummary;
        private String handoffSummaryText;
        private Map<String, String> conversationDigest;
        private Map<String, Object> trace;
    }

    @Data
    public static class RecommendationView {
        private String text;
        private BigDecimal confidence;
        private String source;
        private String reason;
        private String intentCode;
        private String sceneCode;
        private String tone;
    }

    @Data
    public static class QuickReplyView {
        private String code;
        private String label;
        private String text;
        private String sceneCode;
        private String intentCode;
        private String tone;
        private BigDecimal score;
    }

    @Data
    public static class KnowledgeHitView {
        private String sourceType;
        private String sourceCode;
        private String title;
        private String summary;
        private String snippet;
        private BigDecimal score;
        private List<String> tags;
        private Map<String, Object> metadata;
    }

    @Data
    public static class SendMessageRequest {
        private String messageType;
        private String content;
        private String fileUrl;
    }

    @Data
    public static class EvaluationRequest {
        private Integer rating;
        private String content;
    }

    @Data
    public static class TicketView {
        @JsonSerialize(using = ToStringSerializer.class)
        private Long ticketId;
        private String ticketNo;
        private String merchantCode;
        @JsonSerialize(using = ToStringSerializer.class)
        private Long orderId;
        private String orderNo;
        @JsonSerialize(using = ToStringSerializer.class)
        private Long userId;
        private String title;
        private String status;
        private String afterSalesType;
        private String reasonType;
        private String applyRefundAmount;
        private String approvedRefundAmount;
        private String refundStatus;
        private BigDecimal aiReviewConfidence;
        private String priority;
        private String responsibility;
        @JsonSerialize(using = ToStringSerializer.class)
        private Long assignedServiceId;
        private String auditOpinion;
        private String rejectReason;
        private String expectedFinishTime;
        private String auditTime;
        private String completeTime;
    }

    @Data
    public static class TicketLogView {
        @JsonSerialize(using = ToStringSerializer.class)
        private Long id;
        @JsonSerialize(using = ToStringSerializer.class)
        private Long ticketId;
        @JsonSerialize(using = ToStringSerializer.class)
        private Long operatorId;
        private String operatorRole;
        private String oldStatus;
        private String newStatus;
        private String actionType;
        private String actionDesc;
        private String createdAt;
    }

    @Data
    public static class TicketApproveRequest {
        private String auditOpinion;
    }

    @Data
    public static class TicketRejectRequest {
        private String rejectReason;
    }

    @Data
    public static class TicketCompleteRequest {
        private String completeNote;
    }

    @Data
    public static class OrderView {
        @JsonSerialize(using = ToStringSerializer.class)
        private Long orderId;
        private String orderNo;
        private String merchantCode;
        @JsonSerialize(using = ToStringSerializer.class)
        private Long userId;
        private String user;
        private String phone;
        private String product;
        private String amount;
        private String status;
        private String logistics;
        @JsonSerialize(using = ToStringSerializer.class)
        private Long relatedTicketId;
        private String createdAt;
    }

    @Data
    public static class OrderDetail {
        @JsonSerialize(using = ToStringSerializer.class)
        private Long orderId;
        private String orderNo;
        private String merchantCode;
        private String user;
        private String phone;
        private String address;
        private String status;
        private String payAmount;
        private String payTime;
        private List<OrderProductItem> productItems;
        private LogisticsInfo logistics;
        @JsonSerialize(using = ToStringSerializer.class)
        private Long relatedTicketId;
    }

    @Data
    public static class OrderProductItem {
        @JsonSerialize(using = ToStringSerializer.class)
        private Long productId;
        private String productName;
        private Integer quantity;
        private String price;
    }

    @Data
    public static class LogisticsInfo {
        private String company;
        private String trackingNo;
        private String status;
    }

    @Data
    public static class NoticeView {
        @JsonSerialize(using = ToStringSerializer.class)
        private Long id;
        private String level;
        private String title;
        private String content;
        private String target;
        private String readStatus;
        private String createdAt;
    }

    @Data
    public static class ProductView {
        @JsonSerialize(using = ToStringSerializer.class)
        private Long id;
        private String merchantCode;
        private String productName;
        private String productCode;
        private String category;
        private String description;
        private String mainImage;
        private List<String> images;
        private BigDecimal price;
        private String status;
        private String createdAt;
        private String updatedAt;
    }

    @Data
    public static class ProductUpsertRequest {
        private String productName;
        private String productCode;
        private String category;
        private String description;
        private String mainImage;
        private List<String> images;
        private BigDecimal price;
        private String status;
    }

    @Data
    public static class ProductStatusRequest {
        private String status;
    }

    @Data
    public static class ReviewView {
        @JsonSerialize(using = ToStringSerializer.class)
        private Long id;
        @JsonSerialize(using = ToStringSerializer.class)
        private Long orderId;
        private Integer overallScore;
        private String orderNo;
        private String user;
        private String productName;
        private String ticketNo;
        private String content;
        private String productImage;
        private String createdAt;
        private Integer responseSpeedScore;
        private Integer serviceAttitudeScore;
        private Integer professionalScore;
        private Integer efficiencyScore;
    }
}
