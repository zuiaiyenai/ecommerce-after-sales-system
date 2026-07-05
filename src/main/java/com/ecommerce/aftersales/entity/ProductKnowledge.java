package com.ecommerce.aftersales.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("product_knowledge")
public class ProductKnowledge {

    @TableId
    private Long id;

    private Long productId;

    private String productName;

    private String title;

    private String content;

    private Integer chunkCount;

    private Integer vectorStatus;

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
