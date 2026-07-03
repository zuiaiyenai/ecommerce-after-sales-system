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
        private Boolean humanOnline;
        private String humanStatus;
        private String welcomeMessage;
    }

    @Data
    public static class SendMessageRequest {
        private Long sessionId;
        private String message;
        private String messageType;
    }

    @Data
    public static class SendMessageResponse {
        private Long sessionId;
        private String mode;
        private String status;
        private Boolean humanOnline;
        private String humanStatus;
        private String reply;
        private String message;
    }

    @Data
    public static class ServiceStatusResponse {
        private String merchantCode;
        private Boolean aiOnline;
        private Boolean humanOnline;
        private String humanStatus;
    }

    @Data
    public static class ChatMessageView {
        private Long id;
        private String role;
        private String content;
        private String messageType;
        private Boolean read;
        private String createTime;
    }

    @Data
    public static class ChatHistoryResponse {
        private Long sessionId;
        private List<ChatMessageView> list;
    }
}
