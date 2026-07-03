package com.ecommerce.aftersales.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Data
@TableName("chat_message")
public class ChatMessage {

    @TableId
    private Long id;

    private Long sessionId;

    private String role;

    private String content;

    private String messageType;

    private String toolCallId;

    private BigDecimal confidence;

    private String emotionLabel;

    private BigDecimal emotionScore;

    private Integer tokenUsage;

    private LocalDateTime readTime;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;
}
