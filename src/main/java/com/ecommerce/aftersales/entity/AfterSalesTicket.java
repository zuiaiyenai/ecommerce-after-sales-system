package com.ecommerce.aftersales.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Data
@TableName("after_sales_ticket")
public class AfterSalesTicket {

    @TableId
    private Long id;

    private String ticketNo;

    private Long orderId;

    private String orderNo;

    private Long userId;

    private Long merchantId;

    private String merchantCode;

    private String productName;

    private String afterSaleType;

    private String reason;

    private String reasonDetail;

    private String description;

    private BigDecimal refundAmount;

    private String aiClassifyResult;

    private BigDecimal aiConfidence;

    private String aiRecommendType;

    private String status;

    private Integer priority;

    private Long assigneeId;

    private String auditOpinion;

    private LocalDateTime auditTime;

    private LocalDateTime expectedCompleteTime;

    private LocalDateTime completeTime;

    @TableLogic
    private Integer deleted;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updateTime;
}
