package com.ecommerce.aftersales.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("agent_tool_call")
public class AgentToolCall {

    @TableId
    private Long id;

    private Long sessionId;

    private Long messageId;

    private String toolName;

    private String toolInput;

    private String toolOutput;

    private String status;

    private String errorMsg;

    private Integer durationMs;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;
}
