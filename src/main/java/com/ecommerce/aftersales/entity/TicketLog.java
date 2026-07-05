package com.ecommerce.aftersales.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("ticket_log")
public class TicketLog {

    @TableId
    private Long id;

    private Long ticketId;

    private Long operatorId;

    private String operatorType;

    private String fromStatus;

    private String toStatus;

    private String action;

    private String content;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;
}
