package com.ecommerce.aftersales.dto;

import lombok.Data;

import java.util.List;

public final class UserChatDtos {

    private UserChatDtos() {
    }

    @Data
    public static class CreateSessionRequest {
        private Long afterSaleId;
        private Long orderId;
        private String merchantCode;
        private String message;
    }

    @Data
    public static class CreateSessionResponse {
        private Long sessionId;
        private String sessionNo;
        private String merchantCode;
        private String mode;
        private String status;
        private String welcomeMessage;
    }

    @Data
    public static class SendMessageRequest {
        private Long sessionId;
        private String message;
        private String messageType;
    }

    @Data
    public static class HideSessionRequest {
        private Long sessionId;
    }

    @Data
    public static class ChatEvaluationRequest {
        private Long sessionId;
        private Integer rating;
        private String content;
        private Integer responseSpeedScore;
        private Integer serviceAttitudeScore;
        private Integer professionalScore;
        private Integer efficiencyScore;
    }

    @Data
    public static class SendMessageResponse {
        private Long sessionId;
        private String mode;
        private String status;
        private String reply;
        private String message;
    }

    @Data
    public static class ChatMessageView {
        private Long id;
        private String role;
        private String content;
        private String messageType;
        private String createTime;
    }

    @Data
    public static class ChatHistoryResponse {
        private Long sessionId;
        private String mode;
        private String status;
        private List<ChatMessageView> list;
    }

    @Data
    public static class ChatSessionSummary {
        private Long sessionId;
        private Long orderId;
        private Long afterSaleId;
        private String title;
        private String mode;
        private String status;
        private String lastMessage;
        private String lastMessageTime;
        private String evaluationStatus;
    }

    @Data
    public static class ChatSessionListResponse {
        private List<ChatSessionSummary> list;
    }
}
