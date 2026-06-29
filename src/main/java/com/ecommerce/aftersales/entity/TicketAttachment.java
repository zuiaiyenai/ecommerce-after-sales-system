package com.ecommerce.aftersales.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("ticket_attachment")
public class TicketAttachment {

    @TableId
    private Long id;

    private Long ticketId;

    private String fileUrl;

    private String fileType;

    private String fileName;

    private Long fileSize;

    private Integer sortOrder;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;
}
