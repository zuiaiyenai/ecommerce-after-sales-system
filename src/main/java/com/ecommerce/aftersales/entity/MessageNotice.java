package com.ecommerce.aftersales.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("message_notice")
public class MessageNotice {

    @TableId
    private Long id;

    private Long userId;

    private String title;

    private String content;

    private String noticeType;

    private Long refId;

    private String refType;

    private Integer isRead;

    private LocalDateTime readTime;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;
}
