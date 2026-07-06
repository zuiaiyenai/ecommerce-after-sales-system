package com.ecommerce.aftersales.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Data
@TableName("chat_session")
public class ChatSession {

    @TableId
    private Long id;

    private String sessionNo;

    private Long userId;

    private Long merchantId;

    private String merchantCode;

    private String policyCode;

    private String policyVersion;

    private Long orderId;

    private Long ticketId;

    private Long humanAgentId;

    private String mode;

    private String status;

    private BigDecimal emotionScore;

    private BigDecimal emotionConfidence;

    private String emotionLabel;

    private String userQuery;

    private Integer resolved;

    private Integer satisfaction;

    private LocalDateTime closeTime;

    @TableLogic
    private Integer deleted;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updateTime;
}
