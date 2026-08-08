package com.ecommerce.aftersales.dto;

import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
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
    @JsonSerialize(using = ToStringSerializer.class)
    private Long sessionId;
    private String role;        // USER, ASSISTANT, SYSTEM
    private String content;
    private String messageType; // TEXT, IMAGE
    private String fileUrl;
    private String createdAt;
}
