package com.ecommerce.aftersales.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("after_sales_event_outbox")
public class AfterSalesEventOutbox {

    @TableId(type = IdType.ASSIGN_ID)
    private Long id;

    private String eventId;

    private String eventType;

    private String topic;

    private String aggregateType;

    private Long aggregateId;

    private String payload;

    private String status;

    private Integer retryCount;

    private String lastError;

    private LocalDateTime nextRetryTime;

    private LocalDateTime publishedTime;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updateTime;
}
