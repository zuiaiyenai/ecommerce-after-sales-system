package com.ecommerce.aftersales.dto;

import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import lombok.Data;

import java.util.List;

public final class UserChatDtos {

    private UserChatDtos() {
    }

    @Data
    public static class CreateSessionRequest {
        private Long ticketId;
        private Long orderId;
        private String merchantCode;
        private String message;
    }

    @Data
    public static class CreateSessionResponse {
        @JsonSerialize(using = ToStringSerializer.class)
        private Long sessionId;
        private String sessionNo;
        private String merchantCode;
        private String merchantDisplayName;
        private String mode;
        private String status;
        private String welcomeMessage;
    }

    @Data
    public static class SendMessageRequest {
        private Long sessionId;
        private String message;
        private String messageType;
        private String fileUrl;
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
        @JsonSerialize(using = ToStringSerializer.class)
        private Long sessionId;
        private String mode;
        private String status;
        private String reply;
        private String message;
    }

    @Data
    public static class ChatMessageView {
        @JsonSerialize(using = ToStringSerializer.class)
        private Long messageId;
        private String role;
        private String content;
        private String messageType;
        private String fileUrl;
        private String createTime;
    }

    @Data
    public static class ChatHistoryResponse {
        @JsonSerialize(using = ToStringSerializer.class)
        private Long sessionId;
        private String merchantCode;
        private String merchantDisplayName;
        private String mode;
        private String status;
        private List<ChatMessageView> list;
        private Boolean hasMore;
        @JsonSerialize(using = ToStringSerializer.class)
        private Long nextBeforeMessageId;
    }

    @Data
    public static class ChatSessionSummary {
        @JsonSerialize(using = ToStringSerializer.class)
        private Long sessionId;
        @JsonSerialize(using = ToStringSerializer.class)
        private Long orderId;
        @JsonSerialize(using = ToStringSerializer.class)
        private Long ticketId;
        private String title;
        private String merchantCode;
        private String merchantDisplayName;
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
