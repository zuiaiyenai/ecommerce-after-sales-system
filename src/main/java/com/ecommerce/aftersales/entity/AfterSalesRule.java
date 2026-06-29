package com.ecommerce.aftersales.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Data
@TableName("after_sales_rule")
public class AfterSalesRule {

    @TableId
    private Long id;

    private String ruleName;

    private String ruleCode;

    private String productCategory;

    private String orderStatus;

    private String afterSaleType;

    private String reason;

    private BigDecimal minAmount;

    private BigDecimal maxAmount;

    private Integer timeLimitDays;

    private String freightPayer;

    private String auditMode;

    private String autoAuditCondition;

    private String dispatchRule;

    private Integer priority;

    private Integer status;

    private Long operatorId;

    @TableLogic
    private Integer deleted;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updateTime;
}
