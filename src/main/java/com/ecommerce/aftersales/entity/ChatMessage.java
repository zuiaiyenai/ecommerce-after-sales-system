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

    /** AI回复置信度(0~1)，表示回复生成/选用把握度。 */
    private BigDecimal confidence;

    private String emotionLabel;

    private BigDecimal emotionScore;

    /** 情绪判断置信度(0~1)。 */
    private BigDecimal emotionConfidence;

    private String knowledgeQuery;

    private String knowledgeRetrievalMode;

    private Integer knowledgeHitCount;

    private String knowledgeHitsJson;

    private String knowledgeTraceJson;

    private Integer tokenUsage;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;
}
