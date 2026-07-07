package com.ecommerce.aftersales.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class WsChatMessage {
    private String action;      // "subscribe", "unsubscribe", "message"
    private String sessionId;
    private String role;        // USER, ASSISTANT, SYSTEM
    private String content;
    private String messageType; // TEXT, IMAGE
    private String createdAt;
}
