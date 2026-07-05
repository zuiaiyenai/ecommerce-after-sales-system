package com.ecommerce.aftersales.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Data
@TableName("review_info")
public class ReviewInfo {

    @TableId
    private Long id;

    private Long orderId;

    private Long userId;

    private Integer productScore;

    private Integer logisticsScore;

    private Integer serviceScore;

    private Integer afterSaleScore;

    private Integer overallScore;

    private String content;

    private String images;

    private Integer isAnonymous;

    private String sentiment;

    private BigDecimal sentimentScore;

    private String topics;

    private Integer status;

    @TableLogic
    private Integer deleted;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updateTime;
}
