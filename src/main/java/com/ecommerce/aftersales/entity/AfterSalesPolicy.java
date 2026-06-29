package com.ecommerce.aftersales.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;

import java.time.LocalDate;
import java.time.LocalDateTime;

@Data
@TableName("after_sales_policy")
public class AfterSalesPolicy {

    @TableId
    private Long id;

    private String policyName;

    private String policyCode;

    private String productCategory;

    private String content;

    private String summary;

    private Integer chunkCount;

    private Integer vectorStatus;

    private LocalDate effectiveDate;

    private LocalDate expireDate;

    private Integer status;

    private Integer version;

    private Long operatorId;

    @TableLogic
    private Integer deleted;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updateTime;
}
