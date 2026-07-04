package com.ecommerce.aftersales.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.util.List;

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
    public static class LoginResponse {
        private String token;
        private StaffProfile staff;
    }

    @Data
    public static class StaffProfile {
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
        private List<PerformanceMetric> metrics;
    }

    @Data
    public static class PerformanceMetric {
        private String label;
        private String value;
        private String desc;
        private Integer currentPercent;
        private Integer targetPercent;
    }

    @Data
    public static class SessionView {
        private Long id;
        private String sessionNo;
        private String merchantCode;
        private Long userId;
        private Long orderId;
        private Long ticketId;
        private Long serviceId;
        private String user;
        private String topic;
        private String level;
        private String wait;
        private String emotion;
        private String sourceChannel;
        private Integer serviceUnreadCount;
        private String orderNo;
        private String product;
        private String productName;
        private String ticketNo;
        private String lastMessageContent;
        private String lastMessageTime;
        private String aiSummary;
        private String status;
        private String evaluationRequestedAt;
        private String evaluatedAt;
        private Integer rating;
        private String evaluationContent;
        private String evaluationStatus;
    }

    @Data
    public static class MessageView {
        private Long id;
        private Long sessionId;
        private Long senderId;
        private String senderRole;
        private String messageType;
        private String content;
        private String aiIntent;
        private String emotionLabel;
        private String createdAt;
    }

    @Data
    public static class SendMessageRequest {
        private String messageType;
        private String content;
    }

    @Data
    public static class EvaluationRequest {
        private Integer rating;
        private String content;
    }

    @Data
    public static class TicketView {
        private Long id;
        private String ticketNo;
        private String merchantCode;
        private Long orderId;
        private String orderNo;
        private Long userId;
        private String title;
        private String status;
        private String afterSalesType;
        private String reasonType;
        private String applyRefundAmount;
        private String approvedRefundAmount;
        private String refundStatus;
        private String priority;
        private String responsibility;
        private Long assignedServiceId;
        private String auditOpinion;
        private String rejectReason;
        private String expectedFinishTime;
        private String auditTime;
        private String completeTime;
    }

    @Data
    public static class TicketLogView {
        private Long id;
        private Long ticketId;
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
        private Long id;
        private String orderNo;
        private String merchantCode;
        private Long userId;
        private String user;
        private String phone;
        private String product;
        private String amount;
        private String status;
        private String logistics;
        private Long relatedTicketId;
        private String createdAt;
    }

    @Data
    public static class OrderDetail {
        private Long id;
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
        private Long relatedTicketId;
    }

    @Data
    public static class OrderProductItem {
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
        private Long id;
        private String level;
        private String title;
        private String content;
        private String target;
        private String readStatus;
        private String createdAt;
    }

    @Data
    public static class ReviewView {
        private Long id;
        private Long orderId;
        private String orderNo;
        private Long userId;
        private String user;
        private String productName;
        private String productImage;
        private String ticketNo;
        private Integer overallScore;
        private Integer responseSpeedScore;
        private Integer serviceAttitudeScore;
        private Integer professionalScore;
        private Integer efficiencyScore;
        private Integer productScore;
        private Integer logisticsScore;
        private Integer serviceScore;
        private Integer afterSaleScore;
        private String content;
        private String sentiment;
        private String createdAt;
    }

    @Data
    public static class ProductView {
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
}
